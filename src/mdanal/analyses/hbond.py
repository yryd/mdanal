"""氢键：每帧计数、汇总，以及每个氢键对在窗口内的占有率。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis

from ..plot import annotations, chart, plotutil


SLOTS = ("donor", "hydrogen", "acceptor")

PARAMS = {
    "d_a_cutoff": {
        "type": float,
        "default": 3.5,
        "unit": "Å",
        "min": 0.1,
        "help": "供体-受体距离上限",
    },
    "d_h_a_angle_cutoff": {
        "type": float,
        "default": 150,
        "unit": "度",
        "min": 0.0,
        "max": 180.0,
        "help": "D-H-A 角度下限",
    },
}

LABELS = {
    "zh": {
        "title": "氢键数",
        "x": "时间 (ps)",
        "y": "氢键数",
    },
    "en": {
        "title": "Hydrogen bonds",
        "x": "time (ps)",
        "y": "hydrogen bonds",
    },
}

OCCUPANCY_COLUMNS = ("donor", "hydrogen", "acceptor", "frames_present", "occupancy")


def _selection(group) -> str:
    """把已解析的原子组变成固定的 bynum 选择串，避免按库自己的坐标系重选。"""
    indices = np.asarray(group.atoms.indices, dtype=int) + 1
    return "bynum " + " ".join(str(index) for index in indices)


def _build(ctx) -> HydrogenBondAnalysis:
    """按三个槽位与两个判据构造分析。

    氢键判据与 hbond_type.py / hbond_lifetime.py 必须一致；改动需三处同步
    （由 tests/analyses 的一致性测试守护）。
    """
    return HydrogenBondAnalysis(
        ctx.universe,
        donors_sel=_selection(ctx.groups["donor"]),
        hydrogens_sel=_selection(ctx.groups["hydrogen"]),
        acceptors_sel=_selection(ctx.groups["acceptor"]),
        d_a_cutoff=float(ctx.params["d_a_cutoff"]),
        d_h_a_angle_cutoff=float(ctx.params["d_h_a_angle_cutoff"]),
        update_selections=False,
    )


COLUMN_LABELS = {
    "zh": {"time_ps": "时间 (ps)", "hbond_count": "氢键数"},
    "en": {"time_ps": "time (ps)", "hbond_count": "hydrogen bonds"},
}

COMPARE = {
    "table": "hbond_count",
    "x": "time_ps",
    "y": ["hbond_count"],
    "box_axis": False,
}


def run(ctx) -> dict[str, pd.DataFrame]:
    donor = ctx.groups["donor"]

    # 单位：count_by_time() 是每帧氢键数（个）；results.hbonds 的列为
    # [frame, donor, hydrogen, acceptor, distance(Å), angle(度)]
    analysis = _build(ctx)
    analysis.run(start=ctx.start, stop=ctx.stop)

    counts = np.asarray(analysis.count_by_time(), dtype=int)
    frames = np.arange(ctx.start, ctx.start + len(counts))
    count_table = pd.DataFrame(
        {
            "frame": frames,
            "time_ps": frames * ctx.frame_dt_ps,
            "hbond_count": counts,
        }
    )

    occupancy_table = _occupancy(analysis, len(counts))
    summary_table = _summary(counts, donor)
    return {
        "hbond_count": count_table,
        "hbond_summary": summary_table,
        "hbond_occupancy": occupancy_table,
    }


def figures(ctx, tables):
    table = tables["hbond_count"]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(
        ax, table["time_ps"], table["hbond_count"], lw=0.9, color=chart.COLORS["primary"]
    )
    mean = float(table["hbond_count"].mean())
    chart.refline(ax, mean, ls="--", lw=0.7, color="0.5")
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    plotutil.limit(ax, "x", ctx.window("x"))
    plotutil.limit(ax, "y", ctx.window("y"))
    ax.set_title(ctx.label("title"))
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [("hbond_count", fig)]


def _occupancy(analysis, n_frames: int) -> pd.DataFrame:
    hbonds = np.asarray(analysis.results.hbonds)
    if hbonds.size == 0 or n_frames == 0:
        return pd.DataFrame(columns=list(OCCUPANCY_COLUMNS))

    triples = pd.DataFrame(
        hbonds[:, 1:4].astype(int), columns=["donor", "hydrogen", "acceptor"]
    )
    table = (
        triples.groupby(["donor", "hydrogen", "acceptor"])
        .size()
        .rename("frames_present")
        .reset_index()
    )
    table["occupancy"] = table["frames_present"] / n_frames
    return table.sort_values(["occupancy", "donor"], ascending=[False, True]).reset_index(
        drop=True
    )


def _summary(counts: np.ndarray, donor) -> pd.DataFrame:
    """归一化分别按供体原子数与供体残基数给出，避免"每分子"含义含糊。"""
    n_atoms = donor.atoms.n_atoms
    n_residues = donor.atoms.residues.n_residues
    if counts.size == 0:
        return pd.DataFrame(
            [
                {
                    "n_frames": 0,
                    "mean_hbonds": 0.0,
                    "std_hbonds": 0.0,
                    "per_donor_atom": 0.0,
                    "per_donor_residue": 0.0,
                }
            ]
        )
    mean = float(counts.mean())
    return pd.DataFrame(
        [
            {
                "n_frames": int(counts.size),
                "mean_hbonds": mean,
                "std_hbonds": float(counts.std(ddof=0)),
                "per_donor_atom": mean / max(n_atoms, 1),
                "per_donor_residue": mean / max(n_residues, 1),
            }
        ]
    )
