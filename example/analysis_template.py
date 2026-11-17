"""可复制的小分析模板：空 PARAMS、只依赖表与 PlotContext 的 figures。

复制到 `src/mdanal/analyses/<name>.py` 后，改文件名、LABELS 和计算内容；
不要放进 analyses/ 之外还指望自动发现。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mdanal.plot import annotations, chart

SLOTS = ("group",)

# 空参数是合法的：分析没有可调项时不要虚构参数。
PARAMS = {}

LABELS = {
    "zh": {"title": "模板分析", "x": "时间 (ps)", "y": "质心 z (Å)", "window": "帧 {start}–{stop}"},
    "en": {"title": "Template analysis", "x": "time (ps)", "y": "COM z (Å)", "window": "frames {start}–{stop}"},
}

COORDINATES = "in_box"
GEOMETRY = {"cell": "orthorhombic", "periodicity": "full"}
REQUIRES = ()
MUTATES_POSITIONS = False

COLUMN_LABELS = {
    "zh": {"time_ps": "时间 (ps)", "com_z_angstrom": "质心 z (Å)"},
    "en": {"time_ps": "time (ps)", "com_z_angstrom": "COM z (Å)"},
}


def run(ctx) -> dict[str, pd.DataFrame]:
    atoms = ctx.groups["group"].atoms
    times, values = [], []
    for frame in range(ctx.start, ctx.stop):
        ctx.universe.trajectory[frame]
        times.append(frame * ctx.frame_dt_ps)
        values.append(float(atoms.center_of_mass()[2]))
    return {
        "template": pd.DataFrame(
            {"time_ps": np.asarray(times), "com_z_angstrom": np.asarray(values)}
        )
    }


def meta(ctx, tables) -> dict:
    return {"n_frames": int(len(tables["template"]))}


def figures(ctx, tables):
    table = tables["template"]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, table["time_ps"], table["com_z_angstrom"], lw=1.2)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    # 整体质心接近常数；关掉 1e-6 的偏移标记，避免把微小数值当成大变化
    ax.ticklabel_format(axis="y", useOffset=False, style="plain")
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [("template", fig)]
