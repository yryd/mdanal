"""图内标注：物理盒轴、图横轴/纵轴数据坐标，以及双语文字。"""

from __future__ import annotations

from typing import Any, Mapping

from . import chart
from ..errors import ValidationError

KINDS = ("vline", "hline", "span", "text")
AXES = ("x", "y", "z", "horizontal", "vertical")
ALLOWED = {"kind", "axis", "at", "text"}


def parse(value: Any, where: str) -> tuple[dict[str, Any], ...]:
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
        text = _text(entry.get("text"), position)
        axis = entry.get("axis")

        item: dict[str, Any] = {"kind": kind, "text": text}
        if kind == "vline":
            if axis not in ("x", "y", "z", "horizontal"):
                raise ValidationError(
                    "vline 的 axis 只能是 x/y/z/horizontal（纵轴用 hline）",
                    where=position,
                )
            item["axis"] = axis
            item["at"] = _number(entry.get("at"), "at", position)
        elif kind == "hline":
            if axis is not None and axis != "vertical":
                raise ValidationError(
                    "hline 的 axis 只能省略或写 vertical", where=position
                )
            item["axis"] = "vertical"
            item["at"] = _number(entry.get("at"), "at", position)
        elif kind == "span":
            if axis not in AXES:
                raise ValidationError(
                    "span 的 axis 只能是 x/y/z/horizontal/vertical", where=position
                )
            item["axis"] = axis
            item["at"] = _pair(entry.get("at"), position)
        else:  # text
            if axis is not None:
                raise ValidationError("text 不接受 axis", where=position)
            item["at"] = _point(entry.get("at"), position)
        items.append(item)
    return tuple(items)


def draw(ax, ctx, *, x_axis: str | None = None) -> None:
    """把标注画到 ax；x_axis 是这张图横轴对应的物理盒轴（没有则为 None）。"""
    for item in getattr(ctx, "annotations", ()) or ():
        kind = item["kind"]
        text = _resolve_text(item.get("text"), getattr(ctx, "lang", "zh"))
        axis = item.get("axis")

        if kind == "vline":
            if axis == "horizontal":
                _vline(ax, item["at"], text)
            elif axis == x_axis:
                _vline(ax, item["at"], text)
            else:
                _warn_once(
                    ctx,
                    f"标注的物理轴 {axis!r} 不是本图横轴；跳过",
                )
        elif kind == "hline":
            chart.refline(ax, item["at"], ls=":", lw=chart.ANNOTATION_LINEWIDTH, color=chart.COLORS["guide"])
            if text:
                ax.text(
                    0.98, item["at"], text,
                    transform=ax.get_yaxis_transform(),
                    ha="right", va="bottom", fontsize=chart.ANNOTATION_FONTSIZE,
                    fontweight=chart.ANNOTATION_WEIGHT, color=chart.COLORS["guide"],
                )
        elif kind == "span":
            low, high = item["at"]
            if axis == "horizontal" or axis == x_axis:
                chart.span(ax, low, high, axis="x")
                if text:
                    ax.text(
                        (low + high) / 2, 0.90, text,
                        transform=ax.get_xaxis_transform(),
                        ha="center", va="top", fontsize=chart.ANNOTATION_FONTSIZE,
                        fontweight=chart.ANNOTATION_WEIGHT, color=chart.COLORS["guide"],
                    )
            elif axis == "vertical":
                chart.span(ax, low, high, axis="y")
                if text:
                    ax.text(
                        0.98, (low + high) / 2, text,
                        transform=ax.get_yaxis_transform(),
                        ha="right", va="center", fontsize=chart.ANNOTATION_FONTSIZE,
                        fontweight=chart.ANNOTATION_WEIGHT, color=chart.COLORS["guide"],
                    )
            else:
                _warn_once(
                    ctx,
                    f"标注的物理轴 {axis!r} 不是本图横轴；跳过",
                )
        else:  # text
            x, y = item["at"]
            chart.text(ax, x, y, text or "", ha="left", va="bottom")


def _vline(ax, at: float, text: str | None) -> None:
    chart.vline(ax, at, ls=":", lw=chart.ANNOTATION_LINEWIDTH, color=chart.COLORS["guide"])
    if text:
        ax.text(
            at, 0.97, text,
            transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=chart.ANNOTATION_FONTSIZE,
            fontweight=chart.ANNOTATION_WEIGHT, color=chart.COLORS["guide"],
        )


def _warn_once(ctx, message: str) -> None:
    if hasattr(ctx, "warnings") and message in ctx.warnings:
        return
    ctx.warn(message)


def _text(value: Any, where: str) -> str | dict[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if set(value) != {"zh", "en"} or any(
            not isinstance(item, str) for item in value.values()
        ):
            raise ValidationError(
                f"text 映射必须同时含 zh 和 en 字符串，收到 {value!r}", where=where
            )
        return {"zh": value["zh"], "en": value["en"]}
    raise ValidationError(f"text 必须是字符串或 zh/en 映射，收到 {value!r}", where=where)


def _resolve_text(value, lang: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.get(lang) or value.get("zh")


def _number(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{key} 必须是数值，收到 {value!r}", where=where)
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValidationError(f"{key} 必须是有限数，收到 {value!r}", where=where)
    return number


def _point(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise ValidationError(f"at 必须是两个数 [x, y]，收到 {value!r}", where=where)
    return (float(value[0]), float(value[1]))


def _pair(value: Any, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise ValidationError(f"at 必须是两个数 [a, b]，收到 {value!r}", where=where)
    low, high = (float(value[0]), float(value[1]))
    if low == high:
        raise ValidationError(f"at 的两个数不能相等，收到 {value!r}", where=where)
    return (low, high) if low < high else (high, low)
