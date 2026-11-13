"""msd 的算术测试。

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


def test_msd_matches_raw_coordinates(real):
    cfg, _ = real
    continuous = load_universe(cfg, coordinates="continuous")
    raw = raw_universe(cfg)

    for frame in range(START, STOP):
        continuous.trajectory[frame]
        raw.trajectory[frame]
        assert np.allclose(continuous.atoms.positions, raw.atoms.positions, atol=1e-9)

    results = []
    for universe in (continuous, raw):
        analysis = EinsteinMSD(
            universe.atoms, select="all", msd_type="xyz", fft=True
        )
        analysis.run(start=START, stop=STOP)
        results.append(np.asarray(analysis.results.timeseries))
    assert np.allclose(results[0], results[1], rtol=1e-6, atol=1e-9)


# --------------------------------------------------------------------------- #
# 端到端：输出、视图、确定性
# --------------------------------------------------------------------------- #


def test_msd_matches_ballistic_motion():
    """匀速直线运动时 MSD = (v·Δt)²，用来验证时间轴与单位。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import msd as msd_module

    n_frames, n_atoms, dt, vx = 6, 2, 2.0, 1.5
    coords = np.zeros((n_frames, n_atoms, 3))
    coords[:, :, 0] = np.arange(n_frames)[:, None] * dt * vx
    universe = mda.Universe.empty(n_atoms, trajectory=True)
    universe.load_new(coords, format=MemoryReader)
    universe.trajectory.ts.dt = dt

    ctx = SimpleNamespace(
        groups={"group": SimpleNamespace(atoms=universe.atoms)},
        start=0,
        stop=n_frames,
        params={"msd_type": "xyz", "fft": False},
    )
    table = msd_module.run(ctx)["msd"]
    lag = np.arange(n_frames) * dt
    assert np.allclose(table["dt_ps"], lag)
    assert np.allclose(table["msd_A2"], (vx * lag) ** 2)
