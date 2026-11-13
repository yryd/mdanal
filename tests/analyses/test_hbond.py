"""hbond 的算术测试。

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


def test_hbond_family_keeps_same_detection(real, tmp_path):
    """三个 hbond 分析各自构造检测时，判据与接线必须一致。"""
    import importlib
    import types

    cfg, _ = real
    analyses = (
        '  - {name: hbond, sel: [tma_o, tma_h, tma_o]}\n'
        '  - {name: hbond_type, sel: [tma_o, tma_h, tma_o]}\n'
        '  - {name: hbond_lifetime, sel: [tma_o, tma_h, tma_o], tau_max_ps: 20}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    config = read_system(path)
    plan = build_plan(config, load_registry())
    prepared = prepare(config, plan)

    curves = []
    for item in plan:
        module = importlib.import_module(item.definition.module)
        ctx = types.SimpleNamespace(
            universe=prepared.views[item.view],
            groups=prepared.item_groups(item),
            params=item.params,
        )
        analysis = module._build(ctx)
        analysis.run(start=prepared.start, stop=prepared.stop)
        curves.append(np.asarray(analysis.count_by_time(), dtype=int))

    assert np.array_equal(curves[0], curves[1])
    assert np.array_equal(curves[0], curves[2])
