"""呈现设置校验：system.yaml 的 analyses[].plot 与 replot 配置共用。"""

from __future__ import annotations

from typing import Any, Mapping

from matplotlib import rcParams

from ..errors import ValidationError

PLOT_KEYS = {"window", "size", "xlim", "ylim", "title", "xlabel", "ylabel", "rc"}
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
        if key in ("window", "rc") and isinstance(value, Mapping):
            current = dict(merged.get(key) or {})
            current.update(value)
            merged[key] = current
        else:
            merged[key] = value
    return merged
