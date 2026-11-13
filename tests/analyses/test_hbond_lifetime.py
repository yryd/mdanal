"""hbond_lifetime 的算术测试。

审计中按插件拆分；A2–A5 继续补解析/守恒用例。
"""

from __future__ import annotations

import json

import MDAnalysis as mda
import numpy as np
import pandas as pd
import pytest
from MDAnalysis.analysis.msd import EinsteinMSD
from PIL import Image

from mdanal import cli
from mdanal.config.registry import build_plan, load_registry
from mdanal.config.system import load_universe, read_system
from mdanal.errors import ValidationError
from mdanal.plot import chart, plotutil
from mdanal.run.runner import prepare

from helpers import SYSTEM, START, STOP, raw_universe, selection_count, write_system

pytestmark = pytest.mark.analysis


def test_hbond_lifetime_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_lifetime, sel: ["type 1 3", "type 5 6", "type 1 3"],'
        ' tau_max_ps: 20}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(
        out / "hbond_lifetime/tables/hbond_lifetime.csv", encoding="utf-8-sig"
    )
    assert list(table.columns) == ["lag_ps", "continuous", "intermittent"]
    assert table["lag_ps"].iloc[0] == 0
    assert table["continuous"].iloc[0] == 1 and table["intermittent"].iloc[0] == 1
    # 每帧 5 ps，tau_max_ps=20 -> 4 帧，最后一行是 20 ps
    assert table["lag_ps"].iloc[-1] == pytest.approx(20.0)

    summary = pd.read_csv(
        out / "hbond_lifetime/tables/hbond_lifetime_summary.csv", encoding="utf-8-sig"
    )
    assert list(summary.columns) == [
        "criterion",
        "tau_1e_ps",
        "tolerance_frames",
        "note",
    ]
    assert list(summary["criterion"]) == ["continuous", "intermittent"]
    assert (out / "hbond_lifetime/figures/hbond_lifetime.png").is_file()

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    warnings = provenance["analyses"][0]["warnings"]
    assert any("不可信" in message for message in warnings)


def test_hbond_lifetime_rejects_tau_below_one_frame(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_lifetime, sel: ["type 1 3", "type 5 6", "type 1 3"],'
        ' tau_max_ps: 1}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
