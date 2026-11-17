"""均方位移。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.msd import EinsteinMSD

from ..plot import annotations, chart, plotutil
from ..plot.panels import Panel, compose_panels
from ..plot.specs import Curve, PanelRequest, Series


SLOTS = ("group",)

PARAMS = {
    "msd_type": {
        "type": str,
        "default": "xyz",
        "choices": ("xyz", "xy", "xz", "yz", "x", "y", "z"),
        "help": "MSD 的维度组合",
    },
    "fft": {
        "type": bool,
        "default": True,
        "help": "用 FFT 加速",
    },
}

LABELS = {
    "zh": {
        "title": "均方位移",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
    },
    "en": {
        "title": "Mean squared displacement",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
    },
}

COORDINATES = "continuous"


COLUMN_LABELS = {
    "zh": {"dt_ps": r"$\Delta t$ (ps)", "msd_A2": "MSD (Å$^{2}$)"},
    "en": {"dt_ps": r"$\Delta t$ (ps)", "msd_A2": "MSD (Å$^{2}$)"},
}

COMPARE = {
    "table": "msd",
    "x": "dt_ps",
    "y": ["msd_A2"],
    "box_axis": False,
}


GEOMETRY = {"cell": "any", "periodicity": "any"}


def run(ctx) -> dict[str, pd.DataFrame]:
    analysis = EinsteinMSD(
        ctx.groups["group"].atoms,
        select="all",
        msd_type=str(ctx.params["msd_type"]),
        fft=bool(ctx.params["fft"]),
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    # 单位：timeseries 为 Å²；delta_t_values 跟随轨迹时间，这里是 ps
    lag = np.asarray(analysis.results.delta_t_values, dtype=float)
    msd = np.asarray(analysis.results.timeseries, dtype=float)
    # delta_t_values 已按轨迹时间单位（ps）给出
    table = pd.DataFrame({"dt_ps": lag, "msd_A2": msd})
    return {"msd": table}


def build_series(ctx, tables) -> list[Series]:
    table = tables["msd"]
    curve = Curve(
        x=table["dt_ps"].to_numpy(dtype=float),
        y=table["msd_A2"].to_numpy(dtype=float),
        label=ctx.label("y"),
    )
    return [Series(name="msd_A2", curves=[curve], label=ctx.label("y"))]


def panel_request(ctx, tables) -> PanelRequest:
    return PanelRequest(
        recipe="msd",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False, "marker": "o", "markersize": 2},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = len(curves) > 1
        marker = request.options.get("marker")
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
                    marker=marker,
                    ms=request.options.get("markersize"),
                    label=curve.label if show_legend else None,
                )
        if show_legend:
            chart.legend(ax)
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="msd",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label("x"),
        ylabel=request.ylabel or ctx.label("y"),
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )


def figures(ctx, tables):
    request = panel_request(ctx, tables)
    panel = render_panel(ctx, request)
    chart.apply_style()
    fig = compose_panels([panel], ncols=1)
    return [("msd", fig)]
