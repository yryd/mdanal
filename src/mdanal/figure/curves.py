"""曲线产品的通用 compare 助手：多个 PanelSource → 一个 Panel。"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Sequence

from ..plot.specs import PanelRequest



def _source_context(ctx, source):
    extras = dict((source.meta or {}).get("extras") or ctx.extras)
    return replace(
        ctx,
        params={**dict(ctx.params), **dict(source.params or {})},
        extras=extras,
        start=int(source.start),
        stop=int(source.stop),
        selection_frame=int(source.selection_frame),
        shift=tuple(source.shift),
    )


def compare_curves(
    ctx,
    sources: Sequence,
    panel_request: Callable,
    render_panel: Callable,
):
    first_request = panel_request(_source_context(ctx, sources[0]), sources[0].tables)
    merged = []
    for source_index, source in enumerate(sources):
        request = panel_request(_source_context(ctx, source), source.tables)
        for series in request.series:
            curves = []
            for curve in series.curves:
                label = source.label
                if curve.label and len(series.curves) > 1:
                    label = f"{source.label} · {curve.label}"
                linestyle = curve.linestyle
                if len(sources) > 1 and source_index > 0 and curve.linestyle == "-":
                    linestyle = "--" if source_index == 1 else ":"
                curves.append(
                    replace(
                        curve,
                        label=label,
                        source=source.source,
                        linestyle=linestyle,
                    )
                )
            merged.append(replace(series, curves=curves))
    request = PanelRequest(
        recipe=f"{first_request.recipe}-compare",
        series=merged,
        title=first_request.title,
        xlabel=first_request.xlabel,
        ylabel=first_request.ylabel,
        options={**dict(first_request.options), "legend": True},
        metadata={"compare": True},
    )
    return render_panel(ctx, request)
