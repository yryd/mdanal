"""数据表落盘与内容哈希。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

import pandas as pd


def write_tables(directory: Path, tables: Mapping[str, pd.DataFrame]) -> dict[str, Path]:
    """把每张表写成 <directory>/tables/<名>.csv。"""
    written: dict[str, Path] = {}
    for name, frame in tables.items():
        path = directory / "tables" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.8g")
        written[name] = path
    return written


def sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()
