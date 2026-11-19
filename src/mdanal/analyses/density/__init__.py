"""density 图包：3D 数密度投影 + 线密度。"""

from __future__ import annotations

from dataclasses import replace

from ...figure.curves import compare_curves as _compare_curves
from ...figure.model import PanelProduct
from . import _line
from ...plot.plotutil import Labels
from ...figure.plotting import common_labels
from ._impl import *  # noqa: F401,F403
from ._impl import (
    LABELS,
    PARAMS as _DENSITY_PARAMS,
    SLOTS,
    panels as _density_panels,
    run as _density_run,
)

# 合并原 lineardensity 的参数；line 产品用 binsize。
PARAMS = {
    **_DENSITY_PARAMS,
    "binsize": _line.PARAMS["binsize"],
}

LINE_LABELS = _line.LABELS


def compute(ctx):
    """一次 compute：3D 网格的三个投影 + 三个线密度表。"""
    density_params = dict(ctx.params)
    density_params.update(
        {
            "directions": ["xy", "xz", "yz"],
            "panels": [],
            "sum_axis": str(ctx.params.get("sum_axis") or "z"),
            "delta": float(ctx.params.get("delta", 1.0)),
        }
    )
    density_ctx = replace(ctx, params=density_params, extras={})
    tables = dict(_density_run(density_ctx))
    ctx.extras.update(density_ctx.extras)
    line_params = {
        **dict(ctx.params),
        "binsize": float(ctx.params.get("binsize", 0.5)),
    }
    line_ctx = replace(ctx, params=line_params)
    tables.update(_line.run(line_ctx))
    return tables


def _one_panel(panels, label: str):
    if len(panels) != 1:
        raise ValueError(f"{label} 必须返回一个 Panel，实际 {len(panels)} 个")
    return panels[0]


def _build_density_2d(ctx, source):
    plane = str((ctx.plot or {}).get("plane") or "xy").lower()
    infos = list((ctx.extras or {}).get("density_panels") or [])
    match = next((info for info in infos if info.get("direction") == plane), None)
    if match is None:
        raise ValueError(
            f"density-2d 没有投影 {plane!r}；可用 "
            f"{sorted({info.get('direction') for info in infos})}"
        )
    table = source.tables[match["table"]]
    panel_ctx = replace(
        ctx,
        params={**dict(ctx.params), "vmin": ctx.params.get("vmin", "auto"),
                "vmax": ctx.params.get("vmax", "auto")},
        extras={**dict(ctx.extras), "density_panels": [match]},
    )
    return _one_panel(
        _density_panels(panel_ctx, {match["table"]: table}), "density-2d"
    )


def _build_density_line(ctx, source):
    axis = str((ctx.plot or {}).get("axis") or "z").lower()
    if axis not in ("x", "y", "z"):
        raise ValueError(f"density-line 的 axis 只能是 x/y/z，收到 {axis!r}")
    line_ctx = replace(
        ctx,
        params={**dict(ctx.params), "dim": axis},
        labels=Labels(LINE_LABELS.get(ctx.lang, {}), common_labels().get(ctx.lang, {})),
    )
    return _one_panel(_line.panels(line_ctx, source.tables), "density-line")


def _compare_line(ctx, sources):
    axis = str((ctx.plot or {}).get("axis") or "z").lower()
    local = replace(ctx, params={**dict(ctx.params), "dim": axis})
    return _compare_curves(local, sources, _line.panel_request, _line.render_panel)


PRODUCTS = {
    "density-2d": PanelProduct(
        id="density-2d",
        kind="field",
        requires=("density_xy", "density_xz", "density_yz"),
        build=_build_density_2d,
        default=True,
        help="三维数密度沿一个方向投影；plot.plane 选择 xy/xz/yz",
    ),
    "density-line": PanelProduct(
        id="density-line",
        kind="curve",
        requires=("lineardensity_x", "lineardensity_y", "lineardensity_z"),
        build=_build_density_line,
        compare=_compare_line,
        help="质量/电荷线密度；plot.axis 选择 x/y/z",
    ),
}


__all__ = [
    "SLOTS",
    "PARAMS",
    "LABELS",
    "PRODUCTS",
    "compute",
    "COORDINATES",
    "GEOMETRY",
]
