"""流速剖面（MAICoS VelocityPlanar）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import plotutil


def run(ctx) -> dict[str, pd.DataFrame]:
    from maicos.modules.velocityplanar import VelocityPlanar

    analysis = VelocityPlanar(
        ctx.groups["group"].atoms,
        dim=int(ctx.params["dim"]),
        vdim=int(ctx.params["vdim"]),
        bin_width=float(ctx.params["bin_width"]),
        grouping=str(ctx.params["grouping"]),
        refgroup=ctx.groups["ref"].atoms,
        unwrap=True,
        pack=True,
        output=None,
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    table = pd.DataFrame(
        {
            "z (Å)": np.asarray(analysis.results.bin_pos, dtype=float),
            "vx (Å/ps)": np.asarray(analysis.results.profile, dtype=float),
            "误差 (Å/ps)": np.asarray(analysis.results.dprofile, dtype=float),
        }
    )
    return {"velocity": table}


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    z = table["z (Å)"].to_numpy()
    v = table["vx (Å/ps)"].to_numpy()
    err = table["误差 (Å/ps)"].to_numpy()
    valid = np.isfinite(v)

    # 没有样本的 bin 用 NaN 占位，让折线在该处断开而不是跨空档直连
    v_plot = np.where(valid, v, np.nan)
    err_plot = np.where(valid, err, np.nan)

    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(v_plot, z, lw=1.2)
    if np.isfinite(err_plot).any():
        ax.fill_betweenx(
            z,
            v_plot - err_plot,
            v_plot + err_plot,
            alpha=0.25,
            lw=0,
        )
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]
