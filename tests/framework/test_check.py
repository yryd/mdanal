"""契约检查：静态声明、AST 兜底、临时目录实跑。"""

from __future__ import annotations

from pathlib import Path

import helpers
from mdanal.config.check import check_analysis
from mdanal.config.registry import (
    Discovery,
    ImportFailure,
    _definition_from_source,
)
from helpers import SYSTEM, fake_definition, write_system

FAKE = "  - {name: fake, sel: [all_atoms, all_atoms]}\n"


def test_static_check_passes_for_fake():
    assert check_analysis(Discovery({"fake": fake_definition()})) == []


def test_static_check_reports_failure_without_declaration():
    failure = ImportFailure("broken", "broken.py", "缺可选依赖", "not_real_xyz")
    problems = check_analysis(Discovery({}, (failure,)))
    assert problems and "缺可选依赖" in problems[0]


def test_static_check_notes_declaration_is_readable():
    failure = ImportFailure(
        "broken",
        "broken.py",
        "缺可选依赖",
        "not_real_xyz",
        declaration=fake_definition(),
    )
    problems = check_analysis(Discovery({}, (failure,)))
    assert "声明本身可解析" in problems[0]


def test_unknown_name_is_reported():
    problems = check_analysis(Discovery({"fake": fake_definition()}), names=("nope",))
    assert any("没有名为" in problem for problem in problems)


def test_ast_fallback_reads_fake_source():
    path = Path(helpers.__file__).resolve().parent / "fake_analysis.py"
    definition = _definition_from_source(path, "fake")
    assert definition is not None
    assert definition.slots == ("group", "ref")
    assert definition.params["scale"]["type"] is float


def test_ast_fallback_returns_none_on_syntax_error(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("def broken(:\n", encoding="utf-8")
    assert _definition_from_source(path, "bad") is None


def _system(tmp_path, section: str = ""):
    extra = f", section: {section}" if section else ""
    return write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        f"  - {{name: fake, sel: [all_atoms, all_atoms]{extra}}}\n",
        frames="[0, 5]",
    )


def test_system_run_checks_tables_and_figures(tmp_path):
    path = _system(tmp_path)
    assert check_analysis(Discovery({"fake": fake_definition()}), system=path) == []


def test_keep_directory_holds_both_languages(tmp_path):
    path = _system(tmp_path)
    keep = tmp_path / "kept"
    assert (
        check_analysis(
            Discovery({"fake": fake_definition()}), system=path, keep=keep
        )
        == []
    )
    assert (keep / "zh/fake/figures/fake.png").is_file()
    assert (keep / "zh/fake/tables/fake.csv").is_file()
    assert (keep / "en/provenance.json").is_file()


def test_invalid_system_returns_problem_instead_of_raising(tmp_path):
    path = _system(tmp_path, section="[0, 100]")
    problems = check_analysis(Discovery({"fake": fake_definition()}), system=path)
    assert any("超出体系窗口" in problem for problem in problems)
