"""流速剖面（MAICoS VelocityPlanar）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")


def run(ctx) -> dict[str, pd.DataFrame]:
    from maicos.modules.velocityplanar import VelocityPlanar

    dim = int(ctx.params["dim"])
    vdim = int(ctx.params["vdim"])
    if dim not in (0, 1, 2) or vdim not in (0, 1, 2):
        raise ValidationError(f"dim 与 vdim 只能取 0、1、2，收到 dim={dim}、vdim={vdim}")
    axis = AXES[dim]

    # 剖面坐标以参考组质心为零点；把该质心加回去即视图坐标
    ctx.universe.trajectory[ctx.selection_frame]
    lower = ctx.system.view.lower[dim]
    ref = float(ctx.groups["ref"].atoms.center_of_mass()[dim]) + lower
    ctx.extras["velocity_ref"] = ref

    analysis = VelocityPlanar(
        ctx.groups["group"].atoms,
        dim=dim,
        vdim=vdim,
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
            f"{axis} (Å)": np.asarray(analysis.results.bin_pos, dtype=float) + ref,
            f"v{AXES[vdim]} (Å/ps)": np.asarray(analysis.results.profile, dtype=float),
            "误差 (Å/ps)": np.asarray(analysis.results.dprofile, dtype=float),
        }
    )
    return {"velocity": table}


def meta(ctx, tables) -> dict:
    return {
        "axis": AXES[int(ctx.params["dim"])],
        "ref_com": ctx.extras.get("velocity_ref"),
        "ref_frame": ctx.selection_frame,
    }


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    axis = AXES[int(ctx.params["dim"])]
    z = table[f"{axis} (Å)"].to_numpy()
    v = table[f"v{AXES[int(ctx.params['vdim'])]} (Å/ps)"].to_numpy()

    # 没有样本的 bin 用 NaN 占位，让折线在该处断开而不是跨空档直连
    v_plot = np.where(np.isfinite(v), v, np.nan)

    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(v_plot, z, lw=1.2)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "y", ctx.window(axis))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]
