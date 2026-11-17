"""密度投影：三维数密度沿指定轴求和，投影到另外两轴。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")


SLOTS = ("group",)

PARAMS = {
    "delta": {
        "type": float,
        "default": 1.0,
        "unit": "Å",
        "min": 0.01,
        "help": "投影网格的边长；越小越细，代价按立方增长",
    },
    "sum_axis": {
        "type": str,
        "default": "y",
        "choices": AXES,
        "help": "沿哪个轴求和，投影到另外两个轴",
    },
}

LABELS = {
    "zh": {
        "title": "密度投影",
        "cbar": "数密度 (Å$^{-3}$)",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
    },
    "en": {
        "title": "Density projection",
        "cbar": "number density (Å$^{-3}$)",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
    },
}

COORDINATES = "in_box"


def _project_grid(
    counts, edges, sum_axis: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, int]]:
    """沿 sum_axis 求和，投影到另外两轴，返回 (轴1中心, 轴2中心, 数密度, 保留的轴号)。

    数密度 = Σ_k ρ / N_k，单位 Å⁻³，即沿求和方向的平均。
    """
    counts = np.asarray(counts, dtype=float)
    if counts.ndim != 3:
        raise ValueError(f"网格必须是三维，收到 shape={counts.shape}")

    axis = sum_axis.lower()
    if axis not in AXES:
        raise ValueError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")

    index = AXES.index(axis)
    centers = [0.5 * (np.asarray(e[1:]) + np.asarray(e[:-1])) for e in edges]

    keep = tuple(i for i in range(3) if i != index)
    summed = counts.sum(axis=index)
    # 沿求和方向求平均：除以该方向的格数，不是体积
    density = summed / counts.shape[index]

    return centers[keep[0]], centers[keep[1]], density, keep


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


GEOMETRY = {"cell": "orthorhombic", "periodicity": "xy"}


def run(ctx) -> dict[str, pd.DataFrame]:
    params = ctx.params
    sum_axis = str(params["sum_axis"]).lower()
    if sum_axis not in AXES:
        raise ValidationError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")
    delta = float(params["delta"])
    if delta <= 0:
        raise ValidationError(f"delta 必须为正数，收到 {delta}")

    universe = ctx.universe
    if universe.dimensions is None:
        raise ValidationError("轨迹缺少盒信息，无法做密度投影")
    angles = np.asarray(universe.dimensions[3:], dtype=float)
    if not np.allclose(angles, 90.0, atol=1e-3):
        ctx.warn(
            f"检测到三斜盒角 {angles.tolist()}；当前实现按三个盒长计算，"
            "结果仅供定性参考，不能与正交盒结果比较。"
        )

    stop, changed = _fixed_box_stop(ctx)
    if changed is not None:
        ctx.warn(
            f"检测到盒子在变化（第 {changed} 帧与首帧不同）；密度只使用第 "
            f"{ctx.start} 帧，其余帧忽略。需要多帧平均请选固定盒窗口。"
        )
    n_frames = stop - ctx.start
    if n_frames <= 0:
        raise ValidationError("帧窗口为空，无法计算密度")

    universe.trajectory[ctx.start]
    lengths = np.asarray(universe.dimensions[:3], dtype=float)
    geometry = getattr(ctx, "geometry", None)
    pbc = geometry.pbc if geometry is not None else (True, True, True)
    cells = np.ceil(lengths / delta).astype(int)
    edges = [np.arange(n + 1, dtype=float) * delta for n in cells]
    counts = np.zeros(tuple(cells), dtype=float)

    atoms = ctx.groups["group"].atoms
    for frame in range(ctx.start, stop):
        universe.trajectory[frame]
        positions = np.asarray(atoms.positions, dtype=float)
        # in_box 视图已只对周期方向折回；非周期方向不得再次 wrap。
        _reject_outside(positions, lengths, pbc, ctx)
        hist, _ = np.histogramdd(positions, bins=edges)
        counts += hist

    # 单位 Å⁻³：每个格子的计数 / 帧数 / 格体积
    grid = counts / (n_frames * delta**3)
    ctx.extras["density_extent"] = {
        axis: float(edges[i][-1]) for i, axis in enumerate(AXES)
    }

    # 表里是盒坐标（0…L）；视图平移只在出图时施加
    center_a, center_b, density, keep = _project_grid(grid, edges, sum_axis)
    a, b = AXES[keep[0]], AXES[keep[1]]

    # 平面场要摊平成 (坐标, 坐标, 值) 三列；density[i, j] 对应 (a_i, b_j)
    grid_a, grid_b = np.meshgrid(center_a, center_b, indexing="ij")
    table = pd.DataFrame(
        {
            f"{a}_angstrom": grid_a.ravel(),
            f"{b}_angstrom": grid_b.ravel(),
            "number_density_A3": density.ravel(),
        }
    )
    return {f"density_{a}{b}": table}


def meta(ctx, tables) -> dict:
    """记录网格范围，便于用 Σρ·Δa·Δb·L_axis 核验原子数守恒。"""
    sum_axis = str(ctx.params["sum_axis"]).lower()
    return {
        "sum_axis": sum_axis,
        "delta": float(ctx.params["delta"]),
        # DensityAnalysis 的网格按 delta 取整，覆盖范围略大于盒长，核验时用这一组
        "grid_extent": dict(ctx.extras.get("density_extent", {})),
    }


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    cols = list(table.columns)
    pivot = table.pivot(index=cols[1], columns=cols[0], values=cols[2])

    sum_axis = str(ctx.params["sum_axis"]).lower()
    keep = [axis for axis in AXES if axis != sum_axis]
    a, b = keep[0], keep[1]

    shift = ctx.shift
    shift_a, shift_b = shift[AXES.index(a)], shift[AXES.index(b)]

    fig, ax = chart.figure(ctx.size("map"))
    mesh = chart.heatmap(
        ax,
        pivot.columns.to_numpy() + shift_a,
        pivot.index.to_numpy() + shift_b,
        pivot.to_numpy(),
        shading="auto",
        cmap=chart.density_cmap(),
    )

    x_range = plotutil.clip_window(ctx.window(a), plotutil.data_range(ax, "x"))
    y_range = plotutil.clip_window(ctx.window(b), plotutil.data_range(ax, "y"))
    # 画布高度按数据纵横比取，等比例坐标轴才不会在画布里留下大片空白
    if not getattr(ctx, "size_is_explicit", False):
        width = ctx.size("map")[0]
        height = width * (y_range[1] - y_range[0]) / (x_range[1] - x_range[0]) + 0.9
        fig.set_size_inches(width, max(height, 1.6))
    ax.set_xlim(x_range)
    ax.set_ylim(y_range)
    ax.set_aspect("equal")
    ax.set_xlabel(ctx.label(f"axis_{a}"))
    ax.set_ylabel(ctx.label(f"axis_{b}"))
    ax.set_title(ctx.label("title"))
    chart.colorbar(fig, ax, mesh, ctx.label("cbar"))
    annotations.draw(ax, ctx, x_axis=a)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]
