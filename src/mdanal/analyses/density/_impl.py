"""密度投影：三维数密度沿指定轴求和，投影到另外两轴。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.colors import LinearSegmentedColormap, is_color_like

from ...plot import annotations, chart, plotutil
from ...plot.panels import Panel
from ...plot.specs import Field, PanelRequest, Series
from ...errors import ValidationError

AXES = ("x", "y", "z")
DIRECTIONS = {"xy": "z", "xz": "y", "yz": "x"}
DIRECTION_FOR_AXIS = {axis: direction for direction, axis in DIRECTIONS.items()}
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
        "help": "单个投影时沿哪个轴求和；设置 directions/panels 后作为默认方向",
    },
    "directions": {
        "type": list,
        "default": [],
        "help": "同一窗口内的方向列表，如 [xy, xz, yz]；为空时用 sum_axis",
    },
    "panels": {
        "type": list,
        "default": [],
        "help": "任意单图列表；每项 {section, directions, label}，每个方向生成一个 panel",
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
    """沿 sum_axis 求和，投影到另外两轴，返回 (轴1中心, 轴2中心, 数密度, 保留的轴号)。"""
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
    return centers[keep[0]], centers[keep[1]], summed / counts.shape[index], keep


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


def _fixed_box_stop(universe, start: int, stop: int) -> tuple[int, int | None]:
    """返回 (有效 stop, 首次变盒帧)；盒子变了就只用首帧。"""
    universe.trajectory[start]
    reference = np.asarray(universe.dimensions[:3], dtype=float)
    for frame in range(start + 1, stop):
        universe.trajectory[frame]
        current = np.asarray(universe.dimensions[:3], dtype=float)
        if not np.allclose(current, reference, rtol=1e-6, atol=1e-6):
            universe.trajectory[start]
            return start + 1, frame
    universe.trajectory[start]
    return stop, None


def _parse_directions(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("directions 必须是列表，如 [xy, xz, yz]")
    directions: list[str] = []
    for entry in value:
        name = str(entry).lower().strip()
        if name not in DIRECTIONS:
            raise ValidationError(f"directions 只能取 {list(DIRECTIONS)}，收到 {entry!r}")
        if name in directions:
            raise ValidationError(f"directions 不能重复：{name}")
        directions.append(name)
    return directions


def _direction_for_sum_axis(sum_axis: str) -> str:
    return DIRECTION_FOR_AXIS[sum_axis]


def _parse_panels(value, system_start: int, system_stop: int) -> list[dict]:
    """把 panels 解析成“窗口偏移 + 方向列表”；section 与顶层 section 同口径。"""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValidationError("panels 必须是列表")
    specs: list[dict] = []
    for index, item in enumerate(value):
        where = f"panels[{index}]"
        if not isinstance(item, Mapping):
            raise ValidationError(f"{where} 必须是映射", where=where)
        unknown = set(item) - {"section", "directions", "label"}
        if unknown:
            raise ValidationError(f"未知字段 {sorted(unknown)}", where=where)
        section = item.get("section")
        if section is None:
            start, stop = 0, system_stop - system_start
        else:
            if not isinstance(section, (list, tuple)) or len(section) != 2:
                raise ValidationError("section 必须是 [start, stop)", where=where)
            if any(isinstance(part, bool) or not isinstance(part, int) for part in section):
                raise ValidationError("section 必须是整数帧号", where=where)
            start, stop = int(section[0]), int(section[1])
        if start < 0 or stop <= start or stop > system_stop - system_start:
            raise ValidationError(
                f"section [{start}, {stop}) 超出体系窗口 "
                f"[0, {system_stop - system_start})",
                where=where,
            )
        directions = _parse_directions(item.get("directions"))
        label = item.get("label")
        if label is not None and not isinstance(label, str):
            raise ValidationError("label 必须是字符串", where=where)
        specs.append(
            {
                "start": system_start + start,
                "stop": system_start + stop,
                "directions": directions,
                "label": label,
            }
        )
    return specs


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


def _make_table(grid, edges, direction: str):
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


def _grid_for_window(ctx, start: int, stop: int, delta: float) -> dict:
    universe = ctx.universe
    universe.trajectory[start]
    if universe.dimensions is None:
        raise ValidationError("轨迹缺少盒信息，无法做密度投影")
    angles = np.asarray(universe.dimensions[3:], dtype=float)
    if not np.allclose(angles, 90.0, atol=1e-3):
        ctx.warn(
            f"检测到三斜盒角 {angles.tolist()}；当前实现按三个盒长计算，"
            "结果仅供定性参考，不能与正交盒结果比较。"
        )

    effective_stop, changed = _fixed_box_stop(universe, start, stop)
    if changed is not None:
        ctx.warn(
            f"检测到盒子在变化（第 {changed} 帧与首帧不同）；密度只使用第 "
            f"{start} 帧，其余帧忽略。需要多帧平均请选固定盒窗口。"
        )
    n_frames = effective_stop - start
    if n_frames <= 0:
        raise ValidationError("帧窗口为空，无法计算密度")

    universe.trajectory[start]
    lengths = np.asarray(universe.dimensions[:3], dtype=float)
    track = getattr(getattr(ctx, "system", None), "geometry", None)
    geometry = track.frame(start) if track is not None else getattr(ctx, "geometry", None)
    pbc = geometry.pbc if geometry is not None else (True, True, True)
    cells = np.maximum(1, np.ceil(lengths / delta).astype(int))
    widths = lengths / cells
    edges = [np.linspace(0.0, lengths[i], int(cells[i]) + 1) for i in range(3)]
    counts = np.zeros(tuple(int(value) for value in cells), dtype=float)

    atoms = ctx.groups["group"].atoms
    for frame in range(start, effective_stop):
        universe.trajectory[frame]
        positions = np.asarray(atoms.positions, dtype=float)
        _reject_outside(positions, lengths, pbc, ctx)
        hist, _ = np.histogramdd(positions, bins=edges)
        counts += hist

    cell_volume = float(np.prod(widths))
    grid = counts / (n_frames * cell_volume)
    return {
        "start": start,
        "stop": effective_stop,
        "grid": grid,
        "edges": edges,
        "widths": widths,
        "lengths": lengths,
    }


def _panel_label(ctx, info: dict, n_frames: int, n_directions: int) -> str:
    explicit = info.get("label")
    if explicit:
        return str(explicit)
    title = ctx.label("title")
    direction = info.get("direction")
    if n_frames:
        if n_directions > 1:
            return f"Frame {info['start']} · {direction}"
        return f"Frame {info['start']}"
    if n_directions > 1:
        return f"{title} ({direction})"
    return title


GEOMETRY = {"cell": "orthorhombic", "periodicity": "xy"}


def run(ctx) -> dict[str, pd.DataFrame]:
    params = ctx.params
    sum_axis = str(params["sum_axis"]).lower()
    if sum_axis not in AXES:
        raise ValidationError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")
    top_directions = _parse_directions(params.get("directions"))
    delta = float(params["delta"])
    if delta <= 0:
        raise ValidationError(f"delta 必须为正数，收到 {delta}")

    system_window = getattr(getattr(ctx, "system", None), "frames", None)
    system_start, system_stop = system_window or (ctx.start, ctx.stop)
    specs = _parse_panels(params.get("panels"), system_start, system_stop)
    if specs and getattr(ctx, "plan_item", None) is not None and ctx.plan_item.section:
        raise ValidationError("panels 与顶层 section 不能同时使用；请把 section 写进每个 panel")

    jobs: list[dict] = []
    if specs:
        for spec in specs:
            directions = spec["directions"] or top_directions or [
                _direction_for_sum_axis(sum_axis)
            ]
            for direction in directions:
                jobs.append(
                    {
                        "start": spec["start"],
                        "stop": spec["stop"],
                        "direction": direction,
                        "label": spec["label"],
                    }
                )
    else:
        for direction in top_directions or [_direction_for_sum_axis(sum_axis)]:
            jobs.append(
                {
                    "start": ctx.start,
                    "stop": ctx.stop,
                    "direction": direction,
                    "label": None,
                }
            )

    grid_cache: dict[tuple[int, int], dict] = {}
    base_names: list[str] = []
    for job in jobs:
        key = (job["start"], job["stop"])
        if key not in grid_cache:
            grid_cache[key] = _grid_for_window(ctx, *key, delta)
        name, _, _, _ = _make_table(
            grid_cache[key]["grid"], grid_cache[key]["edges"], job["direction"]
        )
        base_names.append(name)

    counts = Counter(base_names)
    used: set[str] = set()
    tables: dict[str, pd.DataFrame] = {}
    panel_info: list[dict] = []
    for job, base in zip(jobs, base_names):
        data = grid_cache[(job["start"], job["stop"])]
        name, table, a, b = _make_table(data["grid"], data["edges"], job["direction"])
        if counts[base] > 1:
            name = f"{base}_f{job['start']}"
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        tables[name] = table
        panel_info.append(
            {
                "table": name,
                "start": job["start"],
                "stop": data["stop"],
                "direction": job["direction"],
                "label": job["label"],
                "a": a,
                "b": b,
            }
        )

    last = grid_cache[(jobs[-1]["start"], jobs[-1]["stop"])]
    ctx.extras["density_extent"] = {
        axis: float(last["edges"][i][-1]) for i, axis in enumerate(AXES)
    }
    ctx.extras["density_widths"] = {
        axis: float(last["widths"][i]) for i, axis in enumerate(AXES)
    }
    ctx.extras["density_panels"] = panel_info
    ctx.extras["density_directions"] = top_directions
    return tables


def meta(ctx, tables) -> dict:
    """记录网格、panel 与色标设置；meta 只放 JSON 可表示值。"""
    sum_axis = str(ctx.params["sum_axis"]).lower()
    return {
        "sum_axis": sum_axis,
        "directions": list(ctx.extras.get("density_directions", [])),
        "panels": list(ctx.extras.get("density_panels", [])),
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
        "grid_extent": dict(ctx.extras.get("density_extent", {})),
    }


def _panel_data(ctx, table, x_axis: str, y_axis: str):
    cols = list(table.columns)
    pivot = table.pivot(index=cols[1], columns=cols[0], values=cols[2])
    shift = ctx.shift
    x = pivot.columns.to_numpy() + shift[AXES.index(x_axis)]
    y = pivot.index.to_numpy() + shift[AXES.index(y_axis)]
    return x, y, pivot.to_numpy()


def render_panel(ctx, request: PanelRequest) -> Panel:
    """density 的 Panel 模板：Field + 坐标轴 + 注释 + 色标。"""
    options = request.options
    a = str(options.get("a", "x"))
    b = str(options.get("b", "y"))
    x_range = options.get("xlim")
    y_range = options.get("ylim")

    def draw(ax):
        mesh = None
        for series in request.series:
            for field in series.fields:
                mesh = ax.pcolormesh(
                    field.x,
                    field.y,
                    field.values,
                    shading="auto",
                    cmap=options.get("cmap"),
                    vmin=options.get("vmin"),
                    vmax=options.get("vmax"),
                )
        annotations.draw(ax, ctx, x_axis=a)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return mesh

    return Panel(
        name="density",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel,
        ylabel=request.ylabel,
        aspect="equal",
        xlim=x_range,
        ylim=y_range,
        colorbar_label=options.get("colorbar_label"),
        panel_size=ctx.size("map"),
    )


def panels(ctx, tables) -> list[Panel]:
    items = list(tables.items())
    if not items:
        return []

    infos = list(getattr(ctx, "extras", {}).get("density_panels") or [])
    if not infos:
        infos = [
            {
                "table": name,
                "start": ctx.start,
                "stop": ctx.stop,
                "direction": next(
                    (direction for direction in DIRECTIONS
                     if direction == f"{str(list(table.columns)[0]).split('_', 1)[0]}"
                     f"{str(list(table.columns)[1]).split('_', 1)[0]}"),
                    None,
                ),
                "label": None,
                "a": str(list(table.columns)[0]).split("_", 1)[0],
                "b": str(list(table.columns)[1]).split("_", 1)[0],
            }
            for name, table in items
        ]

    names = {info["table"] for info in infos}
    for name, table in items:
        if name not in names:
            infos.append(
                {
                    "table": name,
                    "start": ctx.start,
                    "stop": ctx.stop,
                    "direction": None,
                    "label": None,
                    "a": str(list(table.columns)[0]).split("_", 1)[0],
                    "b": str(list(table.columns)[1]).split("_", 1)[0],
                }
            )

    all_values = np.concatenate(
        [tables[info["table"]].iloc[:, 2].to_numpy(dtype=float) for info in infos]
    )
    vmin_param = _optional_number(ctx.params.get("vmin"), "vmin")
    vmax_param = _optional_number(ctx.params.get("vmax"), "vmax")
    vmin = float(np.nanmin(all_values)) if vmin_param is None else vmin_param
    vmax = float(np.nanmax(all_values)) if vmax_param is None else vmax_param
    if vmin_param is not None and vmax_param is not None and vmax <= vmin:
        raise ValidationError(f"vmax（{vmax:g}）必须大于 vmin（{vmin:g}）")
    if vmax <= vmin:
        vmax = vmin + 1e-12
    cmap = _color_map(ctx)

    frame_count = len({info["start"] for info in infos})
    direction_count = len(
        {info.get("direction") for info in infos if info.get("direction")}
    )
    panels: list[Panel] = []
    for index, info in enumerate(infos):
        table = tables[info["table"]]
        a, b = info["a"], info["b"]
        x, y, values = _panel_data(ctx, table, a, b)
        x_range = plotutil.clip_window(ctx.window(a), (float(x.min()), float(x.max())))
        y_range = plotutil.clip_window(ctx.window(b), (float(y.min()), float(y.max())))
        title = _panel_label(ctx, info, frame_count, direction_count)
        field = Field(
            x=x,
            y=y,
            values=values,
            label=ctx.label("cbar"),
            unit="Å^-3",
            colorbar_label=ctx.label("cbar"),
        )
        series = Series(name=info["table"], fields=[field], label=ctx.label("cbar"))
        request = PanelRequest(
            recipe="density",
            series=[series],
            title=title,
            xlabel=ctx.label(f"axis_{a}"),
            ylabel=ctx.label(f"axis_{b}"),
            options={
                "a": a,
                "b": b,
                "cmap": cmap,
                "vmin": vmin,
                "vmax": vmax,
                "xlim": x_range,
                "ylim": y_range,
                "colorbar_label": (
                    ctx.label("cbar") if index == len(infos) - 1 else ""
                ),
            },
        )
        panels.append(render_panel(ctx, request))
    return panels


def figure_name(ctx, tables) -> str:
    if len(tables) > 1:
        return "density"
    return str(next(iter(tables)))
