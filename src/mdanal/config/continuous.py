"""连续坐标视图：把包裹坐标逐帧展开；回退/跳帧时从 0 重放。

新路径使用每帧几何（原点、盒矩阵、PBC），输出实验室连续坐标；旧的
``ContinuousView(raw_universe)`` 调用仍保留，用于只测展开逻辑的单元测试。
"""

from __future__ import annotations

import numpy as np

from ..errors import ValidationError
from .geometry import GeometryTrack, raw_to_local


class ContinuousView:
    """有界状态的逐帧展开。

    MDAnalysis 的 NoJump 也做同样的事，但它假设调用者顺序读取，并且把状态藏在
    transformation 里。这里显式保存状态：重复读同一帧返回缓存；向后或跳帧时从
    第 0 帧重放到目标帧，保证 section/多分析/读盘顺序变化时结果一致。
    """

    def __init__(self, raw_universe, geometry: GeometryTrack | None = None,
                 convention: str | None = None):
        self.raw = raw_universe
        self.geometry = geometry
        self.convention = convention
        if geometry is not None and convention is None:
            raise ValueError("带 geometry 的 ContinuousView 需要坐标约定")
        self._frame: int | None = None
        self._reduced: np.ndarray | None = None
        self._cached_frame: int | None = None
        self._cached: np.ndarray | None = None
        self._reference_cell: np.ndarray | None = None
        # 旧式调用（测试里 raw 与目标 Universe 相同）会把展开结果写回 raw；
        # 缓存首次读到的原始位置，保证回退时可以重放。
        self._raw_cache: dict[int, np.ndarray] = {}

    def __call__(self, ts):
        frame = int(ts.frame)
        if frame == self._cached_frame and self._cached is not None:
            ts.positions = self._cached
            return ts
        if frame == 0:
            self._check_cell(0)
            self._frame = 0
            positions = self._positions(0)
            self._reduced = self._fractional(positions, 0)
            self._cached_frame = 0
            self._cached = positions.copy() if self.geometry is not None else ts.positions.copy()
            if self.geometry is not None:
                ts.positions = self._cached
            return ts
        if self._frame is not None and frame == self._frame + 1:
            self._advance(frame)
        else:
            self._replay(frame)
        ts.positions = self._cached
        return ts

    def _positions(self, frame: int) -> np.ndarray:
        if self.geometry is None and frame in self._raw_cache:
            return self._raw_cache[frame]
        self.raw.trajectory[frame]
        raw = np.asarray(self.raw.trajectory.ts.positions, dtype=np.float64).copy()
        if self.geometry is None:
            self._raw_cache[frame] = raw
            return raw
        geometry = self.geometry.frame(frame)
        local = raw_to_local(raw, self.convention, geometry)
        return local + np.asarray(geometry.origin, dtype=float)

    def _box(self, frame: int) -> np.ndarray:
        self.raw.trajectory[frame]
        if self.geometry is None:
            return np.asarray(self.raw.trajectory.ts.triclinic_dimensions, dtype=float)
        return self.geometry.frame(frame).cell_array

    def _origin(self, frame: int) -> np.ndarray:
        if self.geometry is None:
            return np.zeros(3, dtype=float)
        return np.asarray(self.geometry.frame(frame).origin, dtype=float)

    def _pbc(self, frame: int) -> tuple[bool, bool, bool]:
        if self.geometry is None:
            return (True, True, True)
        return self.geometry.frame(frame).pbc

    def _fractional(self, positions: np.ndarray, frame: int) -> np.ndarray:
        box = self._box(frame)
        try:
            inverse = np.linalg.inv(box)
        except np.linalg.LinAlgError as exc:
            raise ValidationError("盒矩阵不可逆，无法展开连续坐标") from exc
        return (np.asarray(positions, dtype=float) - self._origin(frame)) @ inverse

    def _check_cell(self, frame: int) -> None:
        if self.geometry is None:
            return
        cell = self._box(frame)
        if self._reference_cell is None:
            self._reference_cell = cell.copy()
        elif not np.allclose(cell, self._reference_cell, rtol=1e-8, atol=1e-8):
            raise ValidationError(
                "连续坐标视图要求分析窗口内盒矩阵不变；"
                "当前轨迹的盒在变化，请改用 x/xu 已在文件里展开的坐标，"
                "或先把窗口裁到固定盒。"
            )

    def _advance(self, frame: int) -> None:
        self._check_cell(frame)
        positions = self._positions(frame)
        current = self._fractional(positions, frame)
        reduced = current.copy()
        pbc = self._pbc(frame)
        for axis, periodic in enumerate(pbc):
            if periodic:
                reduced[:, axis] -= np.round(current[:, axis] - self._reduced[:, axis])
        self._reduced = reduced
        self._frame = frame
        self._cached_frame = frame
        self._cached = self._to_positions(reduced, frame)

    def _replay(self, target: int) -> None:
        self._check_cell(0)
        self.raw.trajectory[0]
        reduced = self._fractional(self._positions(0), 0)
        for frame in range(1, target + 1):
            self._check_cell(frame)
            current = self._fractional(self._positions(frame), frame)
            previous = reduced.copy()
            pbc = self._pbc(frame)
            for axis, periodic in enumerate(pbc):
                if periodic:
                    reduced[:, axis] = current[:, axis] - np.round(
                        current[:, axis] - previous[:, axis]
                    )
                else:
                    reduced[:, axis] = current[:, axis]
        self._reduced = reduced
        self._frame = target
        self._cached_frame = target
        self._cached = self._to_positions(reduced, target)

    def _to_positions(self, reduced: np.ndarray, frame: int) -> np.ndarray:
        if self.geometry is None:
            return reduced @ self._box(frame)
        return self._origin(frame) + reduced @ self._box(frame)
