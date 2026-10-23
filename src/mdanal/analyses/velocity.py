"""流速剖面（MAICoS VelocityPlanar）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")


def run(ctx) -> dict[str, pd.DataFrame]:
    from maicos.modules.velocityplanar import VelocityPlanar

    dim, vdim, axis = _axes(ctx)

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
        "axis": _axes(ctx)[2],
        "ref_com": ctx.extras.get("velocity_ref"),
        "ref_frame": ctx.selection_frame,
    }


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    dim, vdim, axis = _axes(ctx)
    coordinate = table[f"{axis} (Å)"].to_numpy()
    velocity = table[f"v{AXES[vdim]} (Å/ps)"].to_numpy()

    # 没有样本的 bin 用 NaN 占位，让折线在该处断开而不是跨空档直连
    velocity_plot = np.where(np.isfinite(velocity), velocity, np.nan)

    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(coordinate, velocity_plot, lw=1.2)
    ax.set_xlabel(ctx.label(f"axis_{axis}"))
    ax.set_ylabel(ctx.label(f"v_{AXES[vdim]}"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(axis))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]


def _axes(ctx) -> tuple[int, int, str]:
    dim = _axis_index(ctx.params["dim"], "dim")
    vdim = _axis_index(ctx.params["vdim"], "vdim")
    return dim, vdim, AXES[dim]


def _axis_index(value, key: str) -> int:
    """轴名（x/y/z）或序号（0/1/2）转成轴序号。"""
    if isinstance(value, str):
        name = value.strip().lower()
        if name in AXES:
            return AXES.index(name)
    elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2:
        return int(value)
    raise ValidationError(f"{key} 只能是 x、y、z 或 0、1、2，收到 {value!r}")
