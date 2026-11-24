"""velocity 图包。"""

from __future__ import annotations

from ...figure.curves import compare_curves as _compare_curves
from ...figure.model import PanelProduct
from ...errors import ValidationError
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
        raise ValueError(f"velocity 必须返回一个 Panel，实际 {len(panels)} 个")
    return panels[0]


def _compare(ctx, sources):
    def signature(source):
        return (
            source.params.get("dim", PARAMS["dim"]["default"]),
            source.params.get("vdim", PARAMS["vdim"]["default"]),
        )

    first = signature(sources[0])
    for source in sources[1:]:
        if signature(source) != first:
            raise ValidationError(
                "velocity compare 要求所有来源的 dim/vdim 相同；"
                f"收到 {first!r} 与 {signature(source)!r}。"
                "不同分量请拆成多个 Panel。"
            )
    return _compare_curves(ctx, sources, panel_request, render_panel)


PRODUCTS = {
    "velocity": PanelProduct(
        id="velocity",
        kind="curve",
        requires=("velocity",),
        build=_build,
        compare=_compare,
        default=True,
        help="速度剖面",
    )
}
