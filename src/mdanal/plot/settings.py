"""Panel 呈现设置校验。"""

from __future__ import annotations

from typing import Any, Mapping

import matplotlib
from matplotlib import rcParams
from matplotlib.colors import is_color_like

from ..errors import ValidationError

PLOT_KEYS = {
    "window", "size", "xlim", "ylim", "title", "xlabel", "ylabel",
    "rc", "palette", "layout", "cbar_width", "cbar_frame",
}
TEXT_KEYS = {"title", "xlabel", "ylabel"}


def _finite_pair(value: Any, where: str, *, positive: bool = False) -> tuple[float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not (float(item) == float(item))
            for item in value
        )
    ):
        raise ValidationError(f"{where} 必须是两个有限数，收到 {value!r}")
    low, high = float(value[0]), float(value[1])
    if not (abs(low) != float("inf") and abs(high) != float("inf")):
        raise ValidationError(f"{where} 必须是有限数，收到 {value!r}")
    if positive and (low <= 0 or high <= 0):
        raise ValidationError(f"{where} 必须为正数，收到 {value!r}")
    if not positive and high <= low:
        raise ValidationError(f"{where} 要求第一个数小于第二个数，收到 {value!r}")
    return low, high


def parse_text(value: Any, where: str) -> str | dict[str, str]:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        if set(value) != {"zh", "en"}:
            raise ValidationError(f"{where} 必须同时含 zh 和 en")
        result = {}
        for key, item in value.items():
            if not isinstance(item, str):
                raise ValidationError(f"{where}.{key} 必须是字符串")
            result[key] = item
        return result
    raise ValidationError(f"{where} 必须是字符串或 {{zh, en}} 映射")




def resolve_palette(value: Any, where: str) -> tuple[str, ...]:
    """把 ``bright`` 这类 SciencePlots 色板或颜色列表规范成颜色元组。"""
    if isinstance(value, str):
        name = value.strip()
        if not name:
            raise ValidationError(f"{where} 不能是空字符串", where=where)
        try:
            import scienceplots  # noqa: F401  注册 SciencePlots 样式名
        except ImportError as exc:
            raise ValidationError(
                f"{where} 使用命名色板需要安装 scienceplots", where=where
            ) from exc
        try:
            with matplotlib.style.context(name):
                colors = rcParams["axes.prop_cycle"].by_key().get("color")
        except Exception as exc:
            raise ValidationError(
                f"{where} 不是可用的 Matplotlib/SciencePlots 色板名：{name!r}",
                where=where,
            ) from exc
        if not colors:
            raise ValidationError(
                f"{where} 色板 {name!r} 没有颜色循环", where=where
            )
        return tuple(str(color) for color in colors)
    if isinstance(value, (list, tuple)) and value:
        colors = []
        for index, color in enumerate(value):
            if not isinstance(color, str) or not is_color_like(color):
                raise ValidationError(
                    f"{where}[{index}] 不是有效颜色：{color!r}", where=where
                )
            colors.append(str(color))
        return tuple(colors)
    raise ValidationError(
        f"{where} 必须是色板名或非空颜色列表，收到 {value!r}", where=where
    )


def parse_plot(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValidationError(f"{where} 必须是映射", where=where)
    unknown = set(value) - PLOT_KEYS
    if unknown:
        raise ValidationError(
            f"{where} 含未知字段 {sorted(unknown)}；允许 {sorted(PLOT_KEYS)}",
            where=where,
        )
    result: dict[str, Any] = {}
    if "window" in value:
        window = value["window"]
        if not isinstance(window, Mapping):
            raise ValidationError(f"{where}.window 必须是映射", where=where)
        unknown = set(window) - set("xyz")
        if unknown:
            raise ValidationError(
                f"{where}.window 含未知轴 {sorted(unknown)}；允许 x/y/z", where=where
            )
        parsed_window = {}
        for axis, bounds in window.items():
            parsed_window[str(axis)] = _finite_pair(
                bounds, f"{where}.window.{axis}"
            )
        result["window"] = parsed_window
    if "layout" in value:
        layout = value["layout"]
        if not isinstance(layout, Mapping):
            raise ValidationError(f"{where}.layout 必须是映射", where=where)
        unknown = set(layout) - {"ncols"}
        if unknown:
            raise ValidationError(
                f"{where}.layout 含未知字段 {sorted(unknown)}；允许 ['ncols']",
                where=where,
            )
        if "ncols" in layout:
            ncols = layout["ncols"]
            if isinstance(ncols, bool) or not isinstance(ncols, int) or ncols < 1:
                raise ValidationError(
                    f"{where}.layout.ncols 必须是正整数，收到 {ncols!r}",
                    where=where,
                )
            result["layout"] = {"ncols": ncols}
    if "palette" in value:
        result["palette"] = list(resolve_palette(value["palette"], f"{where}.palette"))
    if "cbar_width" in value:
        width = value["cbar_width"]
        if (
            not isinstance(width, str)
            or not width.endswith("%")
            or not width[:-1].replace(".", "", 1).isdigit()
            or float(width[:-1]) <= 0
        ):
            raise ValidationError(
                f"{where}.cbar_width 必须是正百分比字符串，如 '6%'",
                where=where,
            )
        result["cbar_width"] = width
    if "cbar_frame" in value:
        frame = value["cbar_frame"]
        if not isinstance(frame, bool):
            raise ValidationError(f"{where}.cbar_frame 必须是布尔值", where=where)
        result["cbar_frame"] = frame
    if "size" in value:
        result["size"] = _finite_pair(value["size"], f"{where}.size", positive=True)
    for key in ("xlim", "ylim"):
        if key in value:
            result[key] = _finite_pair(value[key], f"{where}.{key}")
    for key in TEXT_KEYS:
        if key in value:
            result[key] = parse_text(value[key], f"{where}.{key}")
    if "rc" in value:
        rc = value["rc"]
        if not isinstance(rc, Mapping):
            raise ValidationError(f"{where}.rc 必须是映射", where=where)
        parsed_rc = {}
        for key, item in rc.items():
            if not isinstance(key, str) or key not in rcParams:
                raise ValidationError(
                    f"{where}.rc 含 Matplotlib 不认识的键 {key!r}", where=where
                )
            if key == "backend":
                raise ValidationError(f"{where}.rc 不允许修改 backend", where=where)
            if isinstance(item, (str, bool, int, float)) or item is None:
                parsed_rc[str(key)] = item
            elif isinstance(item, (list, tuple)) and all(
                isinstance(entry, (str, int, float)) for entry in item
            ):
                parsed_rc[str(key)] = list(item)
            else:
                raise ValidationError(
                    f"{where}.rc.{key} 的值必须是标量或标量列表", where=where
                )
        result["rc"] = parsed_rc
    return result


def merge_plot(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in ("window", "rc", "layout") and isinstance(value, Mapping):
            current = dict(merged.get(key) or {})
            current.update(value)
            merged[key] = current
        else:
            merged[key] = value
    return merged
