"""传给分析模块的运行上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import MDAnalysis as mda

from ..config.geometry import FrameGeometry, GeometryWindow
from ..config.registry import PlanItem
from ..config.system import Group, SystemConfig
from ..plot import plotutil


@dataclass
class RunContext:
    """传给分析模块的上下文。"""

    system: SystemConfig
    plan_item: PlanItem
    universe: mda.Universe
    groups: Mapping[str, Group]
    start: int
    stop: int
    lang: str
    dpi: int
    annotate: bool
    labels: plotutil.Labels
    figure_sizes: Mapping[str, tuple[float, float]]
    view: str
    selection_frame: int
    warnings: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    geometry: FrameGeometry | None = None
    geometry_window: GeometryWindow | None = None

    @property
    def params(self) -> Mapping[str, Any]:
        return self.plan_item.params

    @property
    def annotations(self) -> tuple[dict[str, Any], ...]:
        """该条分析上的图内标注声明。"""
        return self.plan_item.annotations

    @property
    def frame_dt_ps(self) -> float:
        return self.system.dump_every * self.system.dt_ps

    def label(self, key: str, **fmt: Any) -> str:
        return self.labels(key, **fmt)

    def size(self, name: str = "single") -> tuple[float, float]:
        return self.figure_sizes.get(name, (3.5, 2.6))

    def window(self, axis: str) -> tuple[float, float] | None:
        """该轴的显示窗口；未设置时为 None。"""
        return self.plan_item.window.get(axis)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def annotation(self) -> str:
        """帧窗口与关键参数，供 --annotate 使用。"""
        # 帧窗口左闭右开；标注里显示实际用到的最后一帧，时间换算为 ns
        t0 = self.start * self.frame_dt_ps / 1000.0
        t1 = max(self.stop - 1, 0) * self.frame_dt_ps / 1000.0
        window = self.label(
            "window", start=self.start, stop=self.stop - 1, t0=t0, t1=t1
        )
        params = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{window}\n{params}"

