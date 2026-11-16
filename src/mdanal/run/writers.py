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

from ..errors import ValidationError

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
# 表里形如 "x_angstrom" 的列是盒坐标列；aligned 副本对它施加视图平移
COORD_COLUMN = re.compile(r"^([xyz])_angstrom$")


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


def column_kinds(frame: pd.DataFrame) -> list[dict[str, str]]:
    """记录列名与可恢复的基础类型；不支持的对象列直接报错。"""
    from pandas.api import types as ptypes

    result: list[dict[str, str]] = []
    for name in frame.columns:
        series = frame[name]
        if ptypes.is_bool_dtype(series.dtype):
            kind = "bool"
        elif ptypes.is_integer_dtype(series.dtype):
            kind = "int"
        elif ptypes.is_float_dtype(series.dtype):
            kind = "float"
        elif ptypes.is_string_dtype(series.dtype) or ptypes.is_object_dtype(series.dtype):
            values = [value for value in series.tolist() if value is not None]
            if not all(isinstance(value, str) for value in values):
                raise ValidationError(
                    f"表列 {name!r} 含非字符串对象，无法写入可重绘快照"
                )
            kind = "str"
        else:
            raise ValidationError(
                f"表列 {name!r} 的类型 {series.dtype} 不受快照支持"
            )
        result.append({"name": str(name), "kind": kind})
    return result


def read_table(path: str | Path, columns: Sequence[Mapping[str, str]]) -> pd.DataFrame:
    """按快照记录的列类型读回 CSV；保留字符串 "NA"，不自动转缺失。"""
    raw = pd.read_csv(
        path, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )
    expected = [str(column["name"]) for column in columns]
    missing = [name for name in expected if name not in raw.columns]
    if missing:
        raise ValidationError(f"表 {path} 缺少快照记录的列 {missing}")
    result = pd.DataFrame(index=raw.index)
    for column in columns:
        name = str(column["name"])
        kind = str(column["kind"])
        values = raw[name]
        if kind == "float":
            result[name] = pd.to_numeric(
                values.replace("", np.nan), errors="raise"
            ).astype(float)
        elif kind == "int":
            numeric = pd.to_numeric(values.replace("", np.nan), errors="raise")
            result[name] = (
                numeric.astype("int64")
                if not numeric.isna().any()
                else numeric.astype("Int64")
            )
        elif kind == "bool":
            mapping = {
                "True": True,
                "False": False,
                "1": True,
                "0": False,
                "": None,
            }
            invalid = [value for value in values if value not in mapping]
            if invalid:
                raise ValidationError(
                    f"表列 {name!r} 的布尔值无法解析：{invalid[:3]}"
                )
            result[name] = values.map(mapping).astype("boolean")
        elif kind == "str":
            result[name] = values.astype(object)
        else:
            raise ValidationError(f"表列 {name!r} 的类型 {kind!r} 不受支持")
    return result
