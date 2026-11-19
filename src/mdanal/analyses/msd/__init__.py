"""MSD 插件包：质心 MSD、派生拟合/RDC、多个图 recipe。"""

from __future__ import annotations

from .contract import (
    COLUMN_LABELS,
    COMPARE,
    COORDINATES,
    GEOMETRY,
    LABELS,
    PARAMS,
    SLOTS,
)
from .compute import _com_trajectory, _msd_from_com, run as _compute_run
from .derive import run as _derive_run
from .figures import (
    FIGURES,
    build_series,
    figure_name,
    panel_request,
    panels_raw as panels,
    render_panel,
)


def run(ctx):
    tables = _compute_run(ctx)
    plan_item = getattr(ctx, "plan_item", None)
    derive = dict(getattr(plan_item, "derive", {}) or {})
    if derive:
        tables.update(_derive_run(ctx, tables, derive))
    return tables


__all__ = [
    "SLOTS", "PARAMS", "LABELS", "COLUMN_LABELS", "COMPARE",
    "COORDINATES", "GEOMETRY", "FIGURES", "run", "build_series",
    "panel_request", "render_panel", "panels", "figure_name",
]
