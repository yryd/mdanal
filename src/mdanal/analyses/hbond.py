"""氢键：每帧计数、汇总，以及每个氢键对在窗口内的占有率。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis

from .. import plotutil

COUNT_COLUMNS = ("帧", "时间 (ps)", "氢键数")
OCCUPANCY_COLUMNS = ("供体", "氢", "受体", "出现帧数", "占有率")


def run(ctx) -> dict[str, pd.DataFrame]:
    donor = ctx.groups["donor"]
    hydrogen = ctx.groups["hydrogen"]
    acceptor = ctx.groups["acceptor"]

    analysis = HydrogenBondAnalysis(
        ctx.universe,
        donors_sel=donor.selection,
        hydrogens_sel=hydrogen.selection,
        acceptors_sel=acceptor.selection,
        d_a_cutoff=float(ctx.params["d_a_cutoff"]),
        d_h_a_angle_cutoff=float(ctx.params["d_h_a_angle_cutoff"]),
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    counts = np.asarray(analysis.count_by_time(), dtype=int)
    frames = np.arange(ctx.start, ctx.start + len(counts))
    count_table = pd.DataFrame(
        {
            "帧": frames,
            "时间 (ps)": frames * ctx.frame_dt_ps,
            "氢键数": counts,
        }
    )

    occupancy_table = _occupancy(analysis, len(counts))
    summary_table = _summary(counts, donor.n_atoms)
    return {
        "hbond_count": count_table,
        "hbond_summary": summary_table,
        "hbond_occupancy": occupancy_table,
    }


def figures(ctx, tables):
    table = tables["hbond_count"]
    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(table["时间 (ps)"], table["氢键数"], lw=0.9, color="#4165c0")
    mean = float(table["氢键数"].mean())
    ax.axhline(mean, ls="--", lw=0.7, color="0.5")
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
    return [("hbond_count", fig)]


def _occupancy(analysis, n_frames: int) -> pd.DataFrame:
    hbonds = np.asarray(analysis.results.hbonds)
    if hbonds.size == 0 or n_frames == 0:
        return pd.DataFrame(columns=list(OCCUPANCY_COLUMNS))

    triples = pd.DataFrame(
        hbonds[:, 1:4].astype(int), columns=["供体", "氢", "受体"]
    )
    table = (
        triples.groupby(["供体", "氢", "受体"])
        .size()
        .rename("出现帧数")
        .reset_index()
    )
    table["占有率"] = table["出现帧数"] / n_frames
    return table.sort_values(["占有率", "供体"], ascending=[False, True]).reset_index(
        drop=True
    )


def _summary(counts: np.ndarray, n_molecules: int) -> pd.DataFrame:
    if counts.size == 0:
        return pd.DataFrame(
            [{"帧数": 0, "平均氢键数": 0.0, "标准差": 0.0, "每分子平均": 0.0}]
        )
    mean = float(counts.mean())
    return pd.DataFrame(
        [
            {
                "帧数": int(counts.size),
                "平均氢键数": mean,
                "标准差": float(counts.std(ddof=0)),
                "每分子平均": mean / max(n_molecules, 1),
            }
        ]
    )
