"""氢键类型分布：按供体/受体所属分子与元素汇总各种氢键的数量。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._geometry import full_periodic_meta
from ...plot import annotations, chart
from ...plot.panels import Panel
from ...plot.specs import Bars, PanelRequest, Series
from ...errors import ValidationError


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

COLUMNS = ("donor", "acceptor", "count", "per_frame", "share")
FIGURE_ROWS = 12

COORDINATES = "in_box"

GEOMETRY = {"cell": "any", "periodicity": "full"}


def _selection(group) -> str:
    """把已解析的原子组变成固定的 bynum 选择串，避免按库自己的坐标系重选。"""
    indices = np.asarray(group.atoms.indices, dtype=int) + 1
    return "bynum " + " ".join(str(index) for index in indices)


def run(ctx) -> dict[str, pd.DataFrame]:
    if not hasattr(ctx.universe.atoms, "resnames"):
        raise ValidationError(
            "hbond_type 需要分子名与元素；请先在 source 配置 naming"
        )

    from .._hbond import analysis as _analysis

    analysis = _analysis(ctx)

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
        **full_periodic_meta(ctx),
    }


def build_series(ctx, tables) -> list[Series]:
    table = tables["hbond_type"]
    axis = str(ctx.params["figure_axis"]).lower()
    column, suffix = ("per_frame", "rate") if axis == "rate" else ("count", "count")
    shown = table.head(FIGURE_ROWS)
    labels = (shown["donor"] + " → " + shown["acceptor"]).tolist()
    values = shown[column].to_numpy(dtype=float)
    shares = shown["share"].to_numpy(dtype=float)
    bars = Bars(
        labels=labels,
        values=values,
        notes=tuple(f"{_number(v)} ({_percent(s)})" for v, s in zip(values, shares)),
        label=ctx.label(suffix),
        color=chart.COLORS["primary"],
    )
    return [Series(name="hbond_type", bars=[bars], label=ctx.label(suffix))]


def panel_request(ctx, tables) -> PanelRequest:
    axis = str(ctx.params["figure_axis"]).lower()
    suffix = "rate" if axis == "rate" else "count"
    return PanelRequest(
        recipe="hbond_type",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label(suffix),
        options={},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        for series in request.series:
            for bars in series.bars:
                chart.bars(
                    ax,
                    bars.labels,
                    bars.values,
                    notes=list(bars.notes),
                    height=0.7,
                    color=bars.color or chart.COLORS["primary"],
                    note_fontsize=8,
                    headroom=1.35,
                )
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="hbond_type",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel,
        aspect="auto",
        xlim=ctx.window("x"),
        panel_size=ctx.size("wide"),
    )


def panels(ctx, tables) -> list[Panel]:
    if tables["hbond_type"].empty:
        ctx.warn("窗口内没有氢键，跳过类型分布图")
        return []
    request = panel_request(ctx, tables)
    return [render_panel(ctx, request)]




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
        columns=["donor", "acceptor", "count"],
    ).sort_values("count", ascending=False, ignore_index=True)
    table["per_frame"] = table["count"] / n_frames
    table["share"] = table["count"] / max(total, 1)
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


def _number(value: float) -> str:
    return f"{value:,.0f}" if value >= 100 else f"{value:.3g}"


def _percent(share: float) -> str:
    percent = share * 100.0
    if percent >= 10:
        return f"{percent:.0f}%"
    if percent >= 1:
        return f"{percent:.1f}%"
    return f"{percent:.2f}%"
