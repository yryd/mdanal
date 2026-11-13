"""氢键类型分布：按供体/受体所属分子与元素汇总各种氢键的数量。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError
from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis


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
    "figure_axis": {
        "type": str,
        "default": "rate",
        "choices": ("rate", "total"),
        "help": "柱状图用每帧平均（rate）还是总次数（total）",
    },
}

LABELS = {
    "zh": {
        "title": "氢键类型分布",
        "count": "次数",
        "rate": "每帧平均次数",
    },
    "en": {
        "title": "Hydrogen bond types",
        "count": "count",
        "rate": "per-frame average",
    },
}

COLUMNS = ("供体", "受体", "次数", "每帧平均", "占比")
FIGURE_ROWS = 12


def _build(ctx) -> HydrogenBondAnalysis:
    """按三个槽位与两个判据构造分析。

    判据与 hbond.py / hbond_lifetime.py 必须一致；改动需三处同步
    （由 tests/analyses 的一致性测试守护）。
    """
    return HydrogenBondAnalysis(
        ctx.universe,
        donors_sel=ctx.groups["donor"].selection,
        hydrogens_sel=ctx.groups["hydrogen"].selection,
        acceptors_sel=ctx.groups["acceptor"].selection,
        d_a_cutoff=float(ctx.params["d_a_cutoff"]),
        d_h_a_angle_cutoff=float(ctx.params["d_h_a_angle_cutoff"]),
    )


def run(ctx) -> dict[str, pd.DataFrame]:
    if not hasattr(ctx.universe.atoms, "resnames"):
        raise ValidationError(
            "hbond_type 需要分子名与元素；请先在 system.yaml 配置 naming"
        )

    analysis = _build(ctx)
    analysis.run(start=ctx.start, stop=ctx.stop)

    # 单位：count_by_type() 返回 (供体类型, 受体类型, 次数)，次数为整数计数
    counts = np.asarray(analysis.count_by_time(), dtype=int)
    n_frames = max(counts.size, 1)
    total = int(counts.sum())

    table = _summarise(analysis.count_by_type(), ctx, n_frames, total)
    ctx.extras["hbond_type_total"] = total
    return {"hbond_type": table}


def meta(ctx, tables) -> dict:
    table = tables["hbond_type"]
    return {
        "total": int(ctx.extras.get("hbond_type_total", 0)),
        "types": int(len(table)),
    }


def figures(ctx, tables):
    table = tables["hbond_type"]
    if table.empty:
        ctx.warn("窗口内没有氢键，跳过类型分布图")
        return []

    axis = str(ctx.params["figure_axis"]).lower()
    if axis not in ("rate", "total"):
        raise ValidationError(
            f"figure_axis 只能是 rate 或 total，收到 {axis!r}"
        )
    column, label = ("每帧平均", "rate") if axis == "rate" else ("次数", "count")

    shown = table.head(FIGURE_ROWS)
    return [("hbond_type", _bars(ctx, shown, column, label))]


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #


def _summarise(rows, ctx, n_frames: int, total: int) -> pd.DataFrame:
    elements = _type_elements(ctx)
    counts: dict[tuple[str, str], int] = {}
    for donor, acceptor, count in rows:
        key = (_label(donor, elements), _label(acceptor, elements))
        counts[key] = counts.get(key, 0) + int(count)

    if not counts:
        return pd.DataFrame(columns=list(COLUMNS))

    table = pd.DataFrame(
        [(d, a, n) for (d, a), n in counts.items()],
        columns=["供体", "受体", "次数"],
    ).sort_values("次数", ascending=False, ignore_index=True)
    table["每帧平均"] = table["次数"] / n_frames
    table["占比"] = table["次数"] / max(total, 1)
    return table.loc[:, list(COLUMNS)]


def _type_elements(ctx) -> dict[str, str]:
    """type 编号 → 元素符号；同一 type 的元素必须一致。"""
    mapping: dict[str, str] = {}
    for type_value, element in zip(ctx.universe.atoms.types, ctx.universe.atoms.elements):
        previous = mapping.setdefault(str(type_value), str(element))
        if previous != element:
            raise ValidationError(
                f"type {type_value} 上出现了两种元素（{previous}、{element}）"
            )
    return mapping


def _label(pair: str, elements: dict[str, str]) -> str:
    """把 count_by_type 的 "分子名:type" 翻成 "分子名-元素"。"""
    resname, _, type_value = pair.partition(":")
    element = elements.get(type_value)
    return f"{resname}-{element}" if element else pair


def _bars(ctx, table: pd.DataFrame, column: str, suffix: str):
    labels = (table["供体"] + " → " + table["受体"]).tolist()
    values = table[column].to_numpy(dtype=float)

    fig, ax = chart.figure(ctx.size("wide"))
    # 数值与占比标在条末：占比极小的类型在条形图上几乎看不见，靠数字读
    shares = table["占比"].to_numpy(dtype=float)
    chart.bars(
        ax,
        labels,
        values,
        notes=[f"{_number(v)} ({_percent(s)})" for v, s in zip(values, shares)],
        height=0.7,
        color=chart.COLORS["primary"],
        note_fontsize=6,
        headroom=1.35,
    )
    ax.set_xlabel(ctx.label(suffix))
    plotutil.limit(ax, "x", ctx.window("x"))
    ax.set_title(ctx.label("title"))
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return fig


def _number(value: float) -> str:
    return f"{value:,.0f}" if value >= 100 else f"{value:.3g}"


def _percent(share: float) -> str:
    percent = share * 100.0
    if percent >= 10:
        return f"{percent:.0f}%"
    if percent >= 1:
        return f"{percent:.1f}%"
    return f"{percent:.2f}%"
