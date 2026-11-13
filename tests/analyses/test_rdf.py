"""rdf 的算术测试。

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


def test_rdf_range_beyond_half_box_is_rejected(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: rdf, sel: [all_atoms, all_atoms], range: [0.5, 40.0], nbins: 100}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "rdf").exists()


def test_ideal_gas_rdf_is_unity():
    """理想气体（随机点）的 g(r) 应接近 1；用来验证 InterRDF 的归一化。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import rdf as rdf_module

    rng = np.random.default_rng(0)
    n, length = 400, 30.0
    coords = rng.uniform(0.0, length, size=(n, 3))
    universe = mda.Universe.empty(n, trajectory=True)
    universe.load_new(coords[None, :, :], format=MemoryReader)
    universe.dimensions = [length, length, length, 90, 90, 90]

    ctx = SimpleNamespace(
        groups={
            "a": SimpleNamespace(atoms=universe.atoms[: n // 2]),
            "b": SimpleNamespace(atoms=universe.atoms[n // 2 :]),
        },
        universe=universe,
        start=0,
        stop=1,
        params={"range": [0.5, 10.0], "nbins": 30},
    )
    table = rdf_module.run(ctx)["rdf"]
    window = table[(table["r_angstrom"] > 2.0) & (table["r_angstrom"] < 9.0)]
    assert window["g_r"].mean() == pytest.approx(1.0, abs=0.15)
