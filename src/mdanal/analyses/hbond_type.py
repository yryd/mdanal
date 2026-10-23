"""氢键类型分布：按供体/受体所属分子与元素汇总各种氢键的数量。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import plotutil
from ..errors import ValidationError
from .hbond import build_analysis

COLUMNS = ("供体", "受体", "次数", "每帧平均", "占比")
FIGURE_ROWS = 12


def run(ctx) -> dict[str, pd.DataFrame]:
    if not hasattr(ctx.universe.atoms, "resnames"):
        raise ValidationError(
            "hbond_type 需要分子名与元素；请先在 system.yaml 配置 naming"
        )

    analysis = build_analysis(ctx)
    analysis.run(start=ctx.start, stop=ctx.stop)

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

    fig, ax = plotutil.figure(ctx.size("wide"))
    positions = np.arange(len(labels))
    bars = ax.barh(positions, values, height=0.7, color="#4165c0")
    ax.set_yticks(positions, labels)
    ax.invert_yaxis()
    # 数值与占比标在条末：占比极小的类型在条形图上几乎看不见，靠数字读
    shares = table["占比"].to_numpy(dtype=float)
    ax.bar_label(
        bars,
        labels=[f"{_number(v)} ({_percent(s)})" for v, s in zip(values, shares)],
        padding=2,
        fontsize=6,
    )
    ax.set_xlim(0, float(values.max()) * 1.35 if values.size else 1.0)
    ax.set_xlabel(ctx.label(suffix))
    ax.set_title(ctx.label("title"))
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
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
