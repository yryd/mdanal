"""多体系对比：读已有输出目录里的表与溯源，按对齐规则叠成一张图。

不重读轨迹，也不改单体系的运行管线；对齐平移只在对比时施加。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml
from matplotlib import rcParams

from ..plot import chart
from ..errors import MdanalError, ValidationError
from ..run.writers import write_provenance

MODES = ("left", "center")
AXES = ("x", "y", "z")
TOP_KEYS = {"items", "figure", "out"}
ITEM_KEYS = {"root", "label", "anchor", "t_offset"}
FIGURE_KEYS = {
    "analysis", "table", "align", "xlim", "xlabel", "ylabel", "title", "y",
}


@dataclass
class CompareItem:
    root: Path
    label: str
    anchor: Mapping[str, float] = field(default_factory=dict)
    t_offset: float = 0.0
    shift: dict[str, float] = field(default_factory=dict)
    box: tuple[float, float, float] = (0.0, 0.0, 0.0)


def run_compare(
    config_path: str | Path,
    out_dir: str | Path | None = None,
    registry: Mapping[str, Any] | None = None,
    lang: str = "zh",
) -> Path:
    config_path = Path(config_path).expanduser().resolve()
    config = _load_config(config_path)
    items = [_load_item(entry, config_path) for entry in config["items"]]
    figure = config["figure"]
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
                "t_offset 只能用于时间轴（列名以 _ps 结尾且非盒坐标轴）；"
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
        else config_path.parent / str(config.get("out", "compare"))
    )
    (out / "tables").mkdir(parents=True, exist_ok=True)
    merged.to_csv(
        out / "tables" / f"{table_name}.csv",
        index=False,
        encoding="utf-8-sig",
        float_format="%.8g",
    )

    fig, ax = chart.figure("single")
    multi_column = len(y_columns) > 1
    show_legend = len(items) > 1 or multi_column
    colors = rcParams["axes.prop_cycle"].by_key().get("color") or ["C0"]
    styles = ("-", "--", ":", "-.")
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

    xlabel = str(figure.get("xlabel") or labels.get(x_column, x_column))
    ylabel = str(
        figure.get("ylabel")
        or ", ".join(labels.get(column, column) for column in y_columns)
    )
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if figure.get("title"):
        ax.set_title(str(figure["title"]))
    xlim = figure.get("xlim")
    if xlim is not None:
        low, high = (float(value) for value in xlim)
    else:
        low, high = _default_range(items, align, box_axis, x_axis, merged)
    ax.set_xlim(low, high)
    if show_legend:
        chart.legend(ax)
    chart.save(fig, out / f"{directory}.png", dpi=300)

    write_provenance(
        out,
        {
            "config": str(config_path),
            "analysis": directory,
            "module": module_name,
            "table": table_name,
            "x": x_column,
            "y": y_columns,
            "lang": lang,
            "time_axis": time_axis,
            "xlabel": xlabel,
            "ylabel": ylabel,
            "align": dict(align),
            "xlim": [low, high],
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
    if not isinstance(figure.get("analysis"), str):
        raise ValidationError("figure.analysis 必须是字符串", where=f"{path}:figure")
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
    """只有非盒坐标轴且列名以 _ps 结尾时，才允许 t_offset。"""
    return (not box_axis) and str(x_column).endswith("_ps")


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
