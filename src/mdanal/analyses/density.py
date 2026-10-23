"""密度投影：三维数密度沿指定轴求和，投影到另外两轴。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.density import DensityAnalysis

from .. import plotutil
from ..errors import ValidationError
from ..writers import project_grid

AXES = ("x", "y", "z")


def run(ctx) -> dict[str, pd.DataFrame]:
    params = ctx.params
    sum_axis = str(params["sum_axis"]).lower()
    if sum_axis not in AXES:
        raise ValidationError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")
    delta = float(params["delta"])
    if delta <= 0:
        raise ValidationError(f"delta 必须为正数，收到 {delta}")

    atoms = ctx.groups["group"].atoms
    lx, ly, lz = (float(v) for v in ctx.universe.dimensions[:3])
    ox, oy, oz = ctx.system.view.lower
    # 显式给定网格范围：默认以原子包围盒居中，会漏掉盒边缘的原子
    analysis = DensityAnalysis(
        atoms,
        delta=delta,
        padding=0.0,
        gridcenter=[ox + lx / 2, oy + ly / 2, oz + lz / 2],
        xdim=lx,
        ydim=ly,
        zdim=lz,
    )
    analysis.run(start=ctx.start, stop=ctx.stop)
    grid = analysis.results.density
    ctx.extras["density_extent"] = {
        axis: float(np.asarray(grid.edges[i])[-1] - np.asarray(grid.edges[i])[0])
        for i, axis in enumerate(AXES)
    }

    center_a, center_b, density, keep = project_grid(grid.grid, grid.edges, sum_axis)
    a, b = AXES[keep[0]], AXES[keep[1]]

    # 平面场要摊平成 (坐标, 坐标, 值) 三列；density[i, j] 对应 (a_i, b_j)
    grid_a, grid_b = np.meshgrid(center_a, center_b, indexing="ij")
    table = pd.DataFrame(
        {
            f"{a} (Å)": grid_a.ravel(),
            f"{b} (Å)": grid_b.ravel(),
            "数密度 (Å^-3)": density.ravel(),
        }
    )
    return {f"density_{a}{b}": table}


def meta(ctx, tables) -> dict:
    """记录网格范围，便于用 Σρ·Δa·Δb·L_axis 核验原子数守恒。"""
    sum_axis = str(ctx.params["sum_axis"]).lower()
    return {
        "sum_axis": sum_axis,
        "delta": float(ctx.params["delta"]),
        # DensityAnalysis 的网格按 delta 取整，覆盖范围略大于盒长，核验时用这一组
        "grid_extent": dict(ctx.extras.get("density_extent", {})),
    }


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    cols = list(table.columns)
    pivot = table.pivot(index=cols[1], columns=cols[0], values=cols[2])

    sum_axis = str(ctx.params["sum_axis"]).lower()
    keep = [axis for axis in AXES if axis != sum_axis]
    a, b = keep[0], keep[1]

    fig, ax = plotutil.figure(ctx.size("map"))
    mesh = ax.pcolormesh(
        pivot.columns.to_numpy(),
        pivot.index.to_numpy(),
        pivot.to_numpy(),
        shading="auto",
        cmap=plotutil.density_cmap(),
    )
    ax.set_aspect("equal")
    ax.set_xlabel(ctx.label(f"axis_{a}"))
    ax.set_ylabel(ctx.label(f"axis_{b}"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(a))
    plotutil.limit(ax, "y", ctx.window(b))
    plotutil.colorbar(fig, ax, mesh, ctx.label("cbar"))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [(name, fig)]
