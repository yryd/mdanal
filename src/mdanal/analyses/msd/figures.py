"""MSD 的多种图 recipe。"""

from __future__ import annotations

import numpy as np

from ...plot import annotations, chart
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series
from .contract import LABELS


def _time(table):
    """返回表内的物理时间（ns）；当前表只有这一种时间单位。"""
    if "dt_ns" not in table.columns:
        raise ValueError("MSD 表缺少 dt_ns 时间列")
    return table["dt_ns"].to_numpy(dtype=float)


def build_series(ctx, tables) -> list[Series]:
    table = tables["msd"]
    curve = Curve(
        x=_time(table),
        y=table["msd_A2"].to_numpy(dtype=float),
        label=ctx.label("y"),
    )
    return [Series(name="msd_A2", curves=[curve], label=ctx.label("y"))]


def panel_request(ctx, tables) -> PanelRequest:
    table = tables["msd"]
    return PanelRequest(
        recipe="msd",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = bool(request.options.get("legend")) or len(curves) > 1
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
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


def panels_raw(ctx, tables):
    return [render_panel(ctx, panel_request(ctx, tables))]



def _draw_fit(ax, ctx, tables):
    raw = tables["msd"]
    fit = tables["msd_fit"]
    summary = tables["msd_fit_summary"].iloc[0]
    t = _time(raw)
    chart.line(ax, t, raw["msd_A2"], label=ctx.label("y"))
    chart.line(
        ax,
        _time(fit),
        fit["fit_msd_A2"].to_numpy(dtype=float),
        color=chart.COLORS["secondary"],
        ls="--",
        label=ctx.label("fit"),
    )
    ax.axvline(
        float(summary["fit_start_ns"]), color=chart.COLORS["guide"], ls=":"
    )
    ax.axvline(
        float(summary["fit_end_ns"]), color=chart.COLORS["guide"], ls=":"
    )
    ax.text(
        0.03,
        0.95,
        f"{ctx.label('d')} = {float(summary['D_m2_per_s']) / 1e-9:.2f} "
        r"$\times 10^{-9}$ m$^2$ s$^{-1}$",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.0, fontweight=chart.ANNOTATION_WEIGHT,
    )
    chart.legend(ax, loc="upper right")
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())


def panels_fit(ctx, tables):
    table = tables["msd"]
    panel = Panel(
        name="msd-fit",
        draw=lambda ax: _draw_fit(ax, ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )
    return [panel]


def panels_rdc(ctx, tables):
    table = tables["msd_rdc"]
    t = _time(table)
    y = table["rdc_A2_per_ps"].to_numpy(dtype=float)

    def draw(ax):
        chart.line(ax, t, y, label=ctx.label("rdc"))
        if "msd_fit_summary" in tables:
            d = float(tables["msd_fit_summary"].iloc[0]["D_A2_per_ps"])
            ax.axhline(d, color=chart.COLORS["secondary"], ls="--", label=ctx.label("d"))
            s = tables["msd_fit_summary"].iloc[0]
            ax.axvspan(
                float(s["fit_start_ns"]),
                float(s["fit_end_ns"]),
                color=chart.COLORS["primary"],
                alpha=0.10,
                lw=0,
            )
        chart.legend(ax, loc="upper left")
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())

    return [
        Panel(
            name="msd-rdc",
            draw=draw,
            title=ctx.label("rdc"),
            xlabel=ctx.label("x"),
            ylabel=ctx.label("rdc_y"),
            aspect="auto",
            xlim=ctx.window("x"),
            ylim=ctx.window("y"),
            panel_size=ctx.size("single"),
        )
    ]
