"""密度投影：三维数密度沿指定轴求和，投影到另外两轴。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, is_color_like

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")
DIRECTIONS = {"xy": "z", "xz": "y", "yz": "x"}
DEFAULT_COLORS = ("#ffffff", "#c05040", "#4165c0")


SLOTS = ("group",)

PARAMS = {
    "delta": {
        "type": float,
        "default": 1.0,
        "unit": "Å",
        "min": 0.01,
        "help": "投影网格的目标边长；越小越细，代价按立方增长",
    },
    "sum_axis": {
        "type": str,
        "default": "y",
        "choices": AXES,
        "help": "单个投影时沿哪个轴求和；设置 directions 后忽略",
    },
    "directions": {
        "type": list,
        "default": [],
        "help": "多面板方向，如 [xy, xz, yz]；为空时只画 sum_axis 一张",
    },
    "cmap": {
        "type": str,
        "default": "mdanal",
        "help": "Matplotlib colormap 名称；mdanal 表示默认白→砖红→蓝色标",
    },
    "colors": {
        "type": list,
        "default": [],
        "help": "自定义连续色标颜色列表（至少 2 个）；非空时覆盖 cmap",
    },
    "vmin": {
        "type": (float, str),
        "default": "auto",
        "help": "色标下限；auto 表示按数据，或写数值",
    },
    "vmax": {
        "type": (float, str),
        "default": "auto",
        "help": "色标上限；auto 表示按数据，或写数值",
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


def _parse_directions(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("directions 必须是列表，如 [xy, xz, yz]")
    directions: list[str] = []
    for entry in value:
        name = str(entry).lower().strip()
        if name not in DIRECTIONS:
            raise ValidationError(
                f"directions 只能取 {list(DIRECTIONS)}，收到 {entry!r}"
            )
        if name in directions:
            raise ValidationError(f"directions 不能重复：{name}")
        directions.append(name)
    return directions


def _optional_number(value, name: str) -> float | None:
    if value is None or (isinstance(value, str) and value.strip().lower() == "auto"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} 只能是 auto 或数值，收到 {value!r}") from exc
    if not np.isfinite(result):
        raise ValidationError(f"{name} 必须是有限数值，收到 {value!r}")
    return result


def _explicit_colors(ctx) -> list[str]:
    return list(ctx.params.get("colors") or [])


def _color_map(ctx):
    colors = _explicit_colors(ctx)
    name = str(ctx.params.get("cmap") or "mdanal")
    if not colors and name.lower() in ("mdanal", "default"):
        colors = list(DEFAULT_COLORS)

    if colors:
        bad = [color for color in colors if not is_color_like(color)]
        if bad:
            raise ValidationError(f"colors 含无效颜色：{bad}")
        if len(colors) < 2:
            raise ValidationError("colors 自定义连续色标至少需要 2 个颜色")
        return LinearSegmentedColormap.from_list("mdanal_density_default", colors)

    if name.lower() in ("mdanal", "default"):
        return chart.density_cmap()
    try:
        return colormaps[name]
    except KeyError as exc:
        raise ValidationError(f"未知 colormap：{name!r}") from exc


def _table_for_direction(grid, edges, direction: str) -> tuple[str, pd.DataFrame, str, str]:
    sum_axis = DIRECTIONS[direction]
    center_a, center_b, density, keep = _project_grid(grid, edges, sum_axis)
    a, b = AXES[keep[0]], AXES[keep[1]]
    grid_a, grid_b = np.meshgrid(center_a, center_b, indexing="ij")
    table = pd.DataFrame(
        {
            f"{a}_angstrom": grid_a.ravel(),
            f"{b}_angstrom": grid_b.ravel(),
            "number_density_A3": density.ravel(),
        }
    )
    return f"density_{a}{b}", table, a, b


def _single_table(grid, edges, sum_axis: str) -> tuple[str, pd.DataFrame, str, str]:
    center_a, center_b, density, keep = _project_grid(grid, edges, sum_axis)
    a, b = AXES[keep[0]], AXES[keep[1]]
    grid_a, grid_b = np.meshgrid(center_a, center_b, indexing="ij")
    table = pd.DataFrame(
        {
            f"{a}_angstrom": grid_a.ravel(),
            f"{b}_angstrom": grid_b.ravel(),
            "number_density_A3": density.ravel(),
        }
    )
    return f"density_{a}{b}", table, a, b


GEOMETRY = {"cell": "orthorhombic", "periodicity": "xy"}


def run(ctx) -> dict[str, pd.DataFrame]:
    params = ctx.params
    sum_axis = str(params["sum_axis"]).lower()
    if sum_axis not in AXES:
        raise ValidationError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")
    directions = _parse_directions(params.get("directions"))
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
    # 用精确铺满盒子的等宽格；delta 是目标分辨率，实际格宽可能略不同。
    # 这样投影平均的分母是真实盒长，而不是 ceil(L/delta)*delta 的扩展长度。
    cells = np.maximum(1, np.ceil(lengths / delta).astype(int))
    widths = lengths / cells
    edges = [np.linspace(0.0, lengths[i], int(cells[i]) + 1) for i in range(3)]
    counts = np.zeros(tuple(int(value) for value in cells), dtype=float)

    atoms = ctx.groups["group"].atoms
    for frame in range(ctx.start, stop):
        universe.trajectory[frame]
        positions = np.asarray(atoms.positions, dtype=float)
        # in_box 视图已只对周期方向折回；非周期方向不得再次 wrap。
        _reject_outside(positions, lengths, pbc, ctx)
        hist, _ = np.histogramdd(positions, bins=edges)
        counts += hist

    # 单位 Å⁻³：每个格子的计数 / 帧数 / 实际格体积
    cell_volume = float(np.prod(widths))
    grid = counts / (n_frames * cell_volume)
    ctx.extras["density_extent"] = {
        axis: float(edges[i][-1]) for i, axis in enumerate(AXES)
    }
    ctx.extras["density_widths"] = {
        axis: float(widths[i]) for i, axis in enumerate(AXES)
    }
    ctx.extras["density_directions"] = list(directions)

    tables: dict[str, pd.DataFrame] = {}
    if directions:
        for direction in directions:
            name, table, _, _ = _table_for_direction(grid, edges, direction)
            tables[name] = table
    else:
        name, table, _, _ = _single_table(grid, edges, sum_axis)
        tables[name] = table
    return tables


def meta(ctx, tables) -> dict:
    """记录网格、方向与色标设置；meta 只放 JSON 可表示值。"""
    sum_axis = str(ctx.params["sum_axis"]).lower()
    directions = _parse_directions(ctx.params.get("directions"))
    return {
        "sum_axis": sum_axis,
        "directions": directions,
        "delta": float(ctx.params["delta"]),
        "cmap": str(ctx.params.get("cmap") or "mdanal"),
        "colors": (
            _explicit_colors(ctx)
            or (
                list(DEFAULT_COLORS)
                if str(ctx.params.get("cmap") or "mdanal").lower()
                in ("mdanal", "default")
                else []
            )
        ),
        "vmin": ctx.params.get("vmin", "auto"),
        "vmax": ctx.params.get("vmax", "auto"),
        "grid_widths": dict(ctx.extras.get("density_widths", {})),
        # 精确铺满盒子的网格；extent 等于真实盒长
        "grid_extent": dict(ctx.extras.get("density_extent", {})),
    }


def _panel_data(ctx, table, x_axis: str, y_axis: str):
    cols = list(table.columns)
    pivot = table.pivot(index=cols[1], columns=cols[0], values=cols[2])
    shift = ctx.shift
    shift_x = shift[AXES.index(x_axis)]
    shift_y = shift[AXES.index(y_axis)]
    x = pivot.columns.to_numpy() + shift_x
    y = pivot.index.to_numpy() + shift_y
    return x, y, pivot.to_numpy()


def _figure_size(ctx, n_panels: int, aspect: float) -> tuple[float, float]:
    base_w, base_h = ctx.size("map")
    if n_panels <= 1:
        if getattr(ctx, "size_is_explicit", False):
            return base_w, base_h
        return base_w, max(base_w * aspect + 0.9, 1.6)
    if getattr(ctx, "size_is_explicit", False):
        return base_w, base_h
    # 多面板时每个面板保持 map 的宽度；高度按最高面板的纵横比取。
    width = base_w * n_panels + 0.5 * (n_panels - 1)
    height = max(base_h, base_w * aspect + 0.9)
    return width, height


def figures(ctx, tables):
    directions = _parse_directions(ctx.params.get("directions"))
    items = list(tables.items())
    if not items:
        return []

    panels = []
    for name, table in items:
        cols = list(table.columns)
        a = str(cols[0]).split("_", 1)[0]
        b = str(cols[1]).split("_", 1)[0]
        direction = f"{a}{b}" if f"{a}{b}" in DIRECTIONS else None
        x, y, values = _panel_data(ctx, table, a, b)
        panels.append((name, direction, a, b, x, y, values))

    # 统一色标：多面板用全部数据的全局范围；vmin/vmax 显式值优先。
    all_values = np.concatenate([panel[6].ravel() for panel in panels])
    vmin_param = _optional_number(ctx.params.get("vmin"), "vmin")
    vmax_param = _optional_number(ctx.params.get("vmax"), "vmax")
    vmin = float(np.nanmin(all_values)) if vmin_param is None else vmin_param
    vmax = float(np.nanmax(all_values)) if vmax_param is None else vmax_param
    if vmin_param is not None and vmax_param is not None and vmax <= vmin:
        raise ValidationError(f"vmax（{vmax:g}）必须大于 vmin（{vmin:g}）")
    if vmax <= vmin:
        vmax = vmin + 1e-12
    cmap = _color_map(ctx)

    # 估算最高的面板纵横比，用来定单图/多图高度。
    aspect = 1.0
    for _, _, a, b, x, y, _ in panels:
        x_range = plotutil.clip_window(ctx.window(a), (float(x.min()), float(x.max())))
        y_range = plotutil.clip_window(ctx.window(b), (float(y.min()), float(y.max())))
        if x_range[1] > x_range[0]:
            aspect = max(aspect, (y_range[1] - y_range[0]) / (x_range[1] - x_range[0]))
    width, height = _figure_size(ctx, len(panels), aspect)

    chart.apply_style()
    if len(panels) == 1:
        fig, axes = plt.subplots(figsize=(width, height))
        axes_list = [axes]
    else:
        fig, axes_array = plt.subplots(1, len(panels), figsize=(width, height))
        axes_list = list(np.atleast_1d(axes_array))

    meshes = []
    for ax, (_, direction, a, b, x, y, values) in zip(axes_list, panels):
        mesh = ax.pcolormesh(
            x, y, values,
            shading="auto",
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
        )
        meshes.append(mesh)
        x_range = plotutil.clip_window(ctx.window(a), (float(x.min()), float(x.max())))
        y_range = plotutil.clip_window(ctx.window(b), (float(y.min()), float(y.max())))
        ax.set_xlim(x_range)
        ax.set_ylim(y_range)
        ax.set_aspect("equal")
        ax.set_xlabel(ctx.label(f"axis_{a}"))
        ax.set_ylabel(ctx.label(f"axis_{b}"))
        title = ctx.label("title")
        if direction is not None and len(panels) > 1:
            title = f"{title} ({direction})"
        ax.set_title(title)
        annotations.draw(ax, ctx, x_axis=a)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())

    # 每个面板各有一条色标，色标高度严格等于该面板纵轴的实际高度。
    # 面板纵横比不同（非立方盒）时，不能共用一条整图高度的色标。
    fig.subplots_adjust(
        left=0.05,
        right=0.94,
        bottom=0.13,
        top=0.90,
        wspace=0.55 if len(panels) > 1 else 0.0,
    )
    fig.canvas.draw()
    for index, (ax, mesh) in enumerate(zip(axes_list, meshes)):
        position = ax.get_position()
        cax = fig.add_axes(
            [position.x1 + 0.014, position.y0, 0.012, position.height]
        )
        bar = fig.colorbar(mesh, cax=cax)
        if index == len(panels) - 1:
            bar.set_label(ctx.label("cbar"))
    name = "density" if len(panels) > 1 else items[0][0]
    return [(name, fig)]
