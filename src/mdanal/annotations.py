"""图内标注：把 `analyses[].annotate` 的声明画到分析图上。

标注属于某一条分析、并且绑定到具体的坐标轴——`density-xz` 的横轴是 x、
`lineardensity` 的横轴是 z，同一个 `vline x=22` 在两处含义不同，故 `axis` 必填。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from . import chart
from .errors import ValidationError

KINDS = ("vline", "hline", "span", "text")
AXES = ("x", "y", "z")
ALLOWED = {"kind", "axis", "at", "text"}


def parse(value: Any, where: str) -> tuple[dict[str, Any], ...]:
    """校验并规范化一条分析上的 annotate 列表。"""
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValidationError("annotate 必须是列表", where=f"{where}:annotate")

    items: list[dict[str, Any]] = []
    for index, entry in enumerate(value, start=1):
        position = f"{where}:annotate[{index}]"
        if not isinstance(entry, dict):
            raise ValidationError("每条标注必须是映射", where=position)
        unknown = set(entry) - ALLOWED
        if unknown:
            raise ValidationError(
                f"标注含未知字段 {sorted(unknown)}；允许 {sorted(ALLOWED)}",
                where=position,
            )

        kind = entry.get("kind")
        if kind not in KINDS:
            raise ValidationError(
                f"kind 只能是 {list(KINDS)}，收到 {kind!r}", where=position
            )

        text = entry.get("text")
        if text is not None and not isinstance(text, str):
            raise ValidationError("text 必须是字符串", where=position)

        item: dict[str, Any] = {"kind": kind, "text": text}
        if kind in ("vline", "span"):
            axis = entry.get("axis")
            if axis not in AXES:
                raise ValidationError(
                    f"{kind} 必须指明 axis（x/y/z），收到 {axis!r}", where=position
                )
            item["axis"] = axis
        if kind == "hline":
            item["at"] = _number(entry.get("at"), "at", position)
        elif kind == "vline":
            item["at"] = _number(entry.get("at"), "at", position)
        elif kind == "span":
            item["at"] = _pair(entry.get("at"), position)
        else:  # text
            item["at"] = _pair(entry.get("at"), position)
        items.append(item)
    return tuple(items)


def draw(ax, ctx, *, axes: Mapping[str, str] | None = None) -> None:
    """把该条分析的标注画到 ax 上。

    `axes` 是这张图的横/纵轴对应的盒坐标轴名，如 ``{"x": "z"}``；
    没有盒坐标轴的图（g(r)、MSD、氢键计数）传 None，此时 vline 与 span 被跳过。
    """
    for item in getattr(ctx, "annotations", ()) or ():
        kind = item["kind"]
        text = item["text"]
        if kind == "vline":
            if not axes or axes.get("x") != item["axis"]:
                continue
            chart.vline(ax, item["at"], ls=":", lw=0.8, color=chart.COLORS["guide"])
            if text:
                ax.text(
                    item["at"], 0.97, text,
                    transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=6, color=chart.COLORS["guide"],
                )
        elif kind == "span":
            if not axes or axes.get("x") != item["axis"]:
                continue
            low, high = item["at"]
            chart.span(ax, low, high, axis="x")
            if text:
                ax.text(
                    (low + high) / 2, 0.97, text,
                    transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=6, color=chart.COLORS["guide"],
                )
        elif kind == "hline":
            chart.refline(ax, item["at"], ls=":", lw=0.8, color=chart.COLORS["guide"])
            if text:
                ax.text(
                    0.98, item["at"], text,
                    transform=ax.get_yaxis_transform(),
                    ha="right", va="bottom", fontsize=6, color=chart.COLORS["guide"],
                )
        else:  # text
            x, y = item["at"]
            chart.text(ax, x, y, text or "", ha="left", va="bottom")


def _number(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{key} 必须是数值，收到 {value!r}", where=where)
    return float(value)


def _pair(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise ValidationError(f"at 必须是两个数 [a, b]，收到 {value!r}", where=where)
    low, high = float(value[0]), float(value[1])
    if low == high:
        raise ValidationError(f"at 的两个数不能相等，收到 {value!r}", where=where)
    return (low, high) if low < high else (high, low)
