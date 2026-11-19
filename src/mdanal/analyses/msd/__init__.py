"""MSD 插件包：质心 MSD、派生拟合/RDC、多个图 recipe。"""

from __future__ import annotations

from .contract import (
    COLUMN_LABELS,
    COORDINATES,
    LABELS,
    PARAMS,
    SLOTS,
)
from .compute import _com_trajectory, _msd_from_com, run as _compute_run
from .derive import run as _derive_run, validate_spec as validate_derive_spec
from .figures import (
    build_series,
    panel_request,
    panels_fit,
    panels_raw,
    panels_rdc,
    render_panel,
)
from ...figure.curves import compare_curves as _compare_curves
from ...figure.model import PanelProduct


def derive_tables(ctx, tables, spec):
    """从已有 MSD 基础表重算派生表；不读轨迹。"""
    validate_derive_spec(dict(spec))
    return _derive_run(ctx, dict(tables), dict(spec))


def _one_panel(builder):
    def build(ctx, source):
        panels = list(builder(ctx, dict(source.tables)) or [])
        if len(panels) != 1:
            raise ValueError(f"MSD 产品必须返回一个 Panel，实际 {len(panels)} 个")
        return panels[0]

    return build


def compute(ctx):
    """新 figure-first compute：只算基础 MSD 表。"""
    return _compute_run(ctx)


validate_derive = validate_derive_spec


def derive(ctx, tables, spec):
    """新 figure-first derive：由 product 的 derive 配置调用。"""
    return derive_tables(ctx, tables, spec)


def _compare_raw(ctx, sources):
    return _compare_curves(ctx, sources, panel_request, render_panel)


PRODUCTS = {
    "msd-raw": PanelProduct(
        id="msd-raw",
        kind="curve",
        requires=("msd",),
        build=_one_panel(panels_raw),
        compare=_compare_raw,
        default=True,
        help="MSD 原始曲线",
    ),
    "msd-fit": PanelProduct(
        id="msd-fit",
        kind="curve",
        requires=("msd", "msd_fit", "msd_fit_summary"),
        build=_one_panel(panels_fit),
        help="MSD + 拟合线 + D",
        requires_derive=("fit",),
    ),
    "msd-rdc": PanelProduct(
        id="msd-rdc",
        kind="curve",
        requires=("msd_rdc",),
        build=_one_panel(panels_rdc),
        help="运行扩散系数 RDC",
        requires_derive=("rdc",),
    ),
}


__all__ = [
    "SLOTS", "PARAMS", "LABELS", "COLUMN_LABELS",
    "COORDINATES", "PRODUCTS",
    "compute", "derive", "derive_tables",
    "validate_derive_spec", "build_series",
    "panel_request", "render_panel", "panels_raw", "panels_fit", "panels_rdc",
]
