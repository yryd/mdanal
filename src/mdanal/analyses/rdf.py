"""径向分布函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.rdf import InterRDF

from ..plot import annotations, chart, plotutil
from ..plot.panels import Panel
from ..plot.specs import Curve, PanelRequest, Series
from ..errors import ValidationError


SLOTS = ("a", "b")

PARAMS = {
    "range": {
        "type": list,
        "default": [0.5, 6.0],
        "unit": "Å",
        "help": "r 的范围 [最小值, 最大值]",
    },
    "nbins": {
        "type": int,
        "default": 60,
        "min": 2,
        "help": "直方图 bin 数",
    },
}

LABELS = {
    "zh": {
        "title": "径向分布函数",
        "x": "$r$ (Å)",
        "y": "$g(r)$",
    },
    "en": {
        "title": "Radial distribution function",
        "x": "$r$ (Å)",
        "y": "$g(r)$",
    },
}


COLUMN_LABELS = {
    "zh": {"r_angstrom": "$r$ (Å)", "g_r": "$g(r)$"},
    "en": {"r_angstrom": "$r$ (Å)", "g_r": "$g(r)$"},
}

COMPARE = {
    "table": "rdf",
    "x": "r_angstrom",
    "y": ["g_r"],
    "box_axis": False,
}


COORDINATES = "in_box"

GEOMETRY = {"cell": "orthorhombic", "periodicity": "full"}


def run(ctx) -> dict[str, pd.DataFrame]:
    group_a = ctx.groups["a"]
    group_b = ctx.groups["b"]
    rmin, rmax = (float(v) for v in ctx.params["range"])
    nbins = int(ctx.params["nbins"])

    dimensions = ctx.universe.dimensions
    if dimensions is not None and not np.allclose(
        np.asarray(dimensions[3:]), 90.0, atol=1e-3
    ):
        ctx.warn(
            f"检测到三斜盒角 {np.asarray(dimensions[3:]).tolist()}；"
            "RDF 的球壳范围/归一化尚未验证，结果仅供定性参考。"
        )
    window = getattr(ctx, "geometry_window", None)
    if window is not None:
        limit = 0.5 * float(window.min_length)
        source = f"分析窗口最短盒长 {window.min_length:g} Å 的一半"
    else:
        dimensions = ctx.universe.dimensions
        limit = 0.5 * float(min(dimensions[:3])) if dimensions is not None else 0.0
        source = "当前帧最短盒长的一半"
    if limit and rmax > limit:
        ctx.warn(
            f"range 上限 {rmax:g} Å 超过{source}（{limit:g} Å）；"
            "距离超过该范围时球壳归一化不适用，结果仅供定性参考。"
        )

    # 单位：range 与 edges 为 Å；g(r) 无量纲
    # (1, 1) 排除“同一原子与自身”的配对；两组互不重叠时无影响，
    # 同组自 RDF 或部分重叠组必须排除，否则 0 距离会污染第一个 bin。
    analysis = InterRDF(
        group_a.atoms,
        group_b.atoms,
        nbins=nbins,
        range=(rmin, rmax),
        exclusion_block=(1, 1),
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    edges = np.asarray(analysis.results.edges, dtype=float)
    centers = 0.5 * (edges[1:] + edges[:-1])
    rdf = np.asarray(analysis.results.rdf, dtype=float)
    return {"rdf": pd.DataFrame({"r_angstrom": centers, "g_r": rdf})}


def build_series(ctx, tables) -> list[Series]:
    table = tables["rdf"]
    curve = Curve(
        x=table["r_angstrom"].to_numpy(dtype=float),
        y=table["g_r"].to_numpy(dtype=float),
        label=ctx.label("y"),
    )
    return [Series(name="g_r", curves=[curve], label=ctx.label("y"))]


def panel_request(ctx, tables) -> PanelRequest:
    return PanelRequest(
        recipe="rdf",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = len(curves) > 1
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
        chart.refline(ax, 1.0, ls="--", lw=0.6, color="0.6")
        if show_legend:
            chart.legend(ax)
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="rdf",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label("x"),
        ylabel=request.ylabel or ctx.label("y"),
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )


def panels(ctx, tables) -> list[Panel]:
    request = panel_request(ctx, tables)
    return [render_panel(ctx, request)]


def figure_name(ctx, tables) -> str:
    return "rdf"
