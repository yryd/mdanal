"""hbond_type 的算术测试。

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


def test_hbond_type_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_type, sel: ["type 1 3", "type 5 6", "type 1 3"]}'
    )
    path = write_system(
        tmp_path, cfg.topology, cfg.trajectory, analyses,
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(out / "hbond_type/tables/hbond_type.csv", encoding="utf-8-sig")
    assert list(table.columns) == ["donor", "acceptor", "count", "per_frame", "share"]
    assert not table.empty
    assert table["count"].is_monotonic_decreasing
    assert set(table["donor"].str.split("-").str[0]) == {"TMA"}
    assert table["donor"].str.match(r"^[A-Z]{3}-[A-Z][a-z]?$").all()
    assert np.allclose(table["per_frame"], table["count"] / (STOP - START))
    assert table["share"].sum() == pytest.approx(1.0)
    assert (out / "hbond_type/figures/hbond_type.png").is_file()

    # 横轴可切换为总次数
    total = write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: hbond_type, figure_axis: total,'
        ' sel: ["type 1 3", "type 5 6", "type 1 3"]}',
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    out_total = tmp_path / "out-total"
    assert cli.main(["run", "--system", str(total), "--out", str(out_total)]) == 0
    assert (out_total / "hbond_type/figures/hbond_type.png").is_file()


def test_hbond_type_requires_naming(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: hbond_type, sel: ["type 1 3", "type 5 6", "type 1 3"]}'
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "hbond_type/tables").exists()


# --------------------------------------------------------------------------- #
# 杂项
# --------------------------------------------------------------------------- #
