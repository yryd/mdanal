"""MSD 插件包：质心 MSD、派生拟合/RDC、多个图 recipe。"""

from __future__ import annotations

from .contract import (
    COLUMN_LABELS,
    COMPARE,
    COORDINATES,
    DERIVE,
    GEOMETRY,
    LABELS,
    PARAMS,
    SLOTS,
)
from .compute import _com_trajectory, _msd_from_com, run as _compute_run
from .derive import run as _derive_run, validate_spec as validate_derive_spec
from .figures import (
    FIGURES,
    build_series,
    figure_name,
    panel_request,
    panels_raw as panels,
    render_panel,
)


def derive_tables(ctx, tables, spec):
    """从已有 MSD 基础表重算派生表；不读轨迹，供 run/离线 derive 共用。"""
    validate_derive_spec(dict(spec))
    return _derive_run(ctx, dict(tables), dict(spec))


def run(ctx):
    tables = _compute_run(ctx)
    plan_item = getattr(ctx, "plan_item", None)
    derive = dict(getattr(plan_item, "derive", {}) or {})
    if derive:
        tables.update(derive_tables(ctx, tables, derive))
    return tables


__all__ = [
    "SLOTS", "PARAMS", "LABELS", "COLUMN_LABELS", "COMPARE",
    "COORDINATES", "GEOMETRY", "DERIVE", "FIGURES", "run", "derive_tables",
    "validate_derive_spec", "build_series",
    "panel_request", "render_panel", "panels", "figure_name",
]
