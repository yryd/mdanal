"""绘图上下文：只含数据表、快照信息和呈现设置，不持有轨迹或原子组。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..plot import plotutil


@dataclass
class PlotContext:
    """传给分析 `figures()` 的纯绘图上下文。"""

    params: Mapping[str, Any]
    meta: Mapping[str, Any]
    extras: Mapping[str, Any]
    start: int
    stop: int
    frame_dt_ps: float
    selection_frame: int
    shift: tuple[float, float, float]
    lang: str
    dpi: int
    annotate: bool
    annotations: tuple[dict[str, Any], ...]
    labels: plotutil.Labels
    figure_sizes: Mapping[str, tuple[float, float]]
    windows: Mapping[str, tuple[float, float]]
    size_override: tuple[float, float] | None = None
    plot: Mapping[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def label(self, key: str, **fmt: Any) -> str:
        return self.labels(key, **fmt)

    def size(self, name: str = "single") -> tuple[float, float]:
        if self.size_override is not None:
            return self.size_override
        return self.figure_sizes.get(name, (3.5, 2.6))

    def window(self, axis: str) -> tuple[float, float] | None:
        return self.windows.get(axis)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def annotation(self) -> str:
        """帧窗口与关键参数，供自动说明使用；不读取轨迹。"""
        t0 = self.start * self.frame_dt_ps / 1000.0
        t1 = max(self.stop - 1, 0) * self.frame_dt_ps / 1000.0
        window = self.label(
            "window", start=self.start, stop=self.stop - 1, t0=t0, t1=t1
        )
        params = ", ".join(f"{key}={value}" for key, value in self.params.items())
        return f"{window}\n{params}"
