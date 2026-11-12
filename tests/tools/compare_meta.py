"""比较两次运行的元数据：manifest.csv 与 provenance.json 的约定字段。

用法：python tests/tools/compare_meta.py BASE AFTER

只比"应当稳定"的字段；参数键序、窗口/切片等结构变化不参与比较。
退出码 0 表示一致，1 表示有差异。
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

# provenance 顶层参与比较的字段（view 只比 origin/shift）
TOP_FIELDS = (
    "system",
    "config",
    "topology",
    "trajectory",
    "input",
    "box",
    "selection",
    "naming",
    "frames",
    "memory",
    "render",
    "libraries",
)

# 每条分析参与比较的字段（window/section 等新增字段不在其列）
ANALYSIS_FIELDS = (
    "order",
    "name",
    "tag",
    "directory",
    "slots",
    "selections",
    "atoms",
    "params",
    "coordinates",
    "tables",
    "figures",
    "meta",
)

MANIFEST_FIELDS = ("order", "name", "tag", "directory", "sels", "atoms", "params")


def project(prov: dict[str, Any]) -> dict[str, Any]:
    view = prov.get("view") or {}
    return {
        **{key: prov.get(key) for key in TOP_FIELDS},
        "view": {"origin": view.get("origin"), "shift": view.get("shift")},
        "analyses": [
            {key: item.get(key) for key in ANALYSIS_FIELDS}
            for item in prov.get("analyses") or []
        ],
    }


def manifests(directory: Path) -> tuple[list[str], list[tuple]]:
    path = directory / "manifest.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            params = json.loads(row.get("params") or "{}")
            rows.append(tuple(
                params if key == "params" else row.get(key)
                for key in MANIFEST_FIELDS
            ))
    return columns, rows


def walk(left: Any, right: Any, path: str = "") -> list[str]:
    """返回差异描述；dict 按键、list 按下标递归，其余直接比较。"""
    if isinstance(left, dict) and isinstance(right, dict):
        problems = []
        for key in sorted(set(left) | set(right)):
            here = f"{path}.{key}" if path else key
            if key not in left:
                problems.append(f"{here}: 缺少于 BASE")
            elif key not in right:
                problems.append(f"{here}: 缺少于 AFTER")
            else:
                problems.extend(walk(left[key], right[key], here))
        return problems
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}: 长度 {len(left)} != {len(right)}"]
        problems = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            problems.extend(walk(left_item, right_item, f"{path}[{index}]"))
        return problems
    if (
        isinstance(left, float)
        and isinstance(right, float)
        and math.isnan(left)
        and math.isnan(right)
    ):
        return []
    if left != right:
        return [f"{path}: {left!r} != {right!r}"]
    return []


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip())
        return 2
    base, after = Path(argv[1]), Path(argv[2])
    problems = []

    base_prov = json.loads((base / "provenance.json").read_text(encoding="utf-8"))
    after_prov = json.loads((after / "provenance.json").read_text(encoding="utf-8"))
    problems.extend(walk(project(base_prov), project(after_prov), "provenance"))

    base_cols, base_rows = manifests(base)
    after_cols, after_rows = manifests(after)
    if base_cols != after_cols:
        problems.append(f"manifest.columns: {base_cols!r} != {after_cols!r}")
    if base_rows != after_rows:
        for index, (left, right) in enumerate(zip(base_rows, after_rows), 1):
            if left != right:
                problems.append(f"manifest.row{index}: {left!r} != {right!r}")
        if len(base_rows) != len(after_rows):
            problems.append(f"manifest.rows: {len(base_rows)} != {len(after_rows)}")

    if problems:
        print("元数据不一致：")
        for problem in problems[:40]:
            print("  -", problem)
        if len(problems) > 40:
            print(f"  ... 共 {len(problems)} 处")
        return 1
    print("元数据一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
