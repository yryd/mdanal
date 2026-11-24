"""contact 图包：分子级接触数与配位数。"""

from __future__ import annotations

from ...figure.curves import compare_curves as _compare_curves
from ...figure.model import PanelProduct
from ._impl import (
    COORDINATES,
    GEOMETRY,
    KERNEL_PBC,
    LABELS,
    PARAMS,
    SLOTS,
    panel_request,
    render_panel,
    run as _run,
)


def compute(ctx):
    return _run(ctx)


def _build(ctx, source, metric: str):
    return render_panel(ctx, panel_request(ctx, source.tables, metric))


def _request(ctx, tables, metric: str):
    return panel_request(ctx, tables, metric)


def _compare(ctx, sources, metric: str):
    return _compare_curves(
        ctx,
        sources,
        lambda local, tables: _request(local, tables, metric),
        render_panel,
    )


def _build_count(ctx, source):
    return _build(ctx, source, "count")


def _build_coordination(ctx, source):
    return _build(ctx, source, "coordination")


def _compare_count(ctx, sources):
    return _compare(ctx, sources, "count")


def _compare_coordination(ctx, sources):
    return _compare(ctx, sources, "coordination")


def _request_count(ctx, source):
    return _request(ctx, source.tables, "count")


def _request_coordination(ctx, source):
    return _request(ctx, source.tables, "coordination")


PRODUCTS = {
    "contact-count": PanelProduct(
        id="contact-count",
        kind="curve",
        requires=("contact",),
        build=_build_count,
        compare=_compare_count,
        curve_request=_request_count,
        default=True,
        help="每帧分子对接触数",
    ),
    "contact-coordination": PanelProduct(
        id="contact-coordination",
        kind="curve",
        requires=("contact",),
        build=_build_coordination,
        compare=_compare_coordination,
        curve_request=_request_coordination,
        help="每个 first 组分子的平均接触数",
    ),
}
