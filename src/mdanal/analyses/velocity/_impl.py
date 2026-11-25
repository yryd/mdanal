"""流速剖面：按原盒坐标逐帧分箱，速度取实验室系。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...plot import annotations, chart, plotutil
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series
from ...errors import ValidationError

AXES = ("x", "y", "z")


SLOTS = ("group", "ref")

PARAMS = {
    "dim": {
        "type": (str, int),
        "default": "z",
        "choices": AXES + (0, 1, 2),
        "help": "剖面的法向轴：名称 x/y/z 或序号 0/1/2",
    },
    "vdim": {
        "type": (str, int),
        "default": "x",
        "choices": AXES + (0, 1, 2),
        "help": "速度分量：名称 x/y/z 或序号 0/1/2",
    },
    "bin_width": {
        "type": float,
        "default": 1.0,
        "unit": "Å",
        "min": 0.01,
        "help": "剖面 bin 宽",
    },
    "grouping": {
        "type": str,
        "default": "molecules",
        "choices": ("atoms", "residues", "segments", "molecules"),
        "help": "按什么分组统计速度",
    },
    "sym": {
        "type": bool,
        "default": False,
        "help": "是否对剖面做对称化",
    },
}

LABELS = {
    "zh": {
        "title": "流速剖面",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "v_x": "$v_x$ (Å ps$^{-1}$)",
        "v_y": "$v_y$ (Å ps$^{-1}$)",
        "v_z": "$v_z$ (Å ps$^{-1}$)",
    },
    "en": {
        "title": "Velocity profile",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "v_x": "$v_x$ (Å ps$^{-1}$)",
        "v_y": "$v_y$ (Å ps$^{-1}$)",
        "v_z": "$v_z$ (Å ps$^{-1}$)",
    },
}

COLUMN_LABELS = {
    "zh": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "vx_A_per_ps": "$v_x$ (Å ps$^{-1}$)",
        "vy_A_per_ps": "$v_y$ (Å ps$^{-1}$)",
        "vz_A_per_ps": "$v_z$ (Å ps$^{-1}$)",
    },
    "en": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "vx_A_per_ps": "$v_x$ (Å ps$^{-1}$)",
        "vy_A_per_ps": "$v_y$ (Å ps$^{-1}$)",
        "vz_A_per_ps": "$v_z$ (Å ps$^{-1}$)",
    },
}


def _unit_layout(atoms, grouping: str) -> tuple[np.ndarray, np.ndarray]:
    """把原子映射到统计单元（原子/残基/分子/段），返回单元编号与首原子。"""
    if grouping == "atoms":
        index = np.arange(atoms.n_atoms, dtype=int)
    else:
        attribute = {
            "molecules": "molnums",
            "residues": "resids",
            "segments": "segids",
        }.get(grouping)
        if attribute is None:
            raise ValidationError(f"未知的 grouping {grouping!r}")
        if not hasattr(atoms, attribute):
            raise ValidationError(f"轨迹缺少 {attribute}，无法按 {grouping} 分组")
        _, index = np.unique(getattr(atoms, attribute), return_inverse=True)
    _, first = np.unique(index, return_index=True)
    return index, first


def _unit_vectors(
    positions: np.ndarray,
    velocities: np.ndarray,
    masses: np.ndarray,
    index: np.ndarray,
    first: np.ndarray,
    unit_mass: np.ndarray,
    lengths: np.ndarray,
    pbc: tuple[bool, bool, bool],
) -> tuple[np.ndarray, np.ndarray]:
    """单元的质心位置与质心速度；只在周期方向做最小镜像。"""
    anchor_per_atom = positions[first][index]
    delta = positions - anchor_per_atom
    for axis, periodic in enumerate(pbc):
        if periodic:
            delta[:, axis] -= np.round(delta[:, axis] / lengths[axis]) * lengths[axis]
    anchor = positions[first]
    com = np.column_stack(
        [
            anchor[:, axis]
            + np.bincount(
                index, weights=masses * delta[:, axis], minlength=len(unit_mass)
            )
            / unit_mass
            for axis in range(3)
        ]
    )
    velocity = np.column_stack(
        [
            np.bincount(
                index, weights=masses * velocities[:, axis], minlength=len(unit_mass)
            )
            / unit_mass
            for axis in range(3)
        ]
    )
    return com, velocity


COORDINATES = "in_box"

KERNEL_PBC = "reference_frame"
GEOMETRY = {"cell": "orthorhombic", "periodicity": "xy"}


def run(ctx) -> dict[str, pd.DataFrame]:
    dim, vdim, axis = _axes(ctx)
    grouping = str(ctx.params["grouping"])
    bin_width = float(ctx.params["bin_width"])
    if bin_width <= 0:
        raise ValidationError(f"bin_width 必须为正数，收到 {bin_width}")

    universe = ctx.universe
    geometry = getattr(ctx, "geometry", None)
    pbc = geometry.pbc if geometry is not None else (True, True, True)
    atoms = ctx.groups["group"].atoms
    ref = ctx.groups["ref"].atoms
    if not universe.trajectory.ts.has_velocities:
        raise ValidationError("轨迹不含速度列，无法计算流速剖面")
    dimensions = universe.dimensions
    if dimensions is not None and not np.allclose(np.asarray(dimensions[3:]), 90.0, atol=1e-3):
        ctx.warn(
            f"检测到三斜盒角 {np.asarray(dimensions[3:]).tolist()}；"
            "当前按三个盒长做分子复原/分箱，结果仅供定性参考。"
        )

    index, first = _unit_layout(atoms, grouping)
    if len(first) == 0:
        raise ValidationError("统计分组为空，无法计算流速剖面")
    masses = np.asarray(atoms.masses, dtype=float)
    if masses.size != atoms.n_atoms:
        masses = np.ones(atoms.n_atoms, dtype=float)
    unit_mass = np.bincount(index, weights=masses, minlength=len(first))
    if np.any(unit_mass <= 0):
        raise ValidationError("存在总质量为 0 的统计单元，无法计算质心速度")

    universe.trajectory[ctx.start]
    lengths_ref = np.asarray(universe.dimensions[:3], dtype=float)
    if bin_width >= lengths_ref[dim]:
        raise ValidationError(
            f"bin_width {bin_width:g} Å 不小于盒长 {lengths_ref[dim]:g} Å"
        )
    n_bins = max(1, int(np.floor(lengths_ref[dim] / bin_width)))
    bin_width_ref = float(lengths_ref[dim] / n_bins)

    universe.trajectory[ctx.selection_frame]
    ctx.extras["velocity_ref"] = float(
        np.average(
            np.asarray(ref.positions, dtype=float),
            weights=np.asarray(ref.masses, dtype=float),
            axis=0,
        )[dim]
    )

    sums = np.zeros(n_bins, dtype=float)
    sums_sq = np.zeros(n_bins, dtype=float)
    counts = np.zeros(n_bins, dtype=int)
    box_changed = False

    for frame in range(ctx.start, ctx.stop):
        universe.trajectory[frame]
        lengths = np.asarray(universe.dimensions[:3], dtype=float)
        if abs(lengths[dim] - lengths_ref[dim]) > 1e-6:
            box_changed = True
        positions = np.asarray(atoms.positions, dtype=float)
        velocities = np.asarray(atoms.velocities, dtype=float)
        com, unit_velocity = _unit_vectors(
            positions, velocities, masses, index, first, unit_mass, lengths, pbc
        )

        # 速度剖面是实验室系速度；参考组只用于记录位置，不参与速度相减
        relative = unit_velocity[:, vdim]

        wrapped = com.copy()
        for axis_index, periodic in enumerate(pbc):
            if periodic:
                wrapped[:, axis_index] -= (
                    np.floor(com[:, axis_index] / lengths[axis_index])
                    * lengths[axis_index]
                )
        # 周期方向统一到首帧参考盒；非周期方向保留实际坐标，不缩放/不折回。
        if pbc[dim]:
            coordinate = wrapped[:, dim] / lengths[dim] * lengths_ref[dim]
        else:
            coordinate = wrapped[:, dim]
            if np.any(coordinate < 0.0) or np.any(coordinate > lengths_ref[dim]):
                ctx.warn(
                    f"非周期方向 {axis} 有统计单元落在参考盒 "
                    f"[0, {lengths_ref[dim]:g}] 之外；这些单元会被边界 bin 截断，"
                    "结果仅供定性参考。"
                )
        bins = np.clip((coordinate / bin_width_ref).astype(int), 0, n_bins - 1)
        sums += np.bincount(bins, weights=relative, minlength=n_bins)
        sums_sq += np.bincount(bins, weights=relative * relative, minlength=n_bins)
        counts += np.bincount(bins, minlength=n_bins)

    if box_changed:
        ctx.warn(
            "检测到盒子在变化；速度剖面在首帧参考盒坐标中平均，"
            "跨帧比较时需注意。"
        )

    with np.errstate(invalid="ignore", divide="ignore"):
        profile = sums / counts
        variance = (sums_sq - counts * profile**2) / (counts - 1)
        error = np.sqrt(np.maximum(variance, 0.0) / counts)
    error[counts < 2] = np.nan

    if bool(ctx.params["sym"]):
        profile = 0.5 * (profile + profile[::-1])
        error = 0.5 * (error + error[::-1])

    centers = (np.arange(n_bins, dtype=float) + 0.5) * bin_width_ref
    table = pd.DataFrame(
        {
            f"{axis}_angstrom": centers,
            f"v{AXES[vdim]}_A_per_ps": profile,
            "error_A_per_ps": error,
        }
    )
    ctx.extras["velocity_bins"] = n_bins
    ctx.extras["velocity_box_ref"] = float(lengths_ref[dim])
    return {"velocity": table}


def meta(ctx, tables) -> dict:
    return {
        "axis": _axes(ctx)[2],
        "ref_com": ctx.extras.get("velocity_ref"),
        "ref_frame": ctx.selection_frame,
        "coordinate_frame": "box",
        "box_length_ref": ctx.extras.get("velocity_box_ref"),
        "n_bins": ctx.extras.get("velocity_bins"),
        "averaging": "pooled_unit_samples",
        "error_method": "naive_sample_sem_without_time_correlation_correction",
        "reference_role": "metadata_only",
        "sym": bool(ctx.params["sym"]),
    }


def build_series(ctx, tables) -> list[Series]:
    table = tables["velocity"]
    dim, vdim, axis = _axes(ctx)
    coordinate = table[f"{axis}_angstrom"].to_numpy(dtype=float)
    velocity = table[f"v{AXES[vdim]}_A_per_ps"].to_numpy(dtype=float)
    curve = Curve(
        x=coordinate + ctx.shift[dim],
        y=velocity,
        label=ctx.label(f"v_{AXES[vdim]}"),
    )
    return [
        Series(
            name=f"v{AXES[vdim]}_A_per_ps",
            curves=[curve],
            label=ctx.label(f"v_{AXES[vdim]}"),
        )
    ]


def panel_request(ctx, tables) -> PanelRequest:
    dim, vdim, axis = _axes(ctx)
    return PanelRequest(
        recipe="velocity",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label(f"axis_{axis}"),
        ylabel=ctx.label(f"v_{AXES[vdim]}"),
        options={"axis": axis, "legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    axis = str(request.options.get("axis") or _axes(ctx)[2]).lower()

    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = len(curves) > 1
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
            chart.legend(ax, loc=plotutil.legend_loc(ctx))
        annotations.draw(ax, ctx, x_axis=axis)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="velocity",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label(f"axis_{axis}"),
        ylabel=request.ylabel or ctx.label("title"),
        aspect="auto",
        xlim=ctx.window(axis),
        panel_size=ctx.size("single"),
    )


def panels(ctx, tables) -> list[Panel]:
    request = panel_request(ctx, tables)
    return [render_panel(ctx, request)]



def _axes(ctx) -> tuple[int, int, str]:
    dim = _axis_index(ctx.params["dim"], "dim")
    vdim = _axis_index(ctx.params["vdim"], "vdim")
    return dim, vdim, AXES[dim]


def _axis_index(value, key: str) -> int:
    """轴名（x/y/z）或序号（0/1/2）转成轴序号。"""
    if isinstance(value, str):
        name = value.strip().lower()
        if name in AXES:
            return AXES.index(name)
    elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2:
        return int(value)
    raise ValidationError(f"{key} 只能是 x、y、z 或 0、1、2，收到 {value!r}")
