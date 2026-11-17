"""MDAnalysis 轨迹的坐标适配器。

只负责把 Reader 的原始位置变成两种公开视图之一；不做科学归一化。
"""

from __future__ import annotations

import numpy as np

from .geometry import GeometryTrack, local_to_lab, raw_to_local, wrap_local


class InBoxView:
    """盒局部笛卡尔坐标：只沿周期方向折回。"""

    def __init__(self, geometry: GeometryTrack, convention: str):
        self.geometry = geometry
        self.convention = convention

    def __call__(self, ts):
        geometry = self.geometry.frame(int(ts.frame))
        local = raw_to_local(np.asarray(ts.positions), self.convention, geometry)
        ts.positions = wrap_local(local, geometry)
        return ts


class LabView:
    """实验室绝对笛卡尔坐标，不做周期折回。"""

    def __init__(self, geometry: GeometryTrack, convention: str):
        self.geometry = geometry
        self.convention = convention

    def __call__(self, ts):
        geometry = self.geometry.frame(int(ts.frame))
        local = raw_to_local(np.asarray(ts.positions), self.convention, geometry)
        ts.positions = local_to_lab(local, geometry)
        return ts
