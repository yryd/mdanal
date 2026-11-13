"""对比层：按分析声明取表与列，叠加两个体系。"""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from mdanal.compare.compare import run_compare
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


def test_compare_rejects_analysis_without_declaration(tmp_path):
    roots = [_run(tmp_path, "a"), _run(tmp_path, "b")]
    config = _config(tmp_path, roots)
    registry = {"fake": replace(fake_definition(), compare=None)}
    with pytest.raises(ValidationError, match="不支持对比"):
        run_compare(config, tmp_path / "out", registry=registry)
