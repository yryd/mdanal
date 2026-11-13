"""线密度：沿单轴的质量密度与电荷密度。

逐帧直方图自己累加，不用 MDAnalysis 的 LinearDensity：后者把盒尺寸在构造时抓成
一个"活视图"，遇到多段合并（ChainReader）或内存读取（MemoryReader）时视图不再
随帧更新，同一份数据会因读取方式不同而给出不同结果。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.units import constants

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError

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

COMPARE = {
    "table": "lineardensity_{dim}",
    "x": "{axis}_angstrom",
    "y": ["mass_density_g_cm3"],
    "box_axis": True,
}


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


def run(ctx) -> dict[str, pd.DataFrame]:
    binsize = float(ctx.params["binsize"])
    if binsize <= 0:
        raise ValidationError(f"binsize 必须为正数，收到 {binsize}")

    universe = ctx.universe
    if universe.dimensions is None:
        raise ValidationError("轨迹缺少盒信息，无法计算线密度")
    angles = np.asarray(universe.dimensions[3:], dtype=float)
    if not np.allclose(angles, 90.0, atol=1e-3):
        raise ValidationError(
            f"只支持正交盒子；检测到盒角 {angles.tolist()}（三斜盒未支持）"
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
        # 原始轨迹可能是未包裹坐标；按盒长折回后再计入直方图
        wrapped = positions - np.floor(positions / lengths) * lengths
        for i, axis in enumerate(AXES):
            mass_hist, _ = np.histogram(
                wrapped[:, i], weights=masses, bins=edges[axis]
            )
            charge_hist, _ = np.histogram(
                wrapped[:, i], weights=charges, bins=edges[axis]
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


def figures(ctx, tables):
    axis = str(ctx.params["dim"]).lower()
    name = f"lineardensity_{axis}"
    table = tables[name]
    cols = list(table.columns)

    shift = ctx.system.view.shift[AXES.index(axis)]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, np.asarray(table[cols[0]]) + shift, table[cols[1]], lw=1.2)
    ax.set_xlabel(ctx.label(f"axis_{axis}"))
    ax.set_ylabel(ctx.label("mass"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(axis))
    annotations.draw(ax, ctx, axes={"x": axis})
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]
