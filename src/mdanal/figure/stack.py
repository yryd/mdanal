"""平台级 stack 合成：多个 source 的单曲线 → 一个堆叠 Panel。"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from ..errors import ValidationError
from ..plot import annotations, chart, plotutil
from ..plot.panels import Panel
from ..plot.specs import PanelRequest
from .curves import _source_context


def _one_curve(request: PanelRequest, label: str):
    curves = [curve for series in request.series for curve in series.curves]
    if len(curves) != 1:
        raise ValidationError(
            f"stack 来源 {label!r} 必须恰好一条曲线；实际 {len(curves)} 条"
        )
    return curves[0]


def stack_curves(
    ctx,
    sources: Sequence,
    curve_request: Callable,
) -> Panel:
    """按 source 顺序堆叠；每条 source 只能提供一条曲线。"""
    requests: list[PanelRequest] = []
    curves = []
    labels = []
    x_ref = None
    for source in sources:
        request = curve_request(_source_context(ctx, source), source)
        curve = _one_curve(request, source.label)
        x = np.asarray(curve.x, dtype=float)
        if x_ref is None:
            x_ref = x
        elif not np.array_equal(x, x_ref):
            raise ValidationError(
                f"stack 来源 {source.label!r} 的 x 轴与第一条不一致；"
                "stack 不做插值或裁剪"
            )
        curves.append(np.asarray(curve.y, dtype=float))
        labels.append(source.label)
        requests.append(request)
    if len(curves) < 2:
        raise ValidationError("stack 至少需要两个来源")
    first = requests[0]
    palette = (getattr(ctx, "plot", {}) or {}).get("palette")
    colors = list(palette) if palette else list(chart.THEME_COLORS)
    total = bool((getattr(ctx, "plot", {}) or {}).get("stack_total", False))

    def draw(ax):
        chart.stack(
            ax,
            x_ref,
            curves,
            labels=labels,
            colors=colors,
            total=total,
        )
        chart.legend(ax, loc=plotutil.legend_loc(ctx))
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="stack",
        draw=draw,
        title=first.title,
        xlabel=first.xlabel,
        ylabel=first.ylabel,
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )
