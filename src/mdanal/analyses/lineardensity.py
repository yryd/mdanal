"""线密度：沿单轴的质量密度与电荷密度。

逐帧直方图自己累加，不用 MDAnalysis 的 LinearDensity：后者把盒尺寸在构造时抓成
一个"活视图"，遇到多段合并（ChainReader）或内存读取（MemoryReader）时视图不再
随帧更新，同一份数据会因读取方式不同而给出不同结果。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.units import constants

from .. import annotations, chart, plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")
AVOGADRO = constants["N_Avogadro"]
VOLUME_CONVERSION = 1e-24  # Å^3 → cm^3


COMPARE = {
    "table": "lineardensity_{dim}",
    "x": "{axis} (Å)",
    "y": ["质量密度 (g/cm^3)"],
    "box_axis": True,
}


def run(ctx) -> dict[str, pd.DataFrame]:
    binsize = float(ctx.params["binsize"])
    if binsize <= 0:
        raise ValidationError(f"binsize 必须为正数，收到 {binsize}")

    group = ctx.groups["group"].atoms
    n_frames = ctx.stop - ctx.start
    if n_frames <= 0:
        raise ValidationError("帧窗口为空，无法计算线密度")

    # 与库一致：网格数按起始帧的盒尺寸取整，切片体积在整个窗口内固定
    dimensions = np.asarray(ctx.universe.dimensions[:3], dtype=float)
    volume = float(np.prod(dimensions))
    bins = (dimensions // binsize).astype(int)
    if int(bins.min()) < 1:
        raise ValidationError(
            f"binsize {binsize:g} Å 大于最短盒长 {float(dimensions.min()):g} Å"
        )
    nbins = int(bins.max())
    slice_volume = volume / bins
    lengths = [float(value) for value in dimensions]

    masses = np.asarray(group.masses, dtype=float)
    charges = np.asarray(group.charges, dtype=float)
    mass_sum = {axis: np.zeros(nbins) for axis in AXES}
    charge_sum = {axis: np.zeros(nbins) for axis in AXES}
    edges: dict[str, np.ndarray] = {}

    for frame in range(ctx.start, ctx.stop):
        ctx.universe.trajectory[frame]
        group.wrap(compound="atoms")
        positions = group.positions
        # 库对三个轴统一用最大盒长作上界，这里保持一致
        upper = float(np.max(ctx.universe.dimensions[:3]))
        for axis in AXES:
            column = positions[:, AXES.index(axis)]
            mass_hist, _ = np.histogram(
                column, weights=masses, bins=nbins, range=(0.0, upper)
            )
            charge_hist, bin_edges = np.histogram(
                column, weights=charges, bins=nbins, range=(0.0, upper)
            )
            mass_sum[axis] += mass_hist
            charge_sum[axis] += charge_hist
            edges[axis] = bin_edges

    norm_factor = AVOGADRO * VOLUME_CONVERSION
    tables: dict[str, pd.DataFrame] = {}
    for axis in AXES:
        norm = norm_factor * slice_volume[AXES.index(axis)]
        mass_density = mass_sum[axis] / n_frames / norm
        charge_density = charge_sum[axis] / n_frames / norm

        # 末尾不足一个 bin 的薄层整格丢弃，否则该格的密度会因体积按满格计而偏低
        bin_edges = edges[axis]
        n_bins = int(
            np.searchsorted(bin_edges, lengths[AXES.index(axis)], side="right") - 1
        )
        # 表里是盒坐标（0…L）；视图平移只在出图时施加
        centers = 0.5 * (bin_edges[1:] + bin_edges[:-1])[:n_bins]
        tables[f"lineardensity_{axis}"] = pd.DataFrame(
            {
                f"{axis} (Å)": centers,
                "质量密度 (g/cm^3)": mass_density[:n_bins],
                "电荷密度 (e/Å^3)": charge_density[:n_bins],
            }
        )
    return tables


def figures(ctx, tables):
    axis = str(ctx.params["dim"]).lower()
    name = f"lineardensity_{axis}"
    table = tables[name]
    cols = list(table.columns)

    shift = ctx.system.view.shift[AXES.index(axis)]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, np.asarray(table[cols[0]]) + shift, table[cols[1]], lw=1.2)
    ax.set_xlabel(ctx.label(f"axis_{axis}"))
    ax.set_ylabel(ctx.label("mass"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(axis))
    annotations.draw(ax, ctx, axes={"x": axis})
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]
