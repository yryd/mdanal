"""注册层：模块声明校验、计划生成、失败分类与契约输出。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mdanal import cli
from mdanal.config import registry as registry_module
from mdanal.config.registry import (
    AnalysisDef,
    Discovery,
    ImportFailure,
    _definition_from_module,
    build_plan,
    check_packages,
)
from mdanal.config.system import read_system
from mdanal.errors import ValidationError

from helpers import SYSTEM, fake_definition, fake_registry, write_system
import fake_analysis


def test_definition_from_fake_module():
    definition = fake_definition()
    assert definition.slots == ("group", "ref")
    assert definition.params["scale"]["default"] == 2.0
    assert definition.params["scale"]["type"] is float
    assert definition.labels["zh"]["title"] == "假分析"
    assert definition.compare == {
        "table": "fake",
        "x": "x_angstrom",
        "y": ["y"],
        "box_axis": True,
    }
    assert definition.mutates_positions is False


def _module(**overrides):
    class Module:
        pass

    module = Module()
    for key in ("SLOTS", "PARAMS", "LABELS", "COORDINATES", "REQUIRES", "PACKAGE", "COMPARE", "MUTATES_POSITIONS"):
        value = overrides.get(key, getattr(fake_analysis, key, None))
        if key == "COORDINATES" and key not in overrides:
            value = "any"
        if key == "REQUIRES" and key not in overrides:
            value = ()
        setattr(module, key, value)
    return module


def test_definition_rejects_missing_slots():
    module = _module(SLOTS=())
    with pytest.raises(ValidationError, match="SLOTS"):
        _definition_from_module("bad", module, __import__("pathlib").Path("bad.py"))


def test_definition_rejects_bad_param_field():
    module = _module(PARAMS={"x": {"default": 1, "uniit": "Å"}})
    with pytest.raises(ValidationError, match="未知字段"):
        _definition_from_module("bad", module, __import__("pathlib").Path("bad.py"))


def test_definition_rejects_missing_english_labels():
    module = _module(LABELS={"zh": {"title": "只有中文"}})
    with pytest.raises(ValidationError, match="en"):
        _definition_from_module("bad", module, __import__("pathlib").Path("bad.py"))


def test_build_plan_applies_defaults_and_overrides(tiny, tmp_path):
    analyses = (
        '  - {name: fake, sel: [all, all]}\n'
        '  - {name: fake, tag: tuned, sel: [all, all], scale: 3.5, label: other,'
        ' section: [1, 3], plot: {window: {x: [0, 4]}}}\n'
    )
    path = write_system(tmp_path, tiny.topology, tiny.trajectory, analyses)
    plan = build_plan(read_system(path), fake_registry())

    assert [item.directory for item in plan] == ["fake", "fake-tuned"]
    assert plan[0].params == {"scale": 2.0, "label": "fake"}
    assert plan[1].params == {"scale": 3.5, "label": "other"}
    assert plan[1].section == (1, 3)
    assert plan[1].window == {"x": (0.0, 4.0)}


@pytest.mark.parametrize(
    "override, message",
    [
        ("scale: nope", "需要 float"),
        ("scale: -1.0", "≥"),
        ("label: nope", "只能是"),
        ("section: [2, 1]", "0 ≤ 起 < 止"),
    ],
)
def test_build_plan_rejects_bad_values(tiny, tmp_path, override, message):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        f'  - {{name: fake, sel: [all, all], {override}}}',
    )
    with pytest.raises(ValidationError, match=message):
        build_plan(read_system(path), fake_registry())


def test_check_packages_reports_missing(tiny, tmp_path):
    path = write_system(
        tmp_path, tiny.topology, tiny.trajectory, '  - {name: fake, sel: [all, all]}'
    )
    plan = build_plan(read_system(path), fake_registry())
    definition = replace(
        plan[0].definition,
        package={"name": "not_a_real_package_xyz", "min_version": ""},
    )
    plan[0] = replace(plan[0], definition=definition)
    problems = check_packages(plan)
    assert any("未安装" in problem for problem in problems)


def test_discover_classifies_import_failures(tmp_path, monkeypatch):
    for name in ("syntax", "missing", "internal", "internal_module", "boom"):
        (tmp_path / f"{name}.py").write_text("", encoding="utf-8")

    def fake_import(name: str):
        if name.endswith("syntax"):
            raise SyntaxError("bad syntax", ("syntax.py", 3, 1, "line"))
        if name.endswith("missing"):
            raise ModuleNotFoundError("No module named 'not_real_xyz'", name="not_real_xyz")
        if name.endswith("internal_module"):
            raise ModuleNotFoundError("No module named 'mdanal.plot.chartt'", name="mdanal.plot.chartt")
        if name.endswith("internal"):
            raise ImportError("cannot import name 'chartt'")
        raise RuntimeError("boom")

    monkeypatch.setattr(registry_module, "ANALYSES_DIR", tmp_path)
    monkeypatch.setattr(registry_module.importlib, "import_module", fake_import)
    discovery = registry_module.discover()

    assert discovery.definitions == {}
    categories = {failure.name: failure.category for failure in discovery.failures}
    assert categories == {
        "syntax": "语法错误",
        "missing": "缺可选依赖",
        "internal_module": "插件内部导入错误",
        "internal": "插件内部导入错误",
        "boom": "插件代码异常",
    }


def test_list_analysis_contract(capsys):
    discovery = Discovery({"fake": fake_definition()})
    assert cli._print_analysis(discovery, "fake") == 0
    output = capsys.readouterr().out
    assert "scale" in output and "float" in output and "2.0" in output


def test_list_shows_failure_reason(capsys):
    discovery = Discovery(
        {}, (ImportFailure("broken", "broken.py", "缺可选依赖", "not_real_xyz"),)
    )
    cli._print_registry(discovery)
    output = capsys.readouterr().out
    assert "broken.py" in output and "缺可选依赖" in output


def test_empty_params_are_allowed():
    subset = {
        "SLOTS": ("group",),
        "PARAMS": {},
        "LABELS": {"zh": {"title": "t"}, "en": {"title": "t"}},
    }
    definition = _definition_from_module("empty", _module(**subset), Path("empty.py"))
    assert definition.params == {}
    assert definition.slots == ("group",)
