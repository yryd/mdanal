"""跨分析 Figure：从多个 analysis 的 recipe 组合 Panel，不访问轨迹。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
from cycler import cycler

from ..errors import MdanalError, ValidationError
from ..run.writers import sha256
from . import chart, plotutil
from .figure import Figure
from .recipes import FigureRecipe
from .snapshot import json_safe, make_plot_context, read_tables


def _panel_settings(panel, settings: Mapping[str, Any], lang: str) -> None:
    if "title" in settings:
        panel.title = plotutil.resolve_text(settings["title"], lang)
    if "xlabel" in settings:
        panel.xlabel = plotutil.resolve_text(settings["xlabel"], lang)
    if "ylabel" in settings:
        panel.ylabel = plotutil.resolve_text(settings["ylabel"], lang)
    for key in ("xlim", "ylim"):
        if key in settings:
            bounds = settings[key]
            setattr(panel, key, (float(bounds[0]), float(bounds[1])))


def _record_for(records: Mapping[str, Any], analysis: str, figure: str):
    record = records.get(analysis)
    if record is None:
        raise ValidationError(
            f"figure {figure!r} 引用的 analysis {analysis!r} 没有可用结果"
        )
    return record


def _panels_for(
    spec,
    records: Mapping[str, Any],
    *,
    lang: str,
    dpi: int,
    annotate: bool,
) -> tuple[list[Any], list[dict[str, Any]]]:
    panels = []
    sources = []
    for item in spec.panels:
        record = _record_for(records, item.analysis, spec.name)
        module = record["module"]
        recipes = getattr(module, "FIGURES", None)
        if not isinstance(recipes, Mapping) or item.recipe not in recipes:
            available = sorted(recipes) if isinstance(recipes, Mapping) else []
            raise ValidationError(
                f"figure {spec.name!r}: analysis {item.analysis!r} 没有 recipe "
                f"{item.recipe!r}；可用 {available}"
            )
        recipe = recipes[item.recipe]
        if not isinstance(recipe, FigureRecipe):
            raise ValidationError(
                f"figure {spec.name!r}: analysis {item.analysis!r} 的 recipe "
                f"{item.recipe!r} 不是 FigureRecipe"
            )
        tables = read_tables(record["payload"], record["target"])
        missing = [name for name in recipe.requires if name not in tables]
        if missing:
            raise ValidationError(
                f"figure {spec.name!r}: analysis {item.analysis!r} 的 recipe "
                f"{item.recipe!r} 缺表 {missing}；请检查该 analysis 的 derive 配置"
            )
        ctx = make_plot_context(
            record["payload"],
            lang=lang,
            dpi=dpi,
            annotate=annotate,
            plot=item.plot,
        )
        built = list(recipe.build(ctx, dict(tables)) or [])
        if len(built) != 1:
            raise ValidationError(
                f"figure {spec.name!r}: analysis {item.analysis!r} 的 recipe "
                f"{item.recipe!r} 必须返回恰好一个 Panel，实际 {len(built)} 个"
            )
        panel = built[0]
        _panel_settings(panel, item.plot, lang)
        panels.append(panel)
        table_payload = record["payload"]["tables"]
        sources.append(
            {
                "analysis": item.analysis,
                "recipe": item.recipe,
                "plot": json_safe(dict(item.plot)),
                "plot_json": record.get(
                    "plot_json_path",
                    (Path("..") / item.analysis / "plot.json").as_posix(),
                ),
                "plot_json_sha256": sha256(
                    record["target"] / "plot.json"
                ),
                "tables": [
                    {
                        "name": name,
                        "path": table_payload[name]["path"],
                        "sha256": table_payload[name]["sha256"],
                    }
                    for name in recipe.requires
                ],
            }
        )
    return panels, sources


def render_composite_figure(
    spec,
    records: Mapping[str, Any],
    outdir: Path,
    *,
    lang: str,
    dpi: int,
    annotate: bool,
    fmt: str = "png",
) -> dict[str, Any]:
    """渲染一个跨分析 figure；只读 records 中的表，不读轨迹。"""
    panels, sources = _panels_for(
        spec, records, lang=lang, dpi=dpi, annotate=annotate
    )
    title = (
        plotutil.resolve_text(spec.plot["title"], lang)
        if spec.plot.get("title") is not None
        else None
    )
    rc = dict(spec.plot.get("rc") or {})
    if spec.plot.get("palette"):
        rc["axes.prop_cycle"] = cycler(color=list(spec.plot["palette"]))
    target = outdir / "figures" / f"{spec.name}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with matplotlib.rc_context(rc):
            fig = Figure(panels, ncols=spec.ncols, title=title).build()
            chart.save(fig, target, dpi)
    except Exception as exc:
        raise MdanalError(f"跨分析图 {spec.name!r} 绘制失败：{exc}") from exc
    payload = {
        "schema_version": 1,
        "kind": "composite_figure",
        "name": spec.name,
        "layout": {"ncols": spec.ncols},
        "plot": json_safe(dict(spec.plot)),
        "panels": sources,
        "figure": {
            "path": target.relative_to(outdir).as_posix(),
            "sha256": sha256(target),
        },
        "status": "ok",
    }
    snapshot = outdir / "figures" / f"{spec.name}.json"
    snapshot.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def render_composites(
    specs: Sequence[Any],
    records: Mapping[str, Any],
    outdir: Path,
    *,
    lang: str,
    dpi: int,
    annotate: bool,
    fmt: str = "png",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """逐个渲染并隔离失败；返回 (成功记录, 错误记录)。"""
    rendered: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for spec in specs:
        try:
            rendered.append(
                render_composite_figure(
                    spec,
                    records,
                    outdir,
                    lang=lang,
                    dpi=dpi,
                    annotate=annotate,
                    fmt=fmt,
                )
            )
        except Exception as exc:
            errors.append({"directory": f"figures/{spec.name}", "error": str(exc)})
    return rendered, errors


def spec_from_snapshot(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    """把 figures/<name>.json 读回 CrossFigureSpec 列表。"""
    from ..config.cross_figures import CrossFigureSpec, CrossPanelSpec

    if payload.get("kind") != "composite_figure":
        raise ValidationError("不是 composite figure 快照")
    name = payload.get("name")
    panels_raw = payload.get("panels")
    if not isinstance(name, str) or not name or not isinstance(panels_raw, list):
        raise ValidationError("composite figure 快照缺少 name/panels")
    panels = []
    for entry in panels_raw:
        if not isinstance(entry, Mapping):
            raise ValidationError("composite figure 快照的 panel 必须是映射")
        analysis = entry.get("analysis")
        recipe = entry.get("recipe")
        if not isinstance(analysis, str) or not isinstance(recipe, str):
            raise ValidationError("composite figure 快照的 panel 缺少 analysis/recipe")
        panels.append(
            CrossPanelSpec(
                analysis=analysis,
                recipe=recipe,
                plot=dict(entry.get("plot") or {}),
            )
        )
    layout = payload.get("layout") or {}
    ncols = layout.get("ncols", 3)
    return (
        CrossFigureSpec(
            name=name,
            panels=tuple(panels),
            ncols=int(ncols),
            plot=dict(payload.get("plot") or {}),
        ),
    )
