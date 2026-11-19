"""system.yaml 顶层 figures：跨分析组合图的配置模型与校验。"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import ValidationError
from ..plot.settings import parse_plot

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
FIGURE_PLOT_KEYS = {"title", "palette", "rc"}
PANEL_PLOT_KEYS = {"title", "xlabel", "ylabel", "window", "xlim", "ylim"}


@dataclass(frozen=True)
class CrossPanelSpec:
    analysis: str
    recipe: str
    plot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossFigureSpec:
    name: str
    panels: tuple[CrossPanelSpec, ...]
    ncols: int = 3
    plot: Mapping[str, Any] = field(default_factory=dict)


def _safe_name(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or not SAFE_NAME.match(value):
        raise ValidationError(
            f"{where} 必须是安全标识符（字母、数字、_ . -），收到 {value!r}",
            where=where,
        )
    if value in (".", ".."):
        raise ValidationError(f"{where} 不能是 {value!r}", where=where)
    return value


def _layout(value: Any, where: str) -> int:
    if value is None:
        return 3
    if not isinstance(value, Mapping):
        raise ValidationError(f"{where} 必须是映射", where=where)
    unknown = set(value) - {"ncols"}
    if unknown:
        raise ValidationError(
            f"{where} 含未知字段 {sorted(unknown)}；允许 ['ncols']", where=where
        )
    ncols = value.get("ncols", 3)
    if isinstance(ncols, bool) or not isinstance(ncols, int) or ncols < 1:
        raise ValidationError(f"{where}.ncols 必须是正整数，收到 {ncols!r}", where=where)
    return ncols


def _subset(value: Any, allowed: set[str], where: str) -> dict[str, Any]:
    parsed = parse_plot(value, where)
    unknown = set(parsed) - allowed
    if unknown:
        raise ValidationError(
            f"{where} 含不允许的字段 {sorted(unknown)}；允许 {sorted(allowed)}",
            where=where,
        )
    return parsed


def parse_figures(value: Any, where: str) -> tuple[CrossFigureSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValidationError(f"{where} 必须是列表", where=where)
    result: list[CrossFigureSpec] = []
    names: set[str] = set()
    for index, entry in enumerate(value, start=1):
        position = f"{where}[{index}]"
        if not isinstance(entry, Mapping):
            raise ValidationError(f"{position} 必须是映射", where=position)
        unknown = set(entry) - {"name", "layout", "plot", "panels"}
        if unknown:
            raise ValidationError(
                f"{position} 含未知字段 {sorted(unknown)}；"
                "允许 ['name', 'layout', 'plot', 'panels']",
                where=position,
            )
        name = _safe_name(entry.get("name"), f"{position}.name")
        if name in names:
            raise ValidationError(f"{where} 中图名重复：{name!r}", where=position)
        names.add(name)
        panels_raw = entry.get("panels")
        if not isinstance(panels_raw, list) or not panels_raw:
            raise ValidationError(f"{position}.panels 必须是非空列表", where=position)
        panels: list[CrossPanelSpec] = []
        seen: set[tuple[str, str]] = set()
        for panel_index, panel in enumerate(panels_raw, start=1):
            panel_where = f"{position}.panels[{panel_index}]"
            if not isinstance(panel, Mapping):
                raise ValidationError(f"{panel_where} 必须是映射", where=panel_where)
            unknown = set(panel) - {"analysis", "recipe", "plot"}
            if unknown:
                raise ValidationError(
                    f"{panel_where} 含未知字段 {sorted(unknown)}；"
                    "允许 ['analysis', 'recipe', 'plot']",
                    where=panel_where,
                )
            analysis = _safe_name(panel.get("analysis"), f"{panel_where}.analysis")
            recipe = _safe_name(panel.get("recipe"), f"{panel_where}.recipe")
            key = (analysis, recipe)
            if key in seen:
                raise ValidationError(
                    f"{position} 中 analysis+recipe 重复：{analysis}/{recipe}",
                    where=panel_where,
                )
            seen.add(key)
            panels.append(
                CrossPanelSpec(
                    analysis=analysis,
                    recipe=recipe,
                    plot=_subset(
                        panel.get("plot"), PANEL_PLOT_KEYS, f"{panel_where}.plot"
                    ),
                )
            )
        result.append(
            CrossFigureSpec(
                name=name,
                panels=tuple(panels),
                ncols=_layout(entry.get("layout"), f"{position}.layout"),
                plot=_subset(entry.get("plot"), FIGURE_PLOT_KEYS, f"{position}.plot"),
            )
        )
    return tuple(result)


def validate_figures(cfg, items: Sequence[Any]) -> None:
    """在读取轨迹前检查 analysis/recipe 引用；表依赖留给 render 再查。"""
    specs = tuple(getattr(cfg, "figures", ()) or ())
    if not specs:
        return
    by_directory = {item.directory: item for item in items}
    problems: list[str] = []
    for spec in specs:
        for panel in spec.panels:
            item = by_directory.get(panel.analysis)
            if item is None:
                problems.append(
                    f"figures.{spec.name}: 引用的 analysis {panel.analysis!r} 不在本次计划中；"
                    f"可用 {sorted(by_directory)}"
                )
                continue
            try:
                module = importlib.import_module(item.definition.module)
            except ImportError as exc:
                problems.append(
                    f"figures.{spec.name}: {panel.analysis} 的模块无法导入：{exc}"
                )
                continue
            recipes = getattr(module, "FIGURES", None)
            if not isinstance(recipes, Mapping) or panel.recipe not in recipes:
                available = sorted(recipes) if isinstance(recipes, Mapping) else []
                problems.append(
                    f"figures.{spec.name}: {panel.analysis} 没有 figure recipe "
                    f"{panel.recipe!r}；可用 {available}"
                )
    if problems:
        raise ValidationError("\n".join(problems), where=str(cfg.yaml_path) + ":figures")
