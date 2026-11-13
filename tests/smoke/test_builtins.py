"""内置插件烟测：可发现、可导入、声明有效、能端到端出图；不断言任何科学数值。"""

from __future__ import annotations

import json
import shutil

import yaml

from mdanal import cli
from mdanal.config.check import check_analysis
from mdanal.config.registry import RESERVED_KEYS, discover
from mdanal.config.system import ALLOWED_KEYS

from helpers import SYSTEM

BUILTINS = {
    "density",
    "lineardensity",
    "rdf",
    "hbond",
    "hbond_type",
    "hbond_lifetime",
    "msd",
    "velocity",
}


def test_builtin_plugins_discoverable():
    discovery = discover()
    assert discovery.failures == ()
    assert set(discovery.definitions) == BUILTINS


def test_builtin_end_to_end(tmp_path):
    for lang in ("zh", "en"):
        out = tmp_path / lang
        assert (
            cli.main(["run", "--system", str(SYSTEM), "--out", str(out), "--lang", lang])
            == 0
        )
        provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
        assert len(provenance["analyses"]) == 8
        assert len(list(out.glob("*/figures/*.png"))) == 8
        assert len(list(out.glob("*/tables/*.csv"))) == 13


def test_builtin_check_and_list(capsys):
    assert cli.main(["list"]) == 0
    assert "density" in capsys.readouterr().out

    assert cli.main(["check", "--system", str(SYSTEM)]) == 0
    assert "校验通过" in capsys.readouterr().out


def test_example_config_matches_registry():
    """模板示例的字段必须与当前程序一致，防止示例腐化。"""
    example = cli.PROGRAM_DIR.parent.parent / "example" / "system.yaml"
    data = yaml.safe_load(example.read_text(encoding="utf-8"))

    assert set(data) <= ALLOWED_KEYS

    registry = discover().definitions
    for entry in data["analyses"]:
        assert entry["name"] in registry
        allowed = RESERVED_KEYS | set(registry[entry["name"]].params)
        assert set(entry) <= allowed, f"{entry['name']} 含未知字段"

    if "naming" in data:
        assert set(data["naming"]) <= {"from_data", "residues", "atoms"}
    if "view" in data:
        assert set(data["view"]) <= {"origin"}


def test_compare_runs_on_builtin_output(tmp_path):
    for name in ("a", "b"):
        shutil.copytree(SYSTEM, tmp_path / name)
    config = tmp_path / "b" / "system.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "frames: [0, 20]", "frames: [0, 20]\n\nview:\n  origin: [0, 0, 5.0]"
        ),
        encoding="utf-8",
    )
    for name in ("a", "b"):
        assert cli.main(
            ["run", "--system", str(tmp_path / name), "--out", str(tmp_path / name / "out")]
        ) == 0

    compare = tmp_path / "compare.yaml"
    compare.write_text(
        f"""items:
  - {{root: {tmp_path / 'a' / 'out'}, label: 零点 0}}
  - {{root: {tmp_path / 'b' / 'out'}, label: 零点 5}}
figure:
  analysis: lineardensity
  align: left
""",
        encoding="utf-8",
    )
    out = tmp_path / "cmp"
    assert cli.main(["compare", "--config", str(compare), "--out", str(out)]) == 0
    assert (out / "tables" / "lineardensity_z.csv").is_file()
    assert (out / "lineardensity.png").is_file()


def test_check_analysis_builtin():
    discovery = discover()
    assert check_analysis(discovery) == []
    # 实跑选两条分析，避免冒烟测试太慢；静态检查已覆盖全部八个
    assert check_analysis(discovery, system=SYSTEM, names=("density", "rdf")) == []


def test_compare_columns_have_bilingual_labels():
    """参与对比的每一列都必须有中英标签，否则 compare --lang 会退回机器名。"""
    for name, definition in discover().definitions.items():
        comparison = definition.compare
        if not comparison:
            continue
        values = {key: spec["default"] for key, spec in definition.params.items()}
        values.setdefault("axis", values.get("dim", ""))
        columns = [comparison["x"].format(**values)]
        columns += [column.format(**values) for column in comparison["y"]]
        for lang in ("zh", "en"):
            labels = definition.column_labels.get(lang, {})
            missing = [column for column in columns if column not in labels]
            assert not missing, (name, lang, missing)


def test_labels_are_bilingual_and_complete():
    """每个内置分析的中英标签键集合必须一致；可对比列标签也一样。"""
    for name, definition in discover().definitions.items():
        assert set(definition.labels["zh"]) == set(definition.labels["en"]), name
        if definition.column_labels:
            assert set(definition.column_labels["zh"]) == set(
                definition.column_labels["en"]
            ), name
