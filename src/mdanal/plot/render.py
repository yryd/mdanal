"""统一绘图入口：插件 figures → 呈现覆盖 → 保存/关闭。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
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


def render(
    module: Any,
    ctx,
    tables: Mapping[str, Any],
    target: Path,
    *,
    fmt: str = "png",
    settings: Mapping[str, Any] | None = None,
    figures: Mapping[str, Any] | None = None,
) -> list[Path]:
    """调用 figures、施加呈现覆盖，并把每张图保存到 target/figures。"""
    if fmt not in ("png", "svg", "pdf"):
        raise ValidationError(f"图件格式只能是 png/svg/pdf，收到 {fmt!r}")
    has_recipes = hasattr(module, "FIGURES")
    has_panels = hasattr(module, "panels")
    if not has_recipes and not has_panels and not hasattr(module, "figures"):
        return []
    plotutil.apply_style()
    settings = dict(settings or {})
    selected = dict(figures or {})
    rc = dict(settings.get("rc") or {})
    if settings.get("palette"):
        rc["axes.prop_cycle"] = cycler(color=list(settings["palette"]))
    with matplotlib.rc_context(rc):
        try:
            if has_recipes:
                recipes = dict(getattr(module, "FIGURES"))
                if not selected:
                    preferred = "raw" if "raw" in recipes else next(iter(recipes))
                    selected = {preferred: {"plot": {}}}
                produced: list[tuple[str, Any, Mapping[str, Any]]] = []
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
                    panels = list(recipe.build(ctx, dict(tables)) or [])
                    if not panels:
                        continue
                    figure_settings = dict(settings)
                    overrides = (figure_spec or {}).get("plot") or {}
                    figure_settings = _merge_plot_settings(figure_settings, overrides)
                    ncols = int(
                        (figure_settings.get("layout") or {}).get(
                            "ncols", recipe.ncols or 3
                        )
                    )
                    filename = recipe.filename or (
                        "msd" if recipe.name == "raw" and hasattr(module, "__name__")
                        else recipe.name
                    )
                    produced.append(
                        (str(filename), Figure(panels, ncols=ncols).build(), figure_settings)
                    )
            elif has_panels:
                panels = module.panels(ctx, dict(tables)) or []
                if not isinstance(panels, (list, tuple)):
                    raise ValidationError("panels() 必须返回 Panel 列表")
                if not panels:
                    return []
                ncols = int(
                    (settings.get("layout") or {}).get("ncols", 3)
                )
                name_fn = getattr(module, "figure_name", None)
                name = (
                    str(name_fn(ctx, dict(tables)))
                    if callable(name_fn)
                    else str(panels[0].name)
                )
                produced = [(name, Figure(panels, ncols=ncols).build(), settings)]
            else:
                produced = module.figures(ctx, dict(tables)) or []
        except MdanalError:
            raise
        except Exception as exc:
            raise MdanalError(f"绘图失败：{exc}") from exc

        if not isinstance(produced, (list, tuple)):
            raise ValidationError("绘图入口必须返回 (名称, Figure) 列表")
        normalized = []
        for entry in produced:
            if len(entry) == 2:
                normalized.append((entry[0], entry[1], settings))
            else:
                normalized.append(entry)
        names = [name for name, _, _ in normalized]
        if len(set(names)) != len(names):
            raise ValidationError(f"figures() 产生了重名图 {names}")
        paths: list[Path] = []
        for name, fig, figure_settings in normalized:
            name = _safe_name(name)
            _apply_settings(fig, figure_settings, ctx.lang)
            path = target / "figures" / f"{name}.{fmt}"
            path.parent.mkdir(parents=True, exist_ok=True)
            chart.save(fig, path, ctx.dpi)
            paths.append(path)
        return paths
