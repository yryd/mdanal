"""包插件、note 与多图配置的最小契约测试。"""

from __future__ import annotations

import importlib
from pathlib import Path

from mdanal.config.registry import _parse_derive, _parse_figures, discover


def test_all_builtin_plugins_have_notes():
    defs = discover().definitions
    assert "msd" in defs and "density" in defs and "hbond" in defs
    for name, definition in defs.items():
        module = importlib.import_module(definition.module)
        path = Path(module.__file__)
        note = path.parent / "note.md" if path.name == "__init__.py" else path.with_name(f"{path.stem}.note.md")
        assert note.is_file(), (name, note)
        text = note.read_text(encoding="utf-8")
        assert "## 分析目的" in text
        assert "## 输出" in text


def test_figures_and_derive_config_are_accepted():
    figures = _parse_figures({"raw": {}, "fit": {"plot": {"xlim": [0, 1]}}}, "test")
    assert set(figures) == {"raw", "fit"}
    derive = _parse_derive({"fit": {"window_ns": [1, 2]}, "rdc": {}}, "test")
    assert set(derive) == {"fit", "rdc"}
