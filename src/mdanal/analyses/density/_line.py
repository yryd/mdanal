"""线密度：沿单轴的质量密度与电荷密度。

逐帧直方图自己累加，不用 MDAnalysis 的 LinearDensity：后者把盒尺寸在构造时抓成
一个"活视图"，遇到多段合并（ChainReader）或内存读取（MemoryReader）时视图不再
随帧更新，同一份数据会因读取方式不同而给出不同结果。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.units import constants

from ...plot import annotations, chart
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series
from ...errors import ValidationError

AXES = ("x", "y", "z")
AVOGADRO = constants["N_Avogadro"]
VOLUME_CONVERSION = 1e-24  # Å^3 → cm^3


SLOTS = ("group",)

PARAMS = {
    "binsize": {
        "type": float,
        "default": 0.5,
        "unit": "Å",
        "min": 0.01,
        "help": "直方图 bin 宽",
    },
    "dim": {
        "type": str,
        "default": "z",
        "choices": AXES,
        "help": "沿哪个轴统计",
    },
}

LABELS = {
    "zh": {
        "title": "线密度",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "mass": "质量密度 (g cm$^{-3}$)",
    },
    "en": {
        "title": "Linear density",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "mass": "mass density (g cm$^{-3}$)",
    },
}


COLUMN_LABELS = {
    "zh": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "mass_density_g_cm3": "质量密度 (g cm$^{-3}$)",
        "charge_density_e_A3": "电荷密度 (e Å$^{-3}$)",
    },
    "en": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "mass_density_g_cm3": "mass density (g cm$^{-3}$)",
        "charge_density_e_A3": "charge density (e Å$^{-3}$)",
    },
}


def _reject_outside(positions: np.ndarray, lengths: np.ndarray,
                    pbc: tuple[bool, ...], ctx) -> None:
    """非周期方向落在盒外时不能悄悄被直方图丢掉。"""
    for axis, periodic in enumerate(pbc):
        if periodic:
            continue
        values = positions[:, axis]
        if values.size and (values.min() < 0.0 or values.max() > lengths[axis]):
            ctx.warn(
                f"非周期方向 {AXES[axis]} 有原子落在盒外 "
                f"[{values.min():g}, {values.max():g}]，盒范围 [0, {lengths[axis]:g}]；"
                "这些原子不会进入直方图，结果仅供定性参考。"
            )


def _fixed_box_stop(ctx) -> tuple[int, int | None]:
    """返回 (有效 stop, 首次变盒的帧)。盒子变了就只用首帧。"""
    universe = ctx.universe
    universe.trajectory[ctx.start]
    reference = np.asarray(universe.dimensions[:3], dtype=float)
    for frame in range(ctx.start + 1, ctx.stop):
        universe.trajectory[frame]
        current = np.asarray(universe.dimensions[:3], dtype=float)
        if not np.allclose(current, reference, rtol=1e-6, atol=1e-6):
            universe.trajectory[ctx.start]
            return ctx.start + 1, frame
    universe.trajectory[ctx.start]
    return ctx.stop, None


COORDINATES = "in_box"

GEOMETRY = {"cell": "orthorhombic", "periodicity": "xy"}


def run(ctx) -> dict[str, pd.DataFrame]:
    binsize = float(ctx.params["binsize"])
    if binsize <= 0:
        raise ValidationError(f"binsize 必须为正数，收到 {binsize}")

    universe = ctx.universe
    if universe.dimensions is None:
        raise ValidationError("轨迹缺少盒信息，无法计算线密度")
    angles = np.asarray(universe.dimensions[3:], dtype=float)
    if not np.allclose(angles, 90.0, atol=1e-3):
        ctx.warn(
            f"检测到三斜盒角 {angles.tolist()}；当前实现按三个盒长计算，"
            "结果仅供定性参考，不能与正交盒结果比较。"
        )

    stop, changed = _fixed_box_stop(ctx)
    if changed is not None:
        ctx.warn(
            f"检测到盒子在变化（第 {changed} 帧与首帧不同）；线密度只使用第 "
            f"{ctx.start} 帧，其余帧忽略。需要多帧平均请选固定盒窗口。"
        )
    n_frames = stop - ctx.start
    if n_frames <= 0:
        raise ValidationError("帧窗口为空，无法计算线密度")

    universe.trajectory[ctx.start]
    lengths = np.asarray(universe.dimensions[:3], dtype=float)
    geometry = getattr(ctx, "geometry", None)
    pbc = geometry.pbc if geometry is not None else (True, True, True)
    bins = np.floor(lengths / binsize).astype(int)
    if int(bins.min()) < 1:
        raise ValidationError(
            f"binsize {binsize:g} Å 大于最短盒长 {float(lengths.min()):g} Å"
        )
    edges = {
        axis: np.linspace(0.0, lengths[i], bins[i] + 1)
        for i, axis in enumerate(AXES)
    }

    # 单位：质量 amu、电荷 e（MDAnalysis 原子属性）
    group = ctx.groups["group"].atoms
    masses = np.asarray(group.masses, dtype=float)
    charges = np.asarray(group.charges, dtype=float)
    mass_sum = {axis: np.zeros(bins[i]) for i, axis in enumerate(AXES)}
    charge_sum = {axis: np.zeros(bins[i]) for i, axis in enumerate(AXES)}

    for frame in range(ctx.start, stop):
        universe.trajectory[frame]
        positions = np.asarray(group.positions, dtype=float)
        # in_box 视图已只对周期方向折回；非周期方向保持实际坐标。
        _reject_outside(positions, lengths, pbc, ctx)
        for i, axis in enumerate(AXES):
            mass_hist, _ = np.histogram(
                positions[:, i], weights=masses, bins=edges[axis]
            )
            charge_hist, _ = np.histogram(
                positions[:, i], weights=charges, bins=edges[axis]
            )
            mass_sum[axis] += mass_hist
            charge_sum[axis] += charge_hist

    volume = float(np.prod(lengths))
    norm_factor = AVOGADRO * VOLUME_CONVERSION  # amu/Å³ → g/cm³
    tables: dict[str, pd.DataFrame] = {}
    for i, axis in enumerate(AXES):
        bin_volume = volume / bins[i]
        mass_density = mass_sum[axis] / n_frames / (norm_factor * bin_volume)
        charge_density = charge_sum[axis] / n_frames / bin_volume
        centers = 0.5 * (edges[axis][1:] + edges[axis][:-1])
        # 表里是盒坐标（0…L）；视图平移只在出图时施加
        tables[f"lineardensity_{axis}"] = pd.DataFrame(
            {
                f"{axis}_angstrom": centers,
                "mass_density_g_cm3": mass_density,
                "charge_density_e_A3": charge_density,
            }
        )
    return tables


def build_series(ctx, tables) -> list[Series]:
    """把原生表转成绘图 Series；一个逻辑量 mass density。"""
    axis = str(ctx.params["dim"]).lower()
    table = tables[f"lineardensity_{axis}"]
    shift = ctx.shift[AXES.index(axis)]
    curve = Curve(
        x=np.asarray(table[f"{axis}_angstrom"], dtype=float) + shift,
        y=np.asarray(table["mass_density_g_cm3"], dtype=float),
        label=ctx.label("mass"),
        unit="g cm^-3",
    )
    return [
        Series(
            name="mass_density_g_cm3",
            curves=[curve],
            label=ctx.label("mass"),
            unit="g cm^-3",
        )
    ]


def panel_request(ctx, tables) -> PanelRequest:
    axis = str(ctx.params["dim"]).lower()
    return PanelRequest(
        recipe="lineardensity",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label(f"axis_{axis}"),
        ylabel=ctx.label("mass"),
        options={"axis": axis, "legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    """插件自己的 Panel 模板；原生曲线和 compare 多曲线共用这一处。"""
    axis = str(request.options.get("axis") or ctx.params.get("dim") or "z").lower()

    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = bool(request.options.get("legend")) or len(curves) > 1
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
                    label=curve.label if show_legend else None,
                )
        if show_legend:
            chart.legend(ax)
        annotations.draw(ax, ctx, x_axis=axis)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name=request.recipe,
        draw=draw,
        title=request.title,
        xlabel=request.xlabel,
        ylabel=request.ylabel,
        aspect="auto",
        xlim=ctx.window(axis),
        panel_size=ctx.size("single"),
    )


def panels(ctx, tables) -> list[Panel]:
    request = panel_request(ctx, tables)
    return [render_panel(ctx, request)]


def figure_name(ctx, tables) -> str:
    axis = str(ctx.params["dim"]).lower()
    return f"lineardensity_{axis}"
