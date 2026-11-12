"""落盘：数据表、清单与溯源。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

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
