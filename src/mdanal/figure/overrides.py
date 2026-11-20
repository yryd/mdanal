"""replot 的纯呈现覆盖配置。

只覆盖已有快照的 plot/语言/分辨率/标注/布局；不读取轨迹，不改变表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from ..errors import ValidationError
from ..plot.settings import parse_plot, parse_text
from .config import _panel_plot

OVERRIDE_KEYS = {"schema_version", "figures"}
FIGURE_KEYS = {"title", "lang", "dpi", "annotate", "ncols", "style", "panels"}
STYLE_KEYS = {"palette", "rc"}


@dataclass(frozen=True)
class FigureOverride:
    title: Any = None
    lang: str | None = None
    dpi: int | None = None
    annotate: bool | None = None
    ncols: int | None = None
    style: Mapping[str, Any] = field(default_factory=dict)
    panels: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class PlotOverrides:
    figures: Mapping[str, FigureOverride] = field(default_factory=dict)


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{where} 必须是映射", where=where)
    return dict(value)


def _one_figure(value: Any, where: str) -> FigureOverride:
    data = _mapping(value, where)
    unknown = set(data) - FIGURE_KEYS
    if unknown:
        raise ValidationError(
            f"{where} 含未知字段 {sorted(unknown)}；允许 {sorted(FIGURE_KEYS)}",
            where=where,
        )
    title = None
    if "title" in data:
        title = parse_text(data["title"], f"{where}.title")
    lang = data.get("lang")
    if lang is not None and lang not in ("zh", "en"):
        raise ValidationError(f"{where}.lang 只能是 zh/en", where=where)
    dpi = data.get("dpi")
    if dpi is not None and (
        isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0
    ):
        raise ValidationError(f"{where}.dpi 必须是正整数", where=where)
    annotate = data.get("annotate")
    if annotate is not None and not isinstance(annotate, bool):
        raise ValidationError(f"{where}.annotate 必须是布尔值", where=where)
    ncols = data.get("ncols")
    if ncols is not None and (
        isinstance(ncols, bool) or not isinstance(ncols, int) or ncols < 1
    ):
        raise ValidationError(f"{where}.ncols 必须是正整数", where=where)
    style = {}
    if "style" in data:
        raw_style = _mapping(data["style"], f"{where}.style")
        unknown = set(raw_style) - STYLE_KEYS
        if unknown:
            raise ValidationError(
                f"{where}.style 含未知字段 {sorted(unknown)}；允许 {sorted(STYLE_KEYS)}",
                where=where,
            )
        style = parse_plot(raw_style, f"{where}.style")
    raw_panels = data.get("panels") or []
    if not isinstance(raw_panels, (list, tuple)):
        raise ValidationError(f"{where}.panels 必须是列表", where=where)
    panels: dict[int, Mapping[str, Any]] = {}
    for index, panel in enumerate(raw_panels):
        if panel is None:
            continue
        panels[index] = _panel_plot(panel, f"{where}.panels[{index}]")
    return FigureOverride(
        title=title,
        lang=lang,
        dpi=dpi,
        annotate=annotate,
        ncols=ncols,
        style=style,
        panels=panels,
    )


def read_overrides(path: str | Path) -> PlotOverrides:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ValidationError(f"找不到 plot 覆盖配置：{config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"plot 覆盖配置无法读取：{config_path}（{exc}）") from exc
    if not isinstance(raw, Mapping):
        raise ValidationError("plot 覆盖配置必须是映射", where=str(config_path))
    data = dict(raw)
    unknown = set(data) - OVERRIDE_KEYS
    if unknown:
        raise ValidationError(
            f"plot 覆盖配置含未知字段 {sorted(unknown)}；"
            f"允许 {sorted(OVERRIDE_KEYS)}",
            where=str(config_path),
        )
    if data.get("schema_version") != 1:
        raise ValidationError("plot 覆盖配置的 schema_version 必须是 1")
    raw_figures = data.get("figures") or {}
    if not isinstance(raw_figures, Mapping):
        raise ValidationError("plot 覆盖配置的 figures 必须是映射")
    figures = {
        str(name): _one_figure(value, f"figures.{name}")
        for name, value in raw_figures.items()
    }
    return PlotOverrides(figures=figures)
