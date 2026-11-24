"""rdf 图包。"""

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
    panels as _panels,
    render_panel,
    run as _run,
)


def compute(ctx):
    return _run(ctx)


def _build(ctx, source):
    panels = list(_panels(ctx, source.tables) or [])
    if len(panels) != 1:
        raise ValueError(f"rdf 必须返回一个 Panel，实际 {len(panels)} 个")
    return panels[0]


def _compare(ctx, sources):
    return _compare_curves(ctx, sources, panel_request, render_panel)


PRODUCTS = {
    "rdf": PanelProduct(
        id="rdf",
        kind="curve",
        requires=("rdf",),
        build=_build,
        compare=_compare,
        default=True,
        help="径向分布函数",
    )
}
