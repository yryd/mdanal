"""解析 figure-first 输入（sources + figures）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..config.source import read_sources
from ..config.system import SystemConfig
from ..errors import ValidationError
from ..plot.settings import parse_plot
from .model import CompareSpec, CurveSource, FigureSpec, PanelRef, StackSpec

CONFIG_KEYS = {"schema_version", "name", "render", "sources", "figures"}
RENDER_KEYS = {"lang", "dpi", "annotate"}
FIGURE_KEYS = {"name", "layout", "title", "panels"}
PANEL_KEYS = {
    "source",
    "pack",
    "product",
    "select",
    "compute",
    "derive",
    "section",
    "plot",
}
COMPARE_KEYS = {
    "pack",
    "product",
    "select",
    "compute",
    "derive",
    "section",
    "plot",
    "sources",
}
STACK_KEYS = set(COMPARE_KEYS)
VIEW_KEYS = {"plane", "axis"}


@dataclass(frozen=True)
class FigureProject:
    yaml_path: Path
    name: str
    sources: Mapping[str, SystemConfig]
    figures: tuple[FigureSpec, ...]
    lang: str = "zh"
    dpi: int = 300
    annotate: bool = False


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{where} 必须是映射", where=where)
    return dict(value)


def _unknown(value: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(
            f"{where} 含未知字段 {sorted(unknown)}；允许 {sorted(allowed)}",
            where=where,
        )


def _str_map(value: Any, where: str, *, allow_empty: bool = True) -> dict[str, str]:
    if value is None:
        return {}
    data = _mapping(value, where)
    if not allow_empty and not data:
        raise ValidationError(f"{where} 不能为空", where=where)
    result: dict[str, str] = {}
    for key, item in data.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValidationError(f"{where} 的键和值都必须是字符串", where=where)
        result[key] = item
    return result


def _any_map(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    return _mapping(value, where)


def _section(value: Any, where: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise ValidationError(f"{where} 必须是 [起, 止] 两个整数", where=where)
    start, stop = int(value[0]), int(value[1])
    if start < 0 or stop <= start:
        raise ValidationError(
            f"{where} 需满足 0 ≤ 起 < 止，收到 {[start, stop]}", where=where
        )
    return (start, stop)


def _panel_plot(value: Any, where: str) -> dict[str, Any]:
    raw = _any_map(value, where)
    view: dict[str, Any] = {}
    for key in VIEW_KEYS:
        if key in raw:
            item = raw.pop(key)
            if not isinstance(item, str):
                raise ValidationError(f"{where}.{key} 必须是字符串", where=where)
            view[key] = item
    if "plane" in view and view["plane"] not in ("xy", "xz", "yz"):
        raise ValidationError(
            f"{where}.plane 只能是 xy/xz/yz，收到 {view['plane']!r}", where=where
        )
    if "axis" in view and view["axis"] not in ("x", "y", "z"):
        raise ValidationError(
            f"{where}.axis 只能是 x/y/z，收到 {view['axis']!r}", where=where
        )
    parsed = parse_plot(raw, where)
    parsed.update(view)
    return parsed


def _panel(
    value: Any, where: str, sources: Mapping[str, Any]
) -> PanelRef:
    data = _mapping(value, where)
    _unknown(data, PANEL_KEYS, where)
    for key in ("source", "pack", "product"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValidationError(f"{where}.{key} 必须是非空字符串", where=where)
    if data["source"] not in sources:
        raise ValidationError(
            f"{where}.source={data['source']!r} 不在 sources 中；"
            f"可用 {sorted(sources)}",
            where=where,
        )
    return PanelRef(
        source=str(data["source"]),
        pack=str(data["pack"]),
        product=str(data["product"]),
        select=_str_map(data.get("select"), f"{where}.select"),
        compute=_any_map(data.get("compute"), f"{where}.compute"),
        derive=_any_map(data.get("derive"), f"{where}.derive"),
        section=_section(data.get("section"), f"{where}.section"),
        plot=_panel_plot(data.get("plot"), f"{where}.plot"),
    )


def _curve_spec(
    data: Mapping[str, Any], where: str, sources: Mapping[str, Any], spec_cls
):
    _unknown(data, STACK_KEYS if spec_cls is StackSpec else COMPARE_KEYS, where)
    for key in ("pack", "product"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValidationError(f"{where}.{key} 必须是非空字符串", where=where)
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, (list, tuple)) or len(raw_sources) < 2:
        raise ValidationError(
            f"{where}.sources 必须是至少两个来源的列表", where=where
        )
    entries: list[CurveSource] = []
    for index, item in enumerate(raw_sources):
        entry_where = f"{where}.sources[{index}]"
        if isinstance(item, str):
            source, label = item, item
        elif isinstance(item, Mapping):
            entry = dict(item)
            _unknown(
                entry,
                {"source", "label", "select", "compute", "derive", "section"},
                entry_where,
            )
            source = entry.get("source")
            label = entry.get("label", source)
        else:
            raise ValidationError(
                f"{entry_where} 必须是 source 名或 {{source, label}}", where=entry_where
            )
        if not isinstance(source, str) or not source:
            raise ValidationError(f"{entry_where}.source 必须是非空字符串")
        if source not in sources:
            raise ValidationError(
                f"{entry_where}.source={source!r} 不在 sources 中；"
                f"可用 {sorted(sources)}",
                where=entry_where,
            )
        if not isinstance(label, str) or not label:
            raise ValidationError(f"{entry_where}.label 必须是非空字符串")
        override_select = _str_map(
            entry.get("select") if isinstance(item, Mapping) else None,
            f"{entry_where}.select",
        )
        override_compute = _any_map(
            entry.get("compute") if isinstance(item, Mapping) else None,
            f"{entry_where}.compute",
        )
        override_derive = _any_map(
            entry.get("derive") if isinstance(item, Mapping) else None,
            f"{entry_where}.derive",
        )
        override_section = _section(
            entry.get("section") if isinstance(item, Mapping) else None,
            f"{entry_where}.section",
        )
        entries.append(
            CurveSource(
                source=source,
                label=label,
                select=override_select,
                compute=override_compute,
                derive=override_derive,
                section=override_section,
            )
        )
    if len({entry.label for entry in entries}) != len(entries):
        raise ValidationError(f"{where}.sources 的 label 不能重复", where=where)
    return spec_cls(
        pack=str(data["pack"]),
        product=str(data["product"]),
        sources=tuple(entries),
        select=_str_map(data.get("select"), f"{where}.select"),
        compute=_any_map(data.get("compute"), f"{where}.compute"),
        derive=_any_map(data.get("derive"), f"{where}.derive"),
        section=_section(data.get("section"), f"{where}.section"),
        plot=_panel_plot(data.get("plot"), f"{where}.plot"),
    )


def _compare(
    data: Mapping[str, Any], where: str, sources: Mapping[str, Any]
) -> CompareSpec:
    return _curve_spec(data, where, sources, CompareSpec)


def _stack(
    data: Mapping[str, Any], where: str, sources: Mapping[str, Any]
) -> StackSpec:
    return _curve_spec(data, where, sources, StackSpec)


def _figure(
    value: Any, where: str, sources: Mapping[str, Any]
) -> FigureSpec:
    data = _mapping(value, where)
    _unknown(data, FIGURE_KEYS, where)
    name = data.get("name")
    if (
        not isinstance(name, str)
        or not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
    ):
        raise ValidationError(
            f"{where}.name 必须是非空且不含路径分隔符", where=where
        )
    layout = data.get("layout") or {}
    if not isinstance(layout, Mapping):
        raise ValidationError(f"{where}.layout 必须是映射", where=where)
    _unknown(layout, {"ncols"}, f"{where}.layout")
    ncols = layout.get("ncols", 1)
    if isinstance(ncols, bool) or not isinstance(ncols, int) or ncols < 1:
        raise ValidationError(f"{where}.layout.ncols 必须是正整数", where=where)
    raw_panels = data.get("panels")
    if not isinstance(raw_panels, (list, tuple)) or not raw_panels:
        raise ValidationError(f"{where}.panels 必须是非空列表", where=where)
    items = []
    for index, entry in enumerate(raw_panels):
        item_where = f"{where}.panels[{index}]"
        if not isinstance(entry, Mapping):
            raise ValidationError(f"{item_where} 必须是映射", where=item_where)
        if "compare" in entry and "stack" in entry:
            raise ValidationError(
                f"{item_where} 不能同时有 compare 和 stack", where=item_where
            )
        if "compare" in entry:
            if set(entry) != {"compare"}:
                raise ValidationError(
                    f"{item_where} 有 compare 时不能再写其他字段", where=item_where
                )
            compare = entry["compare"]
            items.append(_compare(compare, f"{item_where}.compare", sources))
        elif "stack" in entry:
            if set(entry) != {"stack"}:
                raise ValidationError(
                    f"{item_where} 有 stack 时不能再写其他字段", where=item_where
                )
            stack = entry["stack"]
            items.append(_stack(stack, f"{item_where}.stack", sources))
        else:
            items.append(_panel(entry, item_where, sources))
    return FigureSpec(
        name=name,
        items=tuple(items),
        ncols=int(ncols),
        title=data.get("title"),
    )


def read_project(path: str | Path) -> FigureProject:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ValidationError(f"找不到图请求配置：{config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"图请求配置无法读取：{config_path}（{exc}）") from exc
    if not isinstance(raw, Mapping):
        raise ValidationError("图请求配置必须是映射", where=str(config_path))
    data = dict(raw)
    _unknown(data, CONFIG_KEYS, str(config_path))
    if data.get("schema_version") != 1:
        raise ValidationError(
            "schema_version 必须是 1", where=str(config_path)
        )
    name = data.get("name") or config_path.stem
    if not isinstance(name, str):
        raise ValidationError("name 必须是字符串", where=str(config_path))
    sources = read_sources(config_path, data.get("sources"))
    render = data.get("render") or {}
    if not isinstance(render, Mapping):
        raise ValidationError("render 必须是映射", where=str(config_path))
    _unknown(render, RENDER_KEYS, f"{config_path}:render")
    lang = render.get("lang", "zh")
    if lang not in ("zh", "en"):
        raise ValidationError("render.lang 只能是 zh/en")
    dpi = render.get("dpi", 300)
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValidationError("render.dpi 必须是正整数")
    annotate = render.get("annotate", False)
    if not isinstance(annotate, bool):
        raise ValidationError("render.annotate 必须是布尔值")
    raw_figures = data.get("figures")
    if not isinstance(raw_figures, (list, tuple)) or not raw_figures:
        raise ValidationError("figures 必须是非空列表", where=str(config_path))
    figures = tuple(
        _figure(entry, f"{config_path}:figures[{index}]", sources)
        for index, entry in enumerate(raw_figures)
    )
    names = [figure.name for figure in figures]
    if len(set(names)) != len(names):
        raise ValidationError(f"figures 名称重复：{names}", where=str(config_path))
    return FigureProject(
        yaml_path=config_path,
        name=name,
        sources=sources,
        figures=figures,
        lang=str(lang),
        dpi=int(dpi),
        annotate=bool(annotate),
    )
