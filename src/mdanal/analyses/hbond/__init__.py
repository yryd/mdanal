"""hbond 图包：一次 HBA，三个产品（count/type/lifetime）。"""

from __future__ import annotations

from dataclasses import replace

from ...figure.curves import compare_curves as _compare_curves
from ...figure.model import PanelProduct
from ...plot.plotutil import Labels
from ...figure.plotting import common_labels
from . import _lifetime
from . import _type
from ._impl import *  # noqa: F401,F403
from ._impl import LABELS, PARAMS as _COUNT_PARAMS, SLOTS, run as _count_run
from ._impl import panel_request as _count_request, panels as _count_panels, render_panel as _count_render
from ._lifetime import panel_request as _life_request, render_panel as _life_render

PARAMS = {**_COUNT_PARAMS, **_type.PARAMS, **_lifetime.PARAMS}
TYPE_LABELS = _type.LABELS
LIFETIME_LABELS = _lifetime.LABELS


def compute(ctx):
    """一次 HBA 结果供三个产品使用；type 需要 naming 才可计算。"""
    tables = dict(_count_run(ctx))
    if not ctx.system.naming.empty:
        tables.update(_type.run(ctx))
    tables.update(_lifetime.run(ctx))
    return tables


def _one(panels, product: str):
    if len(panels) != 1:
        raise ValueError(f"{product} 必须返回一个 Panel，实际 {len(panels)} 个")
    return panels[0]


def _build_count(ctx, source):
    return _one(_count_panels(ctx, source.tables), "hbond-count")


def _build_type(ctx, source):
    local = replace(ctx, labels=Labels(TYPE_LABELS.get(ctx.lang, {}), common_labels().get(ctx.lang, {})))
    if source.tables["hbond_type"].empty:
        return _type.render_panel(local, _type.panel_request(local, source.tables))
    return _one(_type.panels(local, source.tables), "hbond-type")


def _build_lifetime(ctx, source):
    local = replace(ctx, labels=Labels(LIFETIME_LABELS.get(ctx.lang, {}), common_labels().get(ctx.lang, {})))
    return _one(_lifetime.panels(local, source.tables), "hbond-lifetime")


def _compare_count(ctx, sources):
    return _compare_curves(ctx, sources, _count_request, _count_render)


def _compare_lifetime(ctx, sources):
    local = replace(ctx, labels=Labels(LIFETIME_LABELS.get(ctx.lang, {}), common_labels().get(ctx.lang, {})))
    return _compare_curves(local, sources, _life_request, _life_render)


PRODUCTS = {
    "hbond-count": PanelProduct(
        id="hbond-count",
        kind="curve",
        requires=("hbond_count",),
        build=_build_count,
        compare=_compare_count,
        default=True,
        help="每帧氢键数",
    ),
    "hbond-type": PanelProduct(
        id="hbond-type",
        kind="bars",
        requires=("hbond_type",),
        build=_build_type,
        help="按供体/受体类型统计；需要 naming",
    ),
    "hbond-lifetime": PanelProduct(
        id="hbond-lifetime",
        kind="curve",
        requires=("hbond_lifetime", "hbond_lifetime_summary"),
        build=_build_lifetime,
        compare=_compare_lifetime,
        help="连续/间歇寿命曲线",
    ),
}
