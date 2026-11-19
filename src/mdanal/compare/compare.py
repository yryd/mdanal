"""多体系对比：读已有输出目录里的表与溯源，按对齐规则叠成一张图。

不重读轨迹，也不改单体系的运行管线；对齐平移只在对比时施加。
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml
from matplotlib import rcParams

from ..plot import chart
from ..plot.figure import Figure
from ..plot.plotutil import Labels
from ..plot.settings import resolve_palette
from ..plot.specs import Curve, PanelRequest, Series
from ..errors import MdanalError, ValidationError
from ..run.writers import write_provenance

MODES = ("left", "center")
AXES = ("x", "y", "z")
TOP_KEYS = {"items", "figure", "out"}
ITEM_KEYS = {"root", "label", "anchor", "t_offset"}
FIGURE_KEYS = {
    "analysis", "table", "align", "xlim", "ylim", "xlabel", "ylabel", "title", "y",
    "palette", "panels", "layout", "recipe",
}
PANEL_KEYS = {"analysis", "table", "x", "y", "xlim", "ylim", "xlabel", "ylabel", "title", "legend"}


@dataclass
class CompareItem:
    root: Path
    label: str
    anchor: Mapping[str, float] = field(default_factory=dict)
    t_offset: float = 0.0
    shift: dict[str, float] = field(default_factory=dict)
    box: tuple[float, float, float] = (0.0, 0.0, 0.0)


class _CompareContext:
    """供插件 render_panel 使用的最小绘图上下文；compare 不读轨迹。"""

    def __init__(self, labels: Mapping[str, str], lang: str):
        self._labels = Labels(labels)
        self.lang = lang
        self.annotate = False
        self.annotations = ()
        self.shift = (0.0, 0.0, 0.0)
        self.params: dict[str, Any] = {}
        self.meta: dict[str, Any] = {}
        self.extras: dict[str, Any] = {}
        self.start = 0
        self.stop = 1
        self.frame_dt_ps = 1.0
        self.selection_frame = 0
        self.windows: dict[str, tuple[float, float]] = {}

    def label(self, key: str, **fmt: Any) -> str:
        return self._labels(key, **fmt)

    def window(self, axis: str):
        return self.windows.get(axis)

    def annotation(self) -> str:
        return ""

    def size(self, name: str = "single") -> tuple[float, float]:
        return (3.5, 2.6)


def run_compare(
    config_path: str | Path,
    out_dir: str | Path | None = None,
    registry: Mapping[str, Any] | None = None,
    lang: str = "zh",
    force: bool = False,
) -> Path:
    config_path = Path(config_path).expanduser().resolve()
    config = _load_config(config_path)
    items = [_load_item(entry, config_path) for entry in config["items"]]
    figure = config["figure"]
    if "panels" in figure:
        return _run_panel_compare(
            config_path, config, items, out_dir=out_dir, lang=lang, force=force
        )
    directory = str(figure["analysis"])

    # 同一次对比必须来自同一分析；参数（如 dim）可由 figure.table 覆盖
    module_name, params = _resolve_analysis(items[0], directory)
    comparison = _module_compare(module_name, params, registry)
    for item in items[1:]:
        other_module, other_params = _resolve_analysis(item, directory)
        if other_module != module_name or other_params != params:
            raise ValidationError(
                f"{item.root} 的 {directory} 与第一个体系的分析参数不同；"
                "同一张对比图只能叠同一种分析、同一组参数",
                where=str(item.root),
            )

    table_name = str(figure.get("table") or comparison["table"])
    x_column = comparison["x"]
    y_columns = [str(column) for column in (figure.get("y") or comparison["y"])]
    labels = comparison.get("labels", {}).get(lang, {})
    box_axis = comparison["box_axis"]
    x_axis = x_column[0] if x_column[:1] in AXES else None
    align = _parse_align(figure.get("align"), config_path)

    time_axis = _is_time_axis(box_axis, x_column)
    if not time_axis:
        offenders = [item.label for item in items if item.t_offset]
        if offenders:
            raise ValidationError(
                "t_offset 只能用于时间轴（列名以 _ps/_ns 结尾且非盒坐标轴）；"
                f"{offenders} 设了非零偏移，而当前横轴是 {x_column!r}",
                where=str(config_path),
            )

    blocks: list[pd.DataFrame] = []
    for item in items:
        frame = _read_table(item, directory, table_name)
        _require_columns(frame, [x_column, *y_columns], item, directory)
        shift = 0.0
        if box_axis and x_axis:
            shift = _axis_shift(item, x_axis, align)
            item.shift[x_axis] = shift
        offset = item.t_offset if time_axis else 0.0
        x = frame[x_column].to_numpy(dtype=float) + shift + offset
        block = pd.DataFrame({"item": item.label, "x": x})
        for column in y_columns:
            block[column] = frame[column].to_numpy(dtype=float)
        blocks.append(block)

    merged = pd.concat(blocks, ignore_index=True)
    out = (
        Path(out_dir).expanduser().resolve()
        if out_dir
        else (config_path.parent / str(config.get("out", "compare"))).resolve()
    )
    _guard_output(out, items, config_path, force=force)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    merged.to_csv(
        out / "tables" / f"{table_name}.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )

    multi_column = len(y_columns) > 1
    show_legend = len(items) > 1 or multi_column
    chart.apply_style()
    colors = (
        list(figure["palette"])
        if figure.get("palette")
        else rcParams["axes.prop_cycle"].by_key().get("color") or ["C0"]
    )
    styles = ("-", "--", ":", "-.")
    xlabel = str(figure.get("xlabel") or labels.get(x_column, x_column))
    ylabel = str(
        figure.get("ylabel")
        or ", ".join(labels.get(column, column) for column in y_columns)
    )
    xlim = figure.get("xlim")
    if xlim is not None:
        low, high = (float(value) for value in xlim)
    else:
        low, high = _default_range(items, align, box_axis, x_axis, merged)
    ylim = figure.get("ylim")
    if ylim is not None:
        if (
            not isinstance(ylim, (list, tuple))
            or len(ylim) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in ylim)
            or float(ylim[1]) <= float(ylim[0])
        ):
            raise ValidationError(f"figure.ylim 必须是递增的两个数，收到 {ylim!r}")
        y_low, y_high = float(ylim[0]), float(ylim[1])
    else:
        y_low = y_high = None

    # 新路径：插件声明 render_panel 时，compare 只提供 Curve/Series/PanelRequest，
    # 最终仍由插件自己的 Panel 模板绘制（注释/参考线/标点不会丢）。
    renderer = None
    comparison_module = comparison.get("module")
    if comparison_module:
        try:
            module = importlib.import_module(str(comparison_module))
        except ImportError as exc:
            raise MdanalError(f"无法导入对比分析模块 {comparison_module!r}: {exc}") from exc
        renderer = getattr(module, "render_panel", None)

    if callable(renderer):
        series: list[Series] = []
        for column_index, column in enumerate(y_columns):
            curves: list[Curve] = []
            for block_index, block in enumerate(blocks):
                item_label = str(block["item"].iloc[0])
                if not show_legend:
                    curve_label = ""
                elif multi_column:
                    curve_label = f"{item_label} · {labels.get(column, column)}"
                else:
                    curve_label = item_label
                curves.append(
                    Curve(
                        x=block["x"].to_numpy(dtype=float),
                        y=block[column].to_numpy(dtype=float),
                        label=curve_label,
                        color=colors[block_index % len(colors)],
                        linestyle=styles[column_index % len(styles)],
                        source=item_label,
                    )
                )
            series.append(
                Series(
                    name=column,
                    curves=curves,
                    label=labels.get(column, column),
                )
            )
        panel_labels = (comparison.get("panel_labels") or {}).get(lang)
        if panel_labels is None:
            raise ValidationError(
                f"分析 {module_name!r} 缺少语言 {lang!r} 的 Panel 标签",
                where=str(config_path),
            )
        context = _CompareContext(panel_labels, lang)
        request = PanelRequest(
            recipe=module_name,
            series=series,
            title=str(figure.get("title") or ""),
            xlabel=xlabel,
            ylabel=ylabel,
            options={"axis": x_axis, "legend": show_legend},
        )
        panel = renderer(context, request)
        fig = Figure([panel], ncols=1).build()
        ax = fig.axes[0]
    else:
        # 兼容尚未迁移到 render_panel 的插件。
        fig, ax = chart.figure("single")
        for block_index, block in enumerate(blocks):
            item_label = str(block["item"].iloc[0])
            color = colors[block_index % len(colors)]
            for column_index, column in enumerate(y_columns):
                if not show_legend:
                    label = None
                elif multi_column:
                    label = f"{item_label} · {labels.get(column, column)}"
                else:
                    label = item_label
                chart.line(
                    ax,
                    block["x"],
                    block[column],
                    lw=1.2,
                    color=color,
                    ls=styles[column_index % len(styles)],
                    label=label,
                )

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if figure.get("title"):
        ax.set_title(str(figure["title"]))
    ax.set_xlim(low, high)
    if y_low is not None and y_high is not None:
        ax.set_ylim(y_low, y_high)
    if show_legend and not callable(renderer):
        chart.legend(ax)
    chart.save(fig, out / f"{directory}.png", dpi=300)

    write_provenance(
        out,
        {
            "config": str(config_path),
            "analysis": directory,
            "module": module_name,
            "recipe": str(figure.get("recipe") or "raw"),
            "table": table_name,
            "x": x_column,
            "y": y_columns,
            "lang": lang,
            "palette": list(figure["palette"]) if figure.get("palette") else None,
            "time_axis": time_axis,
            "xlabel": xlabel,
            "ylabel": ylabel,
            "align": dict(align),
            "xlim": [low, high],
            "ylim": [y_low, y_high] if y_low is not None else None,
            "items": [
                {
                    "root": str(item.root),
                    "label": item.label,
                    "shift": dict(item.shift),
                    "t_offset": item.t_offset,
                    "box": list(item.box),
                }
                for item in items
            ],
        },
    )
    return out


def _run_panel_compare(
    config_path: Path,
    config: Mapping[str, Any],
    items: list[CompareItem],
    *,
    out_dir: str | Path | None,
    lang: str,
    force: bool,
) -> Path:
    """一个 compare 配置组织多个 Panel；每个 Panel 内部可叠多个 Series。"""
    figure = config["figure"]
    panel_specs = list(figure["panels"])
    align = _parse_align(figure.get("align"), config_path)
    ncols = int((figure.get("layout") or {}).get("ncols", len(panel_specs)))

    out = (
        Path(out_dir).expanduser().resolve()
        if out_dir
        else (config_path.parent / str(config.get("out", "compare"))).resolve()
    )
    _guard_output(out, items, config_path, force=force)
    (out / "tables").mkdir(parents=True, exist_ok=True)
    chart.apply_style()
    colors = (
        list(figure["palette"])
        if figure.get("palette")
        else rcParams["axes.prop_cycle"].by_key().get("color") or ["C0"]
    )
    styles = ("-", "--", ":", "-.")

    rendered_panels = []
    panel_records: list[dict[str, Any]] = []
    used_table_files: set[str] = set()
    for panel_spec in panel_specs:
        directory = str(panel_spec["analysis"])
        module_name, params = _resolve_analysis(items[0], directory)
        comparison = _module_compare(module_name, params)
        for item in items[1:]:
            other_module, other_params = _resolve_analysis(item, directory)
            if other_module != module_name or other_params != params:
                raise ValidationError(
                    f"{item.root} 的 {directory} 与第一个体系的分析参数不同；"
                    "同一 Panel 只能叠同一种分析、同一组参数",
                    where=str(item.root),
                )
        renderer = getattr(
            importlib.import_module(str(comparison["module"])), "render_panel", None
        )
        if not callable(renderer):
            raise ValidationError(
                f"分析 {module_name!r} 没有 render_panel，不能用于多 Panel compare"
            )

        table_name = str(panel_spec.get("table") or comparison["table"])
        x_column = str(panel_spec.get("x") or comparison["x"])
        y_columns = [
            str(column)
            for column in (panel_spec.get("y") or comparison["y"])
        ]
        labels = comparison.get("labels", {}).get(lang, {})
        box_axis = bool(comparison["box_axis"])
        x_axis = x_column[0] if x_column[:1] in AXES else None
        time_axis = _is_time_axis(box_axis, x_column)
        if not time_axis:
            offenders = [item.label for item in items if item.t_offset]
            if offenders:
                raise ValidationError(
                    "t_offset 只能用于时间轴（列名以 _ps/_ns 结尾且非盒坐标轴）；"
                    f"{offenders} 设了非零偏移，而当前横轴是 {x_column!r}",
                    where=str(config_path),
                )

        blocks: list[pd.DataFrame] = []
        for item in items:
            frame = _read_table(item, directory, table_name)
            _require_columns(frame, [x_column, *y_columns], item, directory)
            shift = 0.0
            if box_axis and x_axis:
                shift = _axis_shift(item, x_axis, align)
                item.shift[x_axis] = shift
            offset = item.t_offset if time_axis else 0.0
            block = pd.DataFrame(
                {
                    "item": item.label,
                    "x": frame[x_column].to_numpy(dtype=float) + shift + offset,
                }
            )
            for column in y_columns:
                block[column] = frame[column].to_numpy(dtype=float)
            blocks.append(block)
        merged = pd.concat(blocks, ignore_index=True)
        # 同一 analysis/table 可被多个 Panel 引用，但列不同；不能互相覆盖。
        table_stem = f"{directory}__{table_name}"
        candidate = table_stem
        serial = 2
        while candidate in used_table_files:
            candidate = f"{table_stem}__panel{serial}"
            serial += 1
        used_table_files.add(candidate)
        table_file = out / "tables" / f"{candidate}.csv"
        merged.to_csv(
            table_file, index=False, encoding="utf-8-sig", float_format="%.8g"
        )

        xlim = panel_spec.get("xlim") or figure.get("xlim")
        if xlim is not None:
            x_low, x_high = (float(value) for value in xlim)
        else:
            x_low, x_high = _default_range(items, align, box_axis, x_axis, merged)
        ylim = panel_spec.get("ylim") or figure.get("ylim")
        if ylim is not None:
            y_low, y_high = (float(value) for value in ylim)
            if y_high <= y_low:
                raise ValidationError(
                    f"ylim 必须递增，收到 {ylim!r}", where=str(config_path)
                )
        else:
            y_low = y_high = None

        show_legend = bool(
            panel_spec.get("legend", len(items) > 1 or len(y_columns) > 1)
        )
        series: list[Series] = []
        for column_index, column in enumerate(y_columns):
            curves: list[Curve] = []
            for block_index, block in enumerate(blocks):
                item_label = str(block["item"].iloc[0])
                if not show_legend:
                    curve_label = ""
                elif len(y_columns) > 1:
                    curve_label = f"{item_label} · {labels.get(column, column)}"
                else:
                    curve_label = item_label
                curves.append(
                    Curve(
                        x=block["x"].to_numpy(dtype=float),
                        y=block[column].to_numpy(dtype=float),
                        label=curve_label,
                        color=colors[block_index % len(colors)],
                        linestyle=styles[column_index % len(styles)],
                        source=item_label,
                    )
                )
            series.append(
                Series(name=column, curves=curves, label=labels.get(column, column))
            )

        panel_labels = (comparison.get("panel_labels") or {}).get(lang)
        if panel_labels is None:
            raise ValidationError(
                f"分析 {module_name!r} 缺少语言 {lang!r} 的 Panel 标签",
                where=str(config_path),
            )
        context = _CompareContext(panel_labels, lang)
        xlabel = (
            panel_spec.get("xlabel")
            or figure.get("xlabel")
            or labels.get(x_column, x_column)
        )
        ylabel = (
            panel_spec.get("ylabel")
            or figure.get("ylabel")
            or ", ".join(labels.get(column, column) for column in y_columns)
        )
        request = PanelRequest(
            recipe=module_name,
            series=series,
            title=str(panel_spec.get("title") or directory),
            xlabel=str(xlabel),
            ylabel=str(ylabel),
            options={"axis": x_axis, "legend": show_legend},
        )
        panel = renderer(context, request)
        panel.xlim = (x_low, x_high)
        panel.ylim = (y_low, y_high) if y_low is not None else None
        rendered_panels.append(panel)
        panel_records.append(
            {
                "analysis": directory,
                "module": module_name,
                "table": table_name,
                "x": x_column,
                "y": y_columns,
                "xlim": [x_low, x_high],
                "ylim": [y_low, y_high] if y_low is not None else None,
                "table_file": table_file.relative_to(out).as_posix(),
            }
        )

    fig = Figure(
        rendered_panels,
        ncols=ncols,
        title=str(figure.get("title")) if figure.get("title") else None,
    ).build()
    chart.save(fig, out / "compare.png", dpi=300)

    write_provenance(
        out,
        {
            "config": str(config_path),
            "lang": lang,
            "palette": list(figure["palette"]) if figure.get("palette") else None,
            "align": dict(align),
            "layout": {"ncols": ncols},
            "recipe": str(figure.get("recipe") or "raw"),
            "panels": panel_records,
            "items": [
                {
                    "root": str(item.root),
                    "label": item.label,
                    "shift": dict(item.shift),
                    "t_offset": item.t_offset,
                    "box": list(item.box),
                }
                for item in items
            ],
        },
    )
    return out


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #


def _load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError("找不到对比配置", where=str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValidationError("顶层必须是映射", where=str(path))
    unknown = set(data) - TOP_KEYS
    if unknown:
        raise ValidationError(
            f"未知字段 {sorted(unknown)}；允许 {sorted(TOP_KEYS)}", where=str(path)
        )
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("items 必须是非空列表", where=f"{path}:items")
    for index, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            raise ValidationError("每条 item 必须是映射", where=f"{path}:items[{index}]")
        unknown = set(entry) - ITEM_KEYS
        if unknown:
            raise ValidationError(
                f"item 含未知字段 {sorted(unknown)}；允许 {sorted(ITEM_KEYS)}",
                where=f"{path}:items[{index}]",
            )
        if not isinstance(entry.get("root"), str) or not entry["root"].strip():
            raise ValidationError("item 缺少 root", where=f"{path}:items[{index}]")
    figure = data.get("figure")
    if not isinstance(figure, dict):
        raise ValidationError("figure 必须是映射", where=f"{path}:figure")
    unknown = set(figure) - FIGURE_KEYS
    if unknown:
        raise ValidationError(
            f"figure 含未知字段 {sorted(unknown)}；允许 {sorted(FIGURE_KEYS)}",
            where=f"{path}:figure",
        )
    if "recipe" in figure:
        if not isinstance(figure["recipe"], str) or not figure["recipe"]:
            raise ValidationError("figure.recipe 必须是非空字符串", where=f"{path}:figure")
        if figure["recipe"] != "raw":
            raise ValidationError(
                "当前 compare 只支持 figure.recipe: raw；fit/rdc 比较需后续实现",
                where=f"{path}:figure.recipe",
            )
    panels = figure.get("panels")
    if panels is not None:
        if not isinstance(panels, list) or not panels:
            raise ValidationError("figure.panels 必须是非空列表", where=f"{path}:figure")
        for index, entry in enumerate(panels, start=1):
            if not isinstance(entry, dict):
                raise ValidationError(
                    f"figure.panels[{index}] 必须是映射", where=f"{path}:figure"
                )
            unknown = set(entry) - PANEL_KEYS
            if unknown:
                raise ValidationError(
                    f"figure.panels[{index}] 含未知字段 {sorted(unknown)}；允许 {sorted(PANEL_KEYS)}",
                    where=f"{path}:figure",
                )
            if not isinstance(entry.get("analysis"), str):
                raise ValidationError(
                    f"figure.panels[{index}] 缺少 analysis", where=f"{path}:figure"
                )
    elif not isinstance(figure.get("analysis"), str):
        raise ValidationError("figure.analysis 必须是字符串", where=f"{path}:figure")
    layout = figure.get("layout")
    if layout is not None:
        if not isinstance(layout, dict) or set(layout) - {"ncols"}:
            raise ValidationError(
                "figure.layout 只允许 ncols", where=f"{path}:figure"
            )
        ncols = layout.get("ncols")
        if isinstance(ncols, bool) or not isinstance(ncols, int) or ncols < 1:
            raise ValidationError(
                "figure.layout.ncols 必须是正整数", where=f"{path}:figure"
            )
    if "palette" in figure:
        figure = dict(figure)
        figure["palette"] = list(
            resolve_palette(figure["palette"], f"{path}:figure.palette")
        )
        data = dict(data)
        data["figure"] = figure
    return data


def _load_item(entry: Mapping[str, Any], config_path: Path) -> CompareItem:
    root = Path(str(entry["root"])).expanduser()
    if not root.is_absolute():
        root = config_path.parent / root
    root = root.resolve()
    if not (root / "provenance.json").is_file():
        raise ValidationError(
            "该目录不是 mdanal 的输出（缺 provenance.json）", where=str(root)
        )
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    box = provenance.get("box", {}).get("length")
    if not box:
        raise ValidationError(
            "溯源里没有 box.length；请用当前版本重跑该体系", where=str(root)
        )
    anchor = entry.get("anchor") or {}
    if not isinstance(anchor, dict):
        raise ValidationError("anchor 必须是 {轴: 数值}", where=str(root))
    for axis, value in anchor.items():
        if (
            axis not in AXES
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            raise ValidationError(f"anchor 非法：{axis}={value!r}", where=str(root))
    return CompareItem(
        root=root,
        label=str(entry.get("label") or root.name),
        anchor={axis: float(value) for axis, value in anchor.items()},
        t_offset=float(entry.get("t_offset") or 0.0),
        box=tuple(float(value) for value in box),
    )


def _parse_align(value: Any, path: Path) -> dict[str, Any]:
    if value is None:
        return {axis: "center" for axis in AXES}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {axis: float(value) for axis in AXES}
    if isinstance(value, str):
        if value not in MODES:
            raise ValidationError(
                f"align 只能是 {list(MODES)} 或逐轴映射", where=f"{path}:figure"
            )
        return {axis: value for axis in AXES}
    if isinstance(value, dict):
        align: dict[str, Any] = {}
        for axis, mode in value.items():
            if axis not in AXES:
                raise ValidationError(
                    f"align 含未知轴 {axis!r}", where=f"{path}:figure"
                )
            if isinstance(mode, str) and mode in MODES:
                align[axis] = mode
            elif isinstance(mode, (int, float)) and not isinstance(mode, bool):
                align[axis] = float(mode)
            else:
                raise ValidationError(
                    f"align.{axis} 只能是 left/center 或数值，收到 {mode!r}",
                    where=f"{path}:figure",
                )
        for axis in AXES:
            align.setdefault(axis, "center")
        return align
    raise ValidationError("align 必须是字符串或映射", where=f"{path}:figure")


# --------------------------------------------------------------------------- #
# 读数与对齐
# --------------------------------------------------------------------------- #


def _resolve_analysis(item: CompareItem, directory: str) -> tuple[str, dict[str, Any]]:
    manifest_path = item.root / "manifest.csv"
    if not manifest_path.is_file():
        raise ValidationError("输出目录缺少 manifest.csv", where=str(item.root))
    manifest = pd.read_csv(manifest_path, encoding="utf-8-sig")
    rows = manifest[manifest["directory"] == directory]
    if rows.empty:
        available = ", ".join(sorted(manifest["directory"].astype(str)))
        raise ValidationError(
            f"该运行里没有分析目录 {directory!r}；可用：{available}",
            where=str(item.root),
        )
    row = rows.iloc[0]
    params = json.loads(row.get("params") or "{}")
    return str(row["name"]), params


def _module_compare(
    module_name: str,
    params: Mapping[str, Any],
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if registry is None:
        from ..config.registry import discover

        registry = discover().definitions
    definition = registry.get(module_name)
    if definition is None:
        raise MdanalError(f"找不到分析 {module_name}（不在当前注册表中）")
    comparison = definition.compare
    if not comparison:
        raise ValidationError(f"{module_name} 不支持对比（没有 COMPARE 声明）")

    values = {str(key): value for key, value in params.items()}
    if "dim" in values:
        values.setdefault("axis", values["dim"])
    return {
        "x": str(comparison["x"]).format(**values),
        "y": [str(column).format(**values) for column in comparison["y"]],
        "table": str(comparison.get("table", module_name)).format(**values),
        "box_axis": bool(comparison.get("box_axis")),
        "labels": dict(definition.column_labels),
        "panel_labels": dict(definition.labels),
        "module": str(definition.module),
    }


def _read_table(item: CompareItem, directory: str, table_name: str) -> pd.DataFrame:
    tables = item.root / directory / "tables"
    path = tables / f"{table_name}.csv"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in tables.glob("*.csv")))
        raise ValidationError(
            f"找不到表 {table_name!r}；可用：{available}", where=str(tables)
        )
    return pd.read_csv(path, encoding="utf-8-sig")


def _require_columns(
    frame: pd.DataFrame, columns: list[str], item: CompareItem, directory: str
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValidationError(
            f"{directory} 的表缺少列 {missing}；实际列为 {list(frame.columns)}",
            where=str(item.root),
        )


def _is_time_axis(box_axis: bool, x_column: str) -> bool:
    """只有非盒坐标轴且列名以 _ps/_ns 结尾时，才允许 t_offset。"""
    return (not box_axis) and str(x_column).endswith(("_ps", "_ns"))


def _axis_shift(item: CompareItem, axis: str, align: Mapping[str, Any]) -> float:
    if axis in item.anchor:
        return -float(item.anchor[axis])
    mode = align.get(axis, "center")
    if isinstance(mode, (int, float)) and not isinstance(mode, bool):
        return -float(mode)
    if mode == "left":
        return 0.0
    return -0.5 * item.box[AXES.index(axis)]


def _default_range(
    items: list[CompareItem],
    align: Mapping[str, Any],
    box_axis: bool,
    x_axis: str | None,
    merged: pd.DataFrame,
) -> tuple[float, float]:
    """缺省横轴范围：盒坐标轴取各体系平移后的并集，其余按数据范围。"""
    if box_axis and x_axis and all(x_axis in item.shift for item in items):
        index = AXES.index(x_axis)
        lows = [item.shift[x_axis] for item in items]
        highs = [item.shift[x_axis] + item.box[index] for item in items]
        return min(lows), max(highs)

    low = float(merged["x"].min())
    high = float(merged["x"].max())
    if high <= low:
        return low - 1.0, high + 1.0
    pad = 0.02 * (high - low)
    return low - pad, high + pad


def _guard_output(
    out: Path,
    items: Sequence[CompareItem],
    config_path: Path,
    *,
    force: bool,
) -> None:
    """compare 绝不能写进输入结果目录，也不能悄悄覆盖非空输出。"""
    for item in items:
        if out == item.root or out.is_relative_to(item.root) or item.root.is_relative_to(out):
            raise ValidationError(
                f"对比输出目录 {out} 与输入结果目录 {item.root} 重叠；"
                "请换一个独立的输出目录",
                where=str(config_path),
            )
    if out.exists():
        if not out.is_dir():
            raise ValidationError(f"对比输出路径不是目录：{out}", where=str(config_path))
        if any(out.iterdir()) and not force:
            raise ValidationError(
                f"对比输出目录非空：{out}；请换目录，或加 --force 覆盖",
                where=str(config_path),
            )
