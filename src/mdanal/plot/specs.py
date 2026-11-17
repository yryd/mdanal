"""绘图数据规格：图元、逻辑系列与 Panel 请求。

这里只描述“画什么”，不创建 Figure，也不决定面板布局。
插件负责把计算结果组织成这些对象；平台负责选择、排版和保存。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass
class Curve:
    """一条 x–y 曲线。不持有 Figure/Axes。"""

    x: np.ndarray
    y: np.ndarray
    label: str = ""
    unit: str = ""
    color: str | None = None
    linestyle: str = "-"
    linewidth: float = 1.2
    source: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        if self.x.shape != self.y.shape:
            raise ValueError(f"Curve x/y 形状不一致：{self.x.shape} vs {self.y.shape}")
        if self.x.ndim != 1:
            raise ValueError(f"Curve 必须是一维，收到 shape={self.x.shape}")


@dataclass
class Field:
    """二维场；density 的投影网格使用。"""

    x: np.ndarray
    y: np.ndarray
    values: np.ndarray
    label: str = ""
    unit: str = ""
    colorbar_label: str = ""
    vmin: float | None = None
    vmax: float | None = None
    cmap: str | None = None
    source: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        self.values = np.asarray(self.values, dtype=float)
        if self.values.ndim != 2:
            raise ValueError(f"Field values 必须是二维，收到 shape={self.values.shape}")


@dataclass
class Series:
    """一个逻辑量的曲线集合；是选择结果，不是固定结构层。"""

    name: str
    curves: Sequence[Curve] = field(default_factory=tuple)
    fields: Sequence[Field] = field(default_factory=tuple)
    label: str = ""
    unit: str = ""
    legend_title: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.curves = tuple(self.curves)
        self.fields = tuple(self.fields)
        if not self.curves and not self.fields:
            raise ValueError(f"Series {self.name!r} 至少需要一个 Curve 或 Field")
        if self.curves and self.fields:
            raise ValueError(f"Series {self.name!r} 不能同时含 Curve 和 Field")


@dataclass
class PanelRequest:
    """某个插件 panel 模板 + 选中的数据系列。

    recipe 通常是插件名；插件用 render_panel(ctx, request) 把它渲染成一个 Panel。
    """

    recipe: str
    series: Sequence[Series]
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    options: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.series = tuple(self.series)
        if not self.series:
            raise ValueError("PanelRequest 至少需要一个 Series")
