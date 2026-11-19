"""包插件、note 与多图配置的最小契约测试。"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mdanal.config.registry import _parse_derive, _parse_figures, discover
from mdanal.errors import ValidationError


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
    definition = discover().definitions["msd"]
    figures = _parse_figures(
        {"raw": {}, "fit": {"plot": {"xlim": [0, 1]}}}, "test", definition
    )
    assert set(figures) == {"raw", "fit"}
    derive = _parse_derive(
        {"fit": {"window_ns": [1, 2]}, "rdc": {}}, "test", definition
    )
    assert set(derive) == {"fit", "rdc"}


def test_msd_declares_derive_and_figures_and_rejects_typos():
    definition = discover().definitions["msd"]
    assert set(definition.derives) == {"fit", "rdc"}
    assert set(definition.figure_ids) == {"raw", "fit", "rdc"}
    with pytest.raises(ValidationError, match="含未知字段"):
        _parse_derive(
            {"fit": {"fit_window_ns": [0, 1]}}, "test", definition
        )
    with pytest.raises(ValidationError, match="不是 msd 的 figure recipe"):
        _parse_figures({"fitt": {}}, "test", definition)


def test_hbond_family_capabilities_are_restored():
    defs = discover().definitions
    assert defs["hbond"].compare is not None
    assert defs["hbond"].column_labels["zh"]["hbond_count"]
    for name in ("hbond", "hbond_type", "hbond_lifetime"):
        assert defs[name].geometry == {"cell": "any", "periodicity": "full"}
        assert defs[name].coordinates == "in_box"
    assert defs["hbond_lifetime"].compare is not None
    assert defs["hbond_type"].compare is None
