"""Figure-first 的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence

PanelKind = Literal["curve", "field", "bars"]


@dataclass(frozen=True)
class PanelProduct:
    """一个图产品；build 必须恰好返回一个 Panel。"""

    id: str
    kind: PanelKind
    requires: tuple[str, ...]
    build: Callable[[Any, "PanelSource"], Any]
    compare: Callable[[Any, Sequence["PanelSource"]], Any] | None = None
    curve_request: Callable[[Any, "PanelSource"], Any] | None = None
    default: bool = False
    help: str = ""
    requires_derive: tuple[str, ...] = ()


@dataclass(frozen=True)
class PanelSource:
    """一个 Panel 的数据来源；platform 负责填充。"""

    source: str
    label: str
    params: Mapping[str, Any]
    meta: Mapping[str, Any]
    tables: Mapping[str, Any]
    start: int
    stop: int
    frame_dt_ps: float
    selection_frame: int
    shift: tuple[float, float, float]


@dataclass(frozen=True)
class PanelRef:
    """配置里的一个单 Panel 引用。"""

    source: str
    pack: str
    product: str
    select: Mapping[str, str] = field(default_factory=dict)
    compute: Mapping[str, Any] = field(default_factory=dict)
    derive: Mapping[str, Any] = field(default_factory=dict)
    section: tuple[int, int] | None = None
    plot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CurveSource:
    source: str
    label: str
    select: Mapping[str, str] = field(default_factory=dict)
    compute: Mapping[str, Any] = field(default_factory=dict)
    derive: Mapping[str, Any] = field(default_factory=dict)
    section: tuple[int, int] | None = None


@dataclass(frozen=True)
class CompareSpec:
    """同一曲线产品在多个来源上的比较；最终产出一个 Panel。"""

    pack: str
    product: str
    sources: tuple[CurveSource, ...]
    select: Mapping[str, str] = field(default_factory=dict)
    compute: Mapping[str, Any] = field(default_factory=dict)
    derive: Mapping[str, Any] = field(default_factory=dict)
    section: tuple[int, int] | None = None
    plot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StackSpec:
    """同一曲线产品在多个来源上堆叠；最终产出一个 Panel。"""

    pack: str
    product: str
    sources: tuple[CurveSource, ...]
    select: Mapping[str, str] = field(default_factory=dict)
    compute: Mapping[str, Any] = field(default_factory=dict)
    derive: Mapping[str, Any] = field(default_factory=dict)
    section: tuple[int, int] | None = None
    plot: Mapping[str, Any] = field(default_factory=dict)


FigureItem = PanelRef | CompareSpec | StackSpec


@dataclass(frozen=True)
class FigureSpec:
    """一张最终图：若干 Panel 项 + ncols。"""

    name: str
    items: tuple[FigureItem, ...]
    ncols: int = 1
    title: str | Mapping[str, str] | None = None


@dataclass(frozen=True)
class FigurePack:
    """一个图包的静态定义。"""

    name: str
    module: str
    slots: tuple[str, ...]
    params: Mapping[str, Mapping[str, Any]]
    labels: Mapping[str, Mapping[str, str]]
    products: Mapping[str, PanelProduct]
    compute: Callable[[Any], Mapping[str, Any]]
    derive: Callable[[Any, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None
    validate_derive: Callable[[Mapping[str, Any]], None] | None = None
    coordinates: str = "any"
    geometry: Mapping[str, Any] = field(default_factory=dict)
    kernel_pbc: tuple[bool, bool, bool] | str = "per_frame"
    note: str = ""

    @property
    def default_product(self) -> str:
        for key, product in self.products.items():
            if product.default:
                return key
        return next(iter(self.products))
