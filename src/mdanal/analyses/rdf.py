"""径向分布函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.rdf import InterRDF

from .. import plotutil
from ..errors import ValidationError


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

    analysis = InterRDF(group_a.atoms, group_b.atoms, nbins=nbins, range=(rmin, rmax))
    analysis.run(start=ctx.start, stop=ctx.stop)

    edges = np.asarray(analysis.results.edges, dtype=float)
    centers = 0.5 * (edges[1:] + edges[:-1])
    rdf = np.asarray(analysis.results.rdf, dtype=float)
    return {"rdf": pd.DataFrame({"r (Å)": centers, "g(r)": rdf})}


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    cols = list(table.columns)
    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(table[cols[0]], table[cols[1]], lw=1.2)
    ax.axhline(1.0, ls="--", lw=0.6, color="0.6")
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]
