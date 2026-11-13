"""均方位移。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.msd import EinsteinMSD

from ..plot import annotations, chart, plotutil


SLOTS = ("group",)

PARAMS = {
    "msd_type": {
        "type": str,
        "default": "xyz",
        "choices": ("xyz", "xy", "xz", "yz", "x", "y", "z"),
        "help": "MSD 的维度组合",
    },
    "fft": {
        "type": bool,
        "default": True,
        "help": "用 FFT 加速",
    },
}

LABELS = {
    "zh": {
        "title": "均方位移",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
    },
    "en": {
        "title": "Mean squared displacement",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
    },
}

COORDINATES = "continuous"


COMPARE = {
    "table": "msd",
    "x": "Δt (ps)",
    "y": ["MSD (Å^2)"],
    "box_axis": False,
}


def run(ctx) -> dict[str, pd.DataFrame]:
    analysis = EinsteinMSD(
        ctx.groups["group"].atoms,
        select="all",
        msd_type=str(ctx.params["msd_type"]),
        fft=bool(ctx.params["fft"]),
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    # 单位：timeseries 为 Å²；delta_t_values 跟随轨迹时间，这里是 ps
    lag = np.asarray(analysis.results.delta_t_values, dtype=float)
    msd = np.asarray(analysis.results.timeseries, dtype=float)
    # delta_t_values 已按轨迹时间单位（ps）给出
    table = pd.DataFrame({"Δt (ps)": lag, "MSD (Å^2)": msd})
    return {"msd": table}


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    cols = list(table.columns)
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, table[cols[0]], table[cols[1]], marker="o", ms=2, lw=1.0)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    plotutil.limit(ax, "x", ctx.window("x"))
    plotutil.limit(ax, "y", ctx.window("y"))
    ax.set_title(ctx.label("title"))
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]
