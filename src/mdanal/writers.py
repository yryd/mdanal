"""落盘：数据表、清单与溯源。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
# 表里形如 "x (Å)" 的列是盒坐标列；aligned 副本对它施加视图平移
COORD_COLUMN = re.compile(r"^([xyz]) \(Å\)$")


def write_aligned(
    directory: Path,
    tables: Mapping[str, pd.DataFrame],
    shift: Sequence[float],
    suffix: str = ".aligned",
) -> dict[str, Path]:
    """把坐标列加上视图平移后另写一份，列名与格式与正表一致。

    用途：需要"平移后"的数值时不必重算分析；正表仍是与呈现无关的盒坐标。
    """
    written: dict[str, Path] = {}
    for name, frame in tables.items():
        shifted = frame.copy()
        for column in shifted.columns:
            match = COORD_COLUMN.match(str(column))
            if match:
                axis = AXIS_INDEX[match.group(1)]
                shifted[column] = shifted[column] + shift[axis]
        path = directory / "tables" / f"{name}{suffix}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        shifted.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.8g")
        written[name] = path
    return written


def write_tables(directory: Path, tables: Mapping[str, pd.DataFrame]) -> dict[str, Path]:
    """把每张表写成 <directory>/tables/<名>.csv。"""
    written: dict[str, Path] = {}
    for name, frame in tables.items():
        path = directory / "tables" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.8g")
        written[name] = path
    return written


def project_grid(
    counts: np.ndarray, edges: Sequence[np.ndarray], sum_axis: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, int]]:
    """沿 sum_axis 求和，投影到另外两轴，返回 (轴1中心, 轴2中心, 数密度, 保留的轴号)。

    数密度 = Σ_axis n / (Δa · Δb · L_axis)，单位 Å⁻³，即沿求和方向的平均。
    """
    counts = np.asarray(counts, dtype=float)
    if counts.ndim != 3:
        raise ValueError(f"网格必须是三维，收到 shape={counts.shape}")

    axis = sum_axis.lower()
    if axis not in AXIS_INDEX:
        raise ValueError(f"sum_axis 只能是 x/y/z，收到 {sum_axis!r}")

    index = AXIS_INDEX[axis]
    centers = [0.5 * (np.asarray(e[1:]) + np.asarray(e[:-1])) for e in edges]
    widths = [float(np.asarray(e)[1] - np.asarray(e)[0]) for e in edges]
    lengths = [float(np.asarray(e)[-1] - np.asarray(e)[0]) for e in edges]

    keep = tuple(i for i in range(3) if i != index)
    summed = counts.sum(axis=index)
    volume = widths[keep[0]] * widths[keep[1]] * lengths[index]
    density = summed / volume

    return centers[keep[0]], centers[keep[1]], density, keep


def write_manifest(directory: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    path = directory / "manifest.csv"
    pd.DataFrame(list(rows)).to_csv(
        path, index=False, encoding="utf-8-sig", float_format="%.8g"
    )
    return path


def write_provenance(directory: Path, payload: Mapping[str, Any]) -> Path:
    path = directory / "provenance.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()
