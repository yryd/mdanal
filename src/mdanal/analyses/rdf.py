"""径向分布函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.rdf import InterRDF

from ..plot import annotations, chart, plotutil
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


def run(ctx) -> dict[str, pd.DataFrame]:
    group_a = ctx.groups["a"]
    group_b = ctx.groups["b"]
    rmin, rmax = (float(v) for v in ctx.params["range"])
    nbins = int(ctx.params["nbins"])

    dimensions = ctx.universe.dimensions
    if dimensions is not None:
        limit = 0.5 * float(min(dimensions[:3]))
        if rmax > limit:
            raise ValidationError(
                f"range 上限 {rmax:g} Å 超过半盒长 {limit:g} Å；"
                "距离超过半盒长时无法配对，请缩小 range"
            )

    # 单位：range 与 edges 为 Å；g(r) 无量纲
    analysis = InterRDF(group_a.atoms, group_b.atoms, nbins=nbins, range=(rmin, rmax))
    analysis.run(start=ctx.start, stop=ctx.stop)

    edges = np.asarray(analysis.results.edges, dtype=float)
    centers = 0.5 * (edges[1:] + edges[:-1])
    rdf = np.asarray(analysis.results.rdf, dtype=float)
    return {"rdf": pd.DataFrame({"r_angstrom": centers, "g_r": rdf})}


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    cols = list(table.columns)
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, table[cols[0]], table[cols[1]], lw=1.2)
    chart.refline(ax, 1.0, ls="--", lw=0.6, color="0.6")
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    plotutil.limit(ax, "x", ctx.window("x"))
    plotutil.limit(ax, "y", ctx.window("y"))
    ax.set_title(ctx.label("title"))
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]
