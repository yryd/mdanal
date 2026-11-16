"""对比层：按分析声明取表与列，叠加两个体系。"""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from mdanal.compare import compare as compare_module
from mdanal.compare.compare import _is_time_axis, run_compare
from mdanal.errors import ValidationError

from helpers import SYSTEM, fake_definition, fake_registry, run_fake, write_system


def _run(tmp_path, name):
    path = write_system(
        tmp_path / name,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        "  - {name: fake, sel: [all_atoms, all_atoms]}\n",
        frames="[0, 5]",
    )
    run_fake(path, tmp_path / name / "out")
    return tmp_path / name / "out"


def _config(tmp_path, roots):
    lines = ["items:"]
    for index, root in enumerate(roots, 1):
        lines.append(f"  - {{root: {root}, label: 体系{index}}}")
    lines += ["figure:", "  analysis: fake", "  align: left"]
    path = tmp_path / "compare.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_compare_overlays_two_runs(tmp_path):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    out = tmp_path / "out"
    run_compare(config, out, registry=fake_registry(), lang="en")

    table = pd.read_csv(out / "tables" / "fake.csv", encoding="utf-8-sig")
    assert "x" in table.columns and "y" in table.columns
    assert len(table) == 10  # 两个体系各 5 行
    assert (out / "fake.png").is_file()

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert len(provenance["items"]) == 2
    assert len(provenance["xlim"]) == 2
    assert provenance["lang"] == "en"
    assert provenance["xlabel"] == "x (Å)"
    assert provenance["ylabel"] == "value"


def test_compare_rejects_t_offset_on_spatial_axis(tmp_path):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = tmp_path / "compare.yaml"
    config.write_text(
        "items:\n"
        f"  - {{root: {roots[0]}, label: A}}\n"
        f"  - {{root: {roots[1]}, label: B, t_offset: 5.0}}\n"
        "figure:\n"
        "  analysis: fake\n"
        "  align: left\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="t_offset 只能用于时间轴"):
        run_compare(config, tmp_path / "out", registry=fake_registry())


def test_compare_multi_column_gets_distinct_style_and_labels(tmp_path, monkeypatch):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    definition = replace(
        fake_definition(),
        compare={"table": "fake", "x": "x_angstrom", "y": ["y", "y2"], "box_axis": False},
    )
    captured = {}

    def fake_save(fig, path, dpi):
        ax = fig.axes[0]
        captured["labels"] = [line.get_label() for line in ax.get_lines()]
        captured["colors"] = [line.get_color() for line in ax.get_lines()]
        captured["styles"] = [line.get_linestyle() for line in ax.get_lines()]
        return path

    monkeypatch.setattr(compare_module.chart, "save", fake_save)
    run_compare(config, tmp_path / "out", registry={"fake": definition})

    assert captured["labels"] == [
        "体系1 · 值",
        "体系1 · 第二列",
        "体系2 · 值",
        "体系2 · 第二列",
    ]
    assert captured["colors"][0] == captured["colors"][1]
    assert captured["colors"][2] == captured["colors"][3]
    assert captured["colors"][0] != captured["colors"][2]
    assert captured["styles"] == ["-", "--", "-", "--"]


def test_compare_rejects_analysis_without_declaration(tmp_path):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    registry = {"fake": replace(fake_definition(), compare=None)}
    with pytest.raises(ValidationError, match="不支持对比"):
        run_compare(config, tmp_path / "out", registry=registry)


def test_time_axis_detection():
    assert _is_time_axis(False, "lag_ps")
    assert _is_time_axis(False, "dt_ps")
    assert not _is_time_axis(False, "r_angstrom")
    assert not _is_time_axis(True, "z_angstrom")


def test_compare_refuses_to_write_into_input_directory(tmp_path):
    """输出等于/位于输入结果目录时必须先失败，且不改动输入溯源。"""
    import hashlib

    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    provenance = roots[0] / "provenance.json"
    before = hashlib.sha256(provenance.read_bytes()).hexdigest()

    with pytest.raises(ValidationError, match="重叠"):
        run_compare(config, roots[0], registry=fake_registry())
    assert hashlib.sha256(provenance.read_bytes()).hexdigest() == before

    with pytest.raises(ValidationError, match="重叠"):
        run_compare(config, roots[0] / "compare", registry=fake_registry())
    assert not (roots[0] / "compare").exists()


def test_compare_refuses_nonempty_output_without_force(tmp_path):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    out = tmp_path / "compare"
    out.mkdir()
    marker = out / "keep.txt"
    marker.write_text("old", encoding="utf-8")

    with pytest.raises(ValidationError, match="非空"):
        run_compare(config, out, registry=fake_registry())
    assert marker.read_text(encoding="utf-8") == "old"

    run_compare(config, out, registry=fake_registry(), force=True)
    assert (out / "fake.png").is_file()
