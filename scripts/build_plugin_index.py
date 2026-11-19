"""校验插件 note 并生成 docs/analyses-index.md。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mdanal.config.registry import discover  # noqa: E402

REQUIRED = (
    "## 分析目的",
    "## 输入与前提",
    "## 输出",
    "## 注意",
)


def note_path(module) -> Path:
    path = Path(module.__file__)
    if path.name == "__init__.py":
        return path.parent / "note.md"
    return path.with_name(f"{path.stem}.note.md")


def main() -> int:
    discovery = discover()
    if discovery.failures:
        print("插件发现失败，拒绝生成索引：")
        for failure in discovery.failures:
            print(f" - {failure.name}（{failure.category}）：{failure.detail}")
        return 1
    missing = []
    rows = []
    for name, definition in sorted(discovery.definitions.items()):
        module = importlib.import_module(definition.module)
        path = note_path(module)
        if not path.is_file():
            missing.append(f"{name}: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        absent = [heading for heading in REQUIRED if heading not in text]
        if absent:
            missing.append(f"{name}: note 缺少 {absent}")
            continue
        rel = path.relative_to(ROOT).as_posix()
        rows.append((name, rel))
    if missing:
        print("插件 note 校验失败：")
        for item in missing:
            print(" -", item)
        return 1
    output = ["# 分析插件索引", "", "由 `scripts/build_plugin_index.py` 从插件 note 生成。", ""]
    for name, rel in rows:
        output.append(f"- [{name}](../{rel})")
    target = ROOT / "docs" / "analyses-index.md"
    target.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"插件 note 通过：{len(rows)} 个；写出 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
