"""统一绘图入口：插件 figures → 呈现覆盖 → 保存/关闭。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
import matplotlib.pyplot as plt
from cycler import cycler

from . import chart, plotutil
from .figure import Figure
from .recipes import FigureRecipe
from ..errors import MdanalError, ValidationError

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or not SAFE_NAME.match(name):
        raise ValidationError(
            f"图名必须是安全文件名（字母、数字、_ . -），收到 {name!r}"
        )
    if name in (".", "..") or name != Path(name).name:
        raise ValidationError(f"图名不能包含路径：{name!r}")
    return name


def _data_axes(fig):
    return [axis for axis in fig.axes if axis.get_label() != "<colorbar>"]


def _apply_settings(fig, settings: Mapping[str, Any], lang: str) -> None:
    title = settings.get("title")
    xlabel = settings.get("xlabel")
    ylabel = settings.get("ylabel")
    for axis in _data_axes(fig):
        if title is not None:
            axis.set_title(plotutil.resolve_text(title, lang))
        if xlabel is not None:
            axis.set_xlabel(plotutil.resolve_text(xlabel, lang))
        if ylabel is not None:
            axis.set_ylabel(plotutil.resolve_text(ylabel, lang))
        for key in ("xlim", "ylim"):
            bounds = settings.get(key)
            if bounds is not None:
                getattr(axis, f"set_{key[0]}lim")(bounds[0], bounds[1])


def _merge_plot_settings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in ("window", "rc", "layout") and isinstance(value, Mapping):
            current = dict(merged.get(key) or {})
            current.update(value)
            merged[key] = current
        else:
            merged[key] = value
    return merged


def _effective_settings(
    base: Mapping[str, Any],
    figure_spec: Mapping[str, Any] | None,
    *,
    priority: str,
) -> dict[str, Any]:
    overrides = (figure_spec or {}).get("plot") or {}
    if priority == "settings":
        return _merge_plot_settings(overrides, base)
    return _merge_plot_settings(base, overrides)


def _rc_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    rc = dict(settings.get("rc") or {})
    if settings.get("palette"):
        rc["axes.prop_cycle"] = cycler(color=list(settings["palette"]))
    return rc


def _ncols(settings: Mapping[str, Any], panels: Sequence[Any], recipe_ncols: int | None) -> int:
    chosen = (settings.get("layout") or {}).get("ncols", recipe_ncols)
    if chosen is None:
        chosen = min(3, max(1, len(panels)))
    return int(chosen)


def _context_with_settings(ctx, settings: Mapping[str, Any]):
    method = getattr(ctx, "with_plot", None)
    return method(settings) if callable(method) else ctx


def render(
    module: Any,
    ctx,
    tables: Mapping[str, Any],
    target: Path,
    *,
    fmt: str = "png",
    settings: Mapping[str, Any] | None = None,
    figures: Mapping[str, Any] | None = None,
    override_priority: str = "figure",
) -> list[Path]:
    """调用 figures、施加呈现覆盖，并把每张图保存到 target/figures。

    `override_priority="figure"` 用于 run：analysis 内单图 `plot` 覆盖分析默认；
    `"settings"` 用于 replot：重绘配置覆盖快照里保存的单图设置。
    """
    if fmt not in ("png", "svg", "pdf"):
        raise ValidationError(f"图件格式只能是 png/svg/pdf，收到 {fmt!r}")
    if override_priority not in ("figure", "settings"):
        raise ValidationError(
            f"override_priority 只能是 figure/settings，收到 {override_priority!r}"
        )
    has_recipes = hasattr(module, "FIGURES")
    has_panels = hasattr(module, "panels")
    if not has_recipes and not has_panels and not hasattr(module, "figures"):
        return []
    plotutil.apply_style()
    settings = dict(settings or {})
    selected = dict(figures or {})
    before = set(plt.get_fignums())
    try:
        try:
            paths: list[Path] = []
            if has_recipes:
                recipes = dict(getattr(module, "FIGURES"))
                if not selected:
                    preferred = "raw" if "raw" in recipes else next(iter(recipes))
                    selected = {preferred: {"plot": {}}}
                for figure_name_key, figure_spec in selected.items():
                    recipe = recipes.get(str(figure_name_key))
                    if not isinstance(recipe, FigureRecipe):
                        raise ValidationError(
                            f"未知 figure recipe {figure_name_key!r}；"
                            f"可用 {sorted(recipes)}"
                        )
                    missing = [name for name in recipe.requires if name not in tables]
                    if missing:
                        raise ValidationError(
                            f"figure {figure_name_key!r} 缺少表 {missing}"
                        )
                    figure_settings = _effective_settings(
                        settings, figure_spec, priority=override_priority
                    )
                    figure_ctx = _context_with_settings(ctx, figure_settings)
                    with matplotlib.rc_context(_rc_settings(figure_settings)):
                        panels = list(recipe.build(figure_ctx, dict(tables)) or [])
                        if not panels:
                            continue
                        ncols = _ncols(figure_settings, panels, recipe.ncols)
                        filename = recipe.filename or recipe.name
                        fig = Figure(panels, ncols=ncols).build()
                        _apply_settings(fig, figure_settings, ctx.lang)
                        name = _safe_name(str(filename))
                        path = target / "figures" / f"{name}.{fmt}"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        chart.save(fig, path, ctx.dpi)
                        paths.append(path)
            elif has_panels:
                with matplotlib.rc_context(_rc_settings(settings)):
                    panels = module.panels(ctx, dict(tables)) or []
                    if not isinstance(panels, (list, tuple)):
                        raise ValidationError("panels() 必须返回 Panel 列表")
                    if not panels:
                        return []
                    ncols = _ncols(settings, panels, None)
                    name_fn = getattr(module, "figure_name", None)
                    name = (
                        str(name_fn(ctx, dict(tables)))
                        if callable(name_fn)
                        else str(panels[0].name)
                    )
                    fig = Figure(panels, ncols=ncols).build()
                    _apply_settings(fig, settings, ctx.lang)
                    name = _safe_name(name)
                    path = target / "figures" / f"{name}.{fmt}"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    chart.save(fig, path, ctx.dpi)
                    paths.append(path)
            else:
                with matplotlib.rc_context(_rc_settings(settings)):
                    produced = module.figures(ctx, dict(tables)) or []
                normalized = []
                for entry in produced:
                    if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
                        raise ValidationError("figures() 必须返回 (名称, Figure[, 设置]) 列表")
                    normalized.append(
                        (entry[0], entry[1], entry[2] if len(entry) == 3 else settings)
                    )
                names = [str(name) for name, _, _ in normalized]
                if len(set(names)) != len(names):
                    raise ValidationError(f"figures() 产生了重名图 {names}")
                for name, fig, figure_settings in normalized:
                    with matplotlib.rc_context(_rc_settings(figure_settings)):
                        name = _safe_name(str(name))
                        _apply_settings(fig, figure_settings, ctx.lang)
                        path = target / "figures" / f"{name}.{fmt}"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        chart.save(fig, path, ctx.dpi)
                        paths.append(path)
            return paths
        except MdanalError:
            raise
        except Exception as exc:
            raise MdanalError(f"绘图失败：{exc}") from exc
    except BaseException:
        # 只关闭本次 render 新建的 Figure；调用方已有的图不动。
        for number in set(plt.get_fignums()) - before:
            plt.close(number)
        raise
