"""质心 MSD 基础计算；不包含拟合和绘图。"""

from __future__ import annotations

import numpy as np
import pandas as pd

AXIS_SETS = {
    "xyz": (0, 1, 2),
    "xy": (0, 1),
    "xz": (0, 2),
    "yz": (1, 2),
    "x": (0,),
    "y": (1,),
    "z": (2,),
}


def _com_trajectory(atoms, grouping: str, start: int, stop: int) -> np.ndarray:
    """按 atoms 或 residue 求每帧质心；返回 (frames, units, 3)。"""
    if grouping == "atoms":
        inverse = np.arange(atoms.n_atoms, dtype=int)
    elif grouping == "residues":
        try:
            residues = np.asarray(atoms.resindices)
        except Exception:
            residues = np.arange(atoms.n_atoms, dtype=int)
        _, inverse = np.unique(residues, return_inverse=True)
    else:
        raise ValueError(f"未知的 msd grouping：{grouping!r}")

    try:
        masses = np.asarray(atoms.masses, dtype=float)
    except Exception:
        masses = np.ones(atoms.n_atoms, dtype=float)
    if masses.size != atoms.n_atoms or not np.all(np.isfinite(masses)):
        masses = np.ones(atoms.n_atoms, dtype=float)
    mass_by_unit = np.bincount(inverse, weights=masses)
    if np.any(mass_by_unit <= 0):
        raise ValueError("存在总质量为 0 的 MSD 统计单元")

    n_units = len(mass_by_unit)
    com = np.empty((stop - start, n_units, 3), dtype=float)
    universe = atoms.universe
    for offset, frame in enumerate(range(start, stop)):
        universe.trajectory[frame]
        positions = np.asarray(atoms.positions, dtype=float)
        for axis in range(3):
            numerator = np.bincount(inverse, weights=masses * positions[:, axis])
            com[offset, :, axis] = numerator / mass_by_unit
    return com


def _msd_from_com(com: np.ndarray, msd_type: str, fft: bool = True) -> np.ndarray:
    """对质心轨迹求时间平均 MSD；fft=True 用 FFT 自相关。"""
    axes = AXIS_SETS[msd_type]
    pos = com[..., axes]
    # 固定参考位置改善大绝对坐标下的 FFT 抵消；不能逐帧减质心。
    pos = pos - pos[0]
    n_frames = len(pos)
    if not fft:
        msd = np.empty(n_frames, dtype=float)
        for lag in range(n_frames):
            delta = pos[lag:] - pos[: n_frames - lag]
            msd[lag] = float(np.mean(np.sum(delta**2, axis=-1)))
        return msd

    n_fft = 1 << (2 * n_frames - 1).bit_length()
    rsq = np.sum(pos**2, axis=(1, 2)) / pos.shape[1]
    acf_sum = np.zeros(n_frames, dtype=float)
    for axis in range(pos.shape[2]):
        spectrum = np.fft.rfft(pos[..., axis], n=n_fft, axis=0)
        acf = np.fft.irfft(spectrum * spectrum.conj(), n=n_fft, axis=0)[:n_frames]
        acf_sum += acf.mean(axis=1)
    counts = n_frames - np.arange(n_frames, dtype=float)
    correlation = acf_sum / counts

    msd = np.empty(n_frames, dtype=float)
    total_sq = 2.0 * rsq.sum()
    msd[0] = total_sq - 2.0 * correlation[0] * n_frames
    if n_frames > 1:
        msd[1:] = (
            total_sq
            - np.cumsum(rsq)[:-1]
            - np.cumsum(rsq[1:][::-1])
        ) / counts[1:] - 2.0 * correlation[1:]
    return msd


def run(ctx) -> dict[str, pd.DataFrame]:
    grouping = str(ctx.params.get("grouping", "residues"))
    atoms = ctx.groups["group"].atoms
    if atoms.n_atoms == 0:
        raise ValueError("MSD 分组为空")
    com = _com_trajectory(atoms, grouping, ctx.start, ctx.stop)
    msd_type = str(ctx.params["msd_type"])
    msd = _msd_from_com(com, msd_type, bool(ctx.params.get("fft", True)))
    universe = atoms.universe
    dt = float(getattr(ctx, "frame_dt_ps", universe.trajectory.ts.dt))
    lag_ns = np.arange(len(msd), dtype=float) * dt / 1000.0
    return {"msd": pd.DataFrame({"dt_ns": lag_ns, "msd_A2": msd})}
