"""产品构建所需的 PlotContext 与 Panel 级呈现覆盖。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
import yaml
from cycler import cycler

from ..plot import plotutil
from ..plot.context import PlotContext

PROGRAM_DIR = Path(__file__).resolve().parent.parent
LABELS_PATH = PROGRAM_DIR / "config" / "labels.yaml"
PANEL_SIZES = {"single": (3.5, 2.6), "wide": (7.0, 3.2), "map": (4.2, 3.0)}
_COMMON: dict[str, dict[str, str]] | None = None


def common_labels() -> dict[str, dict[str, str]]:
    global _COMMON
    if _COMMON is None:
        data = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8")) or {}
        merged: dict[str, dict[str, str]] = {}
        for section in data.values():
            if not isinstance(section, Mapping):
                continue
            for lang, table in section.items():
                if isinstance(table, Mapping):
                    merged.setdefault(str(lang), {}).update(
                        {str(key): str(value) for key, value in table.items()}
                    )
        _COMMON = merged
    return _COMMON


def make_context(
    pack,
    compute_ctx,
    plot: Mapping[str, Any],
    *,
    lang: str,
    dpi: int,
    annotate: bool = False,
) -> PlotContext:
    common = common_labels().get(lang, {})
    labels = plotutil.Labels(pack.labels.get(lang, {}), common)
    settings = dict(plot or {})
    windows = {
        str(axis): (float(bounds[0]), float(bounds[1]))
        for axis, bounds in (settings.get("window") or {}).items()
    }
    size = settings.get("size")
    shift = getattr(compute_ctx, "shift", None)
    if shift is None:
        shift = compute_ctx.system.view.shift
    return PlotContext(
        params=dict(compute_ctx.params),
        meta={},
        extras=dict(compute_ctx.extras),
        start=int(compute_ctx.start),
        stop=int(compute_ctx.stop),
        frame_dt_ps=float(compute_ctx.frame_dt_ps),
        selection_frame=int(compute_ctx.selection_frame),
        shift=tuple(shift),
        lang=lang,
        dpi=dpi,
        annotate=annotate,
        annotations=(),
        labels=labels,
        figure_sizes=PANEL_SIZES,
        windows=windows,
        size_override=(float(size[0]), float(size[1])) if size else None,
        plot=settings,
    )


def select_style(items: Sequence[Any]) -> Mapping[str, Any]:
    """整图共用 palette/rc：取第一个显式设置的 Panel，否则第一个 Panel。"""
    for item in items:
        plot = getattr(item, "plot", None)
        if plot and (plot.get("palette") or plot.get("rc")):
            return plot
    if items:
        return getattr(items[0], "plot", {}) or {}
    return {}


@contextmanager
def plot_style(plot: Mapping[str, Any]):
    """应用 palette/rc；必须在 chart.apply_style() 之后进入。"""
    from ..plot import chart

    chart.apply_style()
    rc = dict(plot.get("rc") or {})
    palette = plot.get("palette")
    if palette:
        rc["axes.prop_cycle"] = cycler(color=list(palette))
    with matplotlib.rc_context(rc):
        yield


def apply_panel_plot(panel, plot: Mapping[str, Any], lang: str) -> None:
    for key in ("title", "xlabel", "ylabel"):
        if plot.get(key) is not None:
            setattr(panel, key, plotutil.resolve_text(plot[key], lang))
    for key in ("xlim", "ylim"):
        if plot.get(key) is not None:
            bounds = plot[key]
            setattr(panel, key, (float(bounds[0]), float(bounds[1])))
