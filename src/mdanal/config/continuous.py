"""连续坐标视图：把包裹坐标逐帧展开；回退/跳帧时从 0 重放。"""

from __future__ import annotations

import numpy as np


class ContinuousView:
    """有界状态的逐帧最小镜像展开。

    MDAnalysis 的 NoJump 也做同样的事，但它假设调用者顺序读取，并且把状态藏在
    transformation 里。这里显式保存状态：重复读同一帧返回缓存；向后或跳帧时从
    第 0 帧重放到目标帧，保证 section/多分析/读盘顺序变化时结果一致。
    """

    def __init__(self, raw_universe):
        self.raw = raw_universe
        self._frame: int | None = None
        self._reduced: np.ndarray | None = None
        self._cached_frame: int | None = None
        self._cached: np.ndarray | None = None

    def __call__(self, ts):
        frame = int(ts.frame)
        if frame == self._cached_frame and self._cached is not None:
            ts.positions = self._cached
            return ts
        if frame == 0:
            self._frame = 0
            self._reduced = self._positions(0) @ self._inverse(0)
            self._cached_frame = 0
            self._cached = ts.positions.copy()
            return ts
        if self._frame is not None and frame == self._frame + 1:
            self._advance(frame)
        else:
            self._replay(frame)
        ts.positions = self._cached
        return ts

    def _positions(self, frame: int) -> np.ndarray:
        self.raw.trajectory[frame]
        return np.asarray(self.raw.trajectory.ts.positions, dtype=np.float64)

    def _inverse(self, frame: int) -> np.ndarray:
        self.raw.trajectory[frame]
        return np.linalg.inv(self.raw.trajectory.ts.triclinic_dimensions)

    def _advance(self, frame: int) -> None:
        self.raw.trajectory[frame]
        box = self.raw.trajectory.ts.triclinic_dimensions
        current = np.asarray(self.raw.trajectory.ts.positions, dtype=np.float64) @ np.linalg.inv(box)
        reduced = current - np.round(current - self._reduced)
        self._reduced = reduced
        self._frame = frame
        self._cached_frame = frame
        self._cached = reduced @ box

    def _replay(self, target: int) -> None:
        self.raw.trajectory[0]
        box = self.raw.trajectory.ts.triclinic_dimensions
        reduced = np.asarray(self.raw.trajectory.ts.positions, dtype=np.float64) @ np.linalg.inv(box)
        for frame in range(1, target + 1):
            self.raw.trajectory[frame]
            box = self.raw.trajectory.ts.triclinic_dimensions
            current = np.asarray(self.raw.trajectory.ts.positions, dtype=np.float64) @ np.linalg.inv(box)
            reduced = current - np.round(current - reduced)
        self._reduced = reduced
        self._frame = target
        self._cached_frame = target
        self._cached = reduced @ box
