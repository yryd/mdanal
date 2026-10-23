"""线密度：沿单轴的质量密度与电荷密度。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.lineardensity import LinearDensity

from .. import plotutil

AXES = ("x", "y", "z")


def run(ctx) -> dict[str, pd.DataFrame]:
    binsize = float(ctx.params["binsize"])
    analysis = LinearDensity(ctx.groups["group"].atoms, binsize=binsize, grouping="atoms")
    analysis.run(start=ctx.start, stop=ctx.stop)

    tables: dict[str, pd.DataFrame] = {}
    for axis in AXES:
        result = analysis.results[axis]
        edges = np.asarray(result["hist_bin_edges"], dtype=float)
        length = float(ctx.universe.dimensions[AXES.index(axis)])
        # LinearDensity 对三个轴统一用 max(dimensions) 作上界，需按盒长截断；
        # 末尾不足一个 bin 的薄层整格丢弃，否则该格的密度会因体积按满格计而偏低
        n_bins = int(np.searchsorted(edges, length, side="right") - 1)
        centers = 0.5 * (edges[1:] + edges[:-1])[:n_bins]
        centers = centers + ctx.system.view.lower[AXES.index(axis)]
        tables[f"lineardensity_{axis}"] = pd.DataFrame(
            {
                f"{axis} (Å)": centers,
                "质量密度 (g/cm^3)": np.asarray(result["mass_density"])[:n_bins],
                "电荷密度 (e/Å^3)": np.asarray(result["charge_density"])[:n_bins],
            }
        )
    return tables


def figures(ctx, tables):
    axis = str(ctx.params["dim"]).lower()
    name = f"lineardensity_{axis}"
    table = tables[name]
    cols = list(table.columns)

    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(table[cols[0]], table[cols[1]], lw=1.2)
    ax.set_xlabel(ctx.label(f"axis_{axis}"))
    ax.set_ylabel(ctx.label("mass"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(axis))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]
