"""每帧盒几何：原点、盒矩阵、边界类型与周期信息。

这一层只读 LAMMPS dump 的几何表头，不读原子坐标，也不依赖 MDAnalysis 的
Reader 状态。坐标适配器（views）和插件能力检查都以这里的每帧事实为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from ..errors import ValidationError


def _as_cell(values: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple(float(v) for v in row) for row in values)


def _parse_boundary(tokens: Sequence[str]) -> tuple[str, str, str]:
    if len(tokens) >= 3:
        return tuple(str(token).lower() for token in tokens[-3:])  # type: ignore[return-value]
    return ("unknown", "unknown", "unknown")


@dataclass(frozen=True)
class FrameGeometry:
    """一帧的盒事实；原点是实验室坐标，cell 行向量为晶格向量。"""

    frame: int
    origin: tuple[float, float, float]
    cell: tuple[tuple[float, float, float], ...]
    boundary_types: tuple[str, str, str] = ("unknown", "unknown", "unknown")

    @property
    def cell_array(self) -> np.ndarray:
        return np.asarray(self.cell, dtype=float)

    @property
    def pbc(self) -> tuple[bool, bool, bool]:
        return tuple(token.startswith("p") for token in self.boundary_types)  # type: ignore[return-value]

    @property
    def pbc_known(self) -> bool:
        known = {"p", "f", "s", "m"}
        return all(token[:1] in known for token in self.boundary_types)

    @property
    def lengths(self) -> tuple[float, float, float]:
        return tuple(float(np.linalg.norm(row)) for row in self.cell)  # type: ignore[return-value]

    @property
    def volume(self) -> float:
        return float(abs(np.linalg.det(self.cell_array)))

    @property
    def orthorhombic(self) -> bool:
        cell = self.cell_array
        scale = max(float(np.max(np.abs(cell))), 1.0)
        return bool(np.allclose(cell, np.diag(np.diag(cell)), rtol=0.0, atol=1e-8 * scale))

    def to_dict(self) -> dict:
        return {
            "frame": self.frame,
            "origin": list(self.origin),
            "cell": [list(row) for row in self.cell],
            "boundary_types": list(self.boundary_types),
            "pbc": list(self.pbc),
            "pbc_known": self.pbc_known,
            "orthorhombic": self.orthorhombic,
            "lengths": list(self.lengths),
            "volume": self.volume,
        }


@dataclass(frozen=True)
class GeometryWindow:
    """一个实际分析窗口的几何摘要，不持有逐帧数组。"""

    start: int
    stop: int
    reference: FrameGeometry
    frames: int
    orthorhombic: bool
    pbc: tuple[bool, bool, bool]
    pbc_all: tuple[bool, bool, bool]
    pbc_known: bool
    full_periodic: bool
    origin_changed: bool
    cell_changed: bool
    pbc_changed: bool
    min_length: float

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "stop": self.stop,
            "frames": self.frames,
            "reference": self.reference.to_dict(),
            "orthorhombic": self.orthorhombic,
            "pbc": list(self.pbc),
            "pbc_all": list(self.pbc_all),
            "pbc_known": self.pbc_known,
            "full_periodic": self.full_periodic,
            "origin_changed": self.origin_changed,
            "cell_changed": self.cell_changed,
            "pbc_changed": self.pbc_changed,
            "min_length": self.min_length,
        }


@dataclass(frozen=True)
class GeometryTrack:
    """整条（可多段拼接的）轨迹的每帧几何。"""

    frames: tuple[FrameGeometry, ...]

    def __len__(self) -> int:
        return len(self.frames)

    def frame(self, index: int) -> FrameGeometry:
        try:
            return self.frames[index]
        except IndexError as exc:
            raise ValidationError(
                f"帧号 {index} 超出几何范围 0…{len(self.frames) - 1}"
            ) from exc

    def window(self, start: int, stop: int) -> GeometryWindow:
        if not (0 <= start < stop <= len(self.frames)):
            raise ValidationError(
                f"几何窗口 [{start}, {stop}) 超出范围 0…{len(self.frames)}"
            )
        selected = self.frames[start:stop]
        reference = selected[0]
        pbc = reference.pbc
        pbc_all = tuple(
            all(frame.pbc[axis] for frame in selected) for axis in range(3)
        )
        orthorhombic = all(frame.orthorhombic for frame in selected)
        pbc_known = all(frame.pbc_known for frame in selected)
        full_periodic = all(pbc_all)
        origin_changed = any(not np.allclose(frame.origin, reference.origin) for frame in selected[1:])
        cell_changed = any(
            not np.allclose(frame.cell, reference.cell) for frame in selected[1:]
        )
        pbc_changed = any(frame.pbc != pbc for frame in selected[1:])
        min_length = min(min(frame.lengths) for frame in selected)
        return GeometryWindow(
            start=start,
            stop=stop,
            reference=reference,
            frames=len(selected),
            orthorhombic=orthorhombic,
            pbc=pbc,
            pbc_all=pbc_all,
            pbc_known=pbc_known,
            full_periodic=full_periodic,
            origin_changed=origin_changed,
            cell_changed=cell_changed,
            pbc_changed=pbc_changed,
            min_length=float(min_length),
        )


# --------------------------------------------------------------------------- #
# 读取 dump 几何表头
# --------------------------------------------------------------------------- #


def _cell_from_bounds(
    bounds: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """返回 (origin, row0, row1, row2)，按 LAMMPS/MDAnalysis 的包围盒约定。"""
    rows = [list(map(float, row)) for row in bounds]
    triclinic = any(len(row) >= 3 for row in rows)
    if triclinic:
        xlo_bound, xhi_bound, xy = (rows[0] + [0.0, 0.0, 0.0])[:3]
        ylo_bound, yhi_bound, xz = (rows[1] + [0.0, 0.0, 0.0])[:3]
        zlo, zhi, yz = (rows[2] + [0.0, 0.0, 0.0])[:3]
        xlo = xlo_bound - min(0.0, xy, xz, xy + xz)
        xhi = xhi_bound - max(0.0, xy, xz, xy + xz)
        ylo = ylo_bound - min(0.0, yz)
        yhi = yhi_bound - max(0.0, yz)
        origin = (float(xlo), float(ylo), float(zlo))
        cell = (
            (float(xhi - xlo), 0.0, 0.0),
            (float(xy), float(yhi - ylo), 0.0),
            (float(xz), float(yz), float(zhi - zlo)),
        )
        return origin, cell[0], cell[1], cell[2]
    origin = (float(rows[0][0]), float(rows[1][0]), float(rows[2][0]))
    cell = (
        (float(rows[0][1] - rows[0][0]), 0.0, 0.0),
        (0.0, float(rows[1][1] - rows[1][0]), 0.0),
        (0.0, 0.0, float(rows[2][1] - rows[2][0])),
    )
    return origin, cell[0], cell[1], cell[2]


def _read_geometry_file(path: Path, offset: int) -> tuple[list[FrameGeometry], int]:
    frames: list[FrameGeometry] = []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValidationError(f"无法读取轨迹几何：{path}：{exc}", where=str(path)) from exc

    with handle:
        while True:
            line = handle.readline()
            if not line:
                break
            if not line.startswith("ITEM: TIMESTEP"):
                continue
            # 每帧必须按固定顺序出现这三块表头；TIMESTEP 后一行是步号。
            handle.readline()
            number_line = handle.readline()
            if not number_line.startswith("ITEM: NUMBER OF ATOMS"):
                raise ValidationError(
                    "dump 帧缺少 ITEM: NUMBER OF ATOMS", where=str(path)
                )
            try:
                n_atoms = int(handle.readline())
            except ValueError as exc:
                raise ValidationError("dump 的原子数不是整数", where=str(path)) from exc
            box_line = handle.readline()
            if not box_line.startswith("ITEM: BOX BOUNDS"):
                raise ValidationError(
                    "dump 帧缺少 ITEM: BOX BOUNDS", where=str(path)
                )
            tokens = box_line.split()[3:]
            bounds = []
            for _ in range(3):
                row = handle.readline().split()
                if len(row) < 2:
                    raise ValidationError("dump 的 BOX BOUNDS 行格式错误", where=str(path))
                bounds.append([float(value) for value in row])
            origin, row0, row1, row2 = _cell_from_bounds(bounds)
            frames.append(
                FrameGeometry(
                    frame=offset + len(frames),
                    origin=origin,
                    cell=(row0, row1, row2),
                    boundary_types=_parse_boundary(tokens),
                )
            )
            atom_header = handle.readline()
            if not atom_header.startswith("ITEM: ATOMS"):
                raise ValidationError(
                    "dump 帧缺少 ITEM: ATOMS 表头", where=str(path)
                )
            for _ in range(n_atoms):
                if not handle.readline():
                    raise ValidationError("dump 在原子块中途结束", where=str(path))
    return frames, offset + len(frames)


def read_geometry(paths: Iterable[Path]) -> GeometryTrack:
    """读取全部路径的每帧几何，帧号按拼接后的全局序号编号。"""
    frames: list[FrameGeometry] = []
    offset = 0
    for path in paths:
        part, offset = _read_geometry_file(Path(path), offset)
        if not part:
            raise ValidationError(
                "轨迹里没有可读的几何表头（BOX BOUNDS）", where=str(path)
            )
        frames.extend(part)
    return GeometryTrack(tuple(frames))


# --------------------------------------------------------------------------- #
# 坐标契约
# --------------------------------------------------------------------------- #


def raw_to_local(
    raw: np.ndarray, convention: str, geometry: FrameGeometry
) -> np.ndarray:
    """把 MDAnalysis DumpReader 的原始位置还原成盒局部笛卡尔坐标。

    当前 MDAnalysis 对 x/xu 返回 ``r - o``，对 xs/xsu 返回 ``sH - o``；
    必须按约定分别还原，不能统一加原点。
    """
    values = np.asarray(raw, dtype=float)
    origin = np.asarray(geometry.origin, dtype=float)
    if convention in ("scaled", "scaled_unwrapped"):
        return values + origin
    if convention in ("unscaled", "unwrapped"):
        return values.copy()
    raise ValidationError(f"未知的坐标约定 {convention!r}")


def local_to_lab(local: np.ndarray, geometry: FrameGeometry) -> np.ndarray:
    return np.asarray(local, dtype=float) + np.asarray(geometry.origin, dtype=float)


def local_to_fractional(local: np.ndarray, geometry: FrameGeometry) -> np.ndarray:
    cell = geometry.cell_array
    try:
        inverse = np.linalg.inv(cell)
    except np.linalg.LinAlgError as exc:
        raise ValidationError("盒矩阵不可逆，无法做坐标变换") from exc
    return np.asarray(local, dtype=float) @ inverse


def fractional_to_local(fractional: np.ndarray, geometry: FrameGeometry) -> np.ndarray:
    return np.asarray(fractional, dtype=float) @ geometry.cell_array


def wrap_local(local: np.ndarray, geometry: FrameGeometry) -> np.ndarray:
    """只沿周期方向折回；非周期方向保持原值。"""
    values = np.asarray(local, dtype=float).copy()
    pbc = geometry.pbc
    if not any(pbc):
        return values
    fractional = local_to_fractional(values, geometry)
    for axis, periodic in enumerate(pbc):
        if periodic:
            fractional[:, axis] -= np.floor(fractional[:, axis])
    return fractional_to_local(fractional, geometry)


def lab_to_local(lab: np.ndarray, geometry: FrameGeometry) -> np.ndarray:
    return np.asarray(lab, dtype=float) - np.asarray(geometry.origin, dtype=float)
