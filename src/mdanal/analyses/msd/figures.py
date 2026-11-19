"""MSD 的多种图 recipe。"""

from __future__ import annotations

import numpy as np

from ...plot import annotations, chart
from ...plot.panels import Panel
from ...plot.recipes import FigureRecipe
from ...plot.specs import Curve, PanelRequest, Series
from .contract import LABELS


def _time(table):
    """返回表内自带的物理时间；旧表是 ps，新表是 ns。

    旧快照的坐标标签、窗口和标注都以 ps 写入，不能在重绘时只把数组除以
    1000，否则横轴数值与标签会差 1000 倍。
    """
    if "dt_ns" in table.columns:
        return table["dt_ns"].to_numpy(dtype=float)
    if "dt_ps" in table.columns:
        return table["dt_ps"].to_numpy(dtype=float)
    raise ValueError("MSD 表缺少 dt_ns 或 dt_ps 时间列")


def _time_label(ctx, table):
    """保持标签与数据同单位；旧快照的 ps 标签原样保留。"""
    label = ctx.label("x")
    if "dt_ps" in table.columns and "ps" not in label:
        return label.replace("ns", "ps")
    if "dt_ns" in table.columns and "ns" not in label:
        return label.replace("ps", "ns")
    return label


def _summary_time(summary, stem: str, table) -> float:
    """优先按表的时间单位取拟合窗口；兼容旧 summary 的 _ps/_ns 列。"""
    unit = "ps" if "dt_ps" in table.columns else "ns"
    for key in (f"{stem}_{unit}", f"{stem}_ps", f"{stem}_ns"):
        if key in summary:
            value = float(summary[key])
            if key.endswith("_ns") and unit == "ps":
                return value * 1000.0
            if key.endswith("_ps") and unit == "ns":
                return value / 1000.0
            return value
    raise ValueError(f"MSD 拟合摘要缺少 {stem}_ps/{stem}_ns")


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
        xlabel=_time_label(ctx, table),
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


def figure_name(ctx, tables) -> str:
    return "msd"


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
        _summary_time(summary, "fit_start", raw), color=chart.COLORS["guide"], ls=":"
    )
    ax.axvline(
        _summary_time(summary, "fit_end", raw), color=chart.COLORS["guide"], ls=":"
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
        xlabel=_time_label(ctx, table),
        ylabel=ctx.label("y"),
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )
    return [panel]


def panels_rdc(ctx, tables):
    table = tables["msd_rdc"]
    raw = tables.get("msd", table)
    t = _time(table)
    y = table["rdc_A2_per_ps"].to_numpy(dtype=float)

    def draw(ax):
        chart.line(ax, t, y, label=ctx.label("rdc"))
        if "msd_fit_summary" in tables:
            d = float(tables["msd_fit_summary"].iloc[0]["D_A2_per_ps"])
            ax.axhline(d, color=chart.COLORS["secondary"], ls="--", label=ctx.label("d"))
            s = tables["msd_fit_summary"].iloc[0]
            ax.axvspan(
                _summary_time(s, "fit_start", raw),
                _summary_time(s, "fit_end", raw),
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
            xlabel=_time_label(ctx, table),
            ylabel=ctx.label("rdc_y"),
            aspect="auto",
            xlim=ctx.window("x"),
            ylim=ctx.window("y"),
            panel_size=ctx.size("single"),
        )
    ]


FIGURES = {
    "raw": FigureRecipe(
        name="raw", build=panels_raw, requires=("msd",), filename="msd"
    ),
    "fit": FigureRecipe(
        name="fit",
        build=panels_fit,
        requires=("msd", "msd_fit", "msd_fit_summary"),
        filename="msd-fit",
    ),
    "rdc": FigureRecipe(
        name="rdc",
        build=panels_rdc,
        requires=("msd_rdc",),
        filename="msd-rdc",
    ),
}
