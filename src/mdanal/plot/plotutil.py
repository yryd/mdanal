"""绘图适配层：把运行上下文（ctx）翻译成公共绘图层（chart）的调用。

画图能力在 `chart`；这里只保留与体系相关的部分——标签查表、窗口裁剪、画布档位，
以及 `runner` 用到的样式与保存入口。
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from . import chart
from ..errors import MdanalError

def apply_style() -> None:
    chart.apply_style()


def save(fig, path, dpi: int):
    return chart.save(fig, path, dpi)


def limit(ax, axis: str, bounds: tuple[float, float] | None) -> None:
    """按窗口裁剪坐标轴范围；落在数据范围之外的边界忽略。"""
    if not bounds:
        return
    low, high = clip_window(bounds, data_range(ax, axis))
    if high > low:
        getattr(ax, f"set_{axis}lim")(low, high)


def data_range(ax, axis: str) -> tuple[float, float]:
    """该轴上美术对象的数据范围。"""
    bounds = ax.dataLim
    low, high = (bounds.x0, bounds.x1) if axis == "x" else (bounds.y0, bounds.y1)
    if np.isfinite(low) and np.isfinite(high):
        return float(low), float(high)
    return getattr(ax, f"get_{axis}lim")()


def clip_window(
    bounds: tuple[float, float] | None, data: tuple[float, float]
) -> tuple[float, float]:
    """把窗口边界裁到数据范围内；整个窗口落在数据之外时返回数据范围。"""
    low, high = data
    if not bounds or high <= low:
        return low, high
    clipped_low = bounds[0] if low <= bounds[0] <= high else low
    clipped_high = bounds[1] if low <= bounds[1] <= high else high
    return (clipped_low, clipped_high) if clipped_high > clipped_low else (low, high)


class Labels:
    """标签解析：分析模块的 LABELS → 全局（labels.yaml）；缺键报错。"""

    def __init__(
        self,
        analysis: Mapping[str, str] | None = None,
        common: Mapping[str, str] | None = None,
    ):
        self._analysis = dict(analysis or {})
        self._common = dict(common or {})

    def __call__(self, key: str, **fmt: Any) -> str:
        if key in self._analysis:
            text = self._analysis[key]
        elif key in self._common:
            text = self._common[key]
        else:
            raise MdanalError(
                f"缺少标签 {key!r}；请在该分析的 LABELS 或 labels.yaml 中补齐"
            )
        return text.format(**fmt) if fmt else text
