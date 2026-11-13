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


def test_hbond_uses_resolved_groups_with_view_shift(real, tmp_path):
    """view.origin≠0 时，库里的选择必须与解析后的原子组一致，而不是按库自己的坐标重选。"""
    import types

    import MDAnalysis  # noqa: F401
    from mdanal.analyses import hbond as hbond_module
    from mdanal.config.registry import build_plan, load_registry

    cfg, _ = real
    path = write_system(
        tmp_path,
        cfg.topology,
        cfg.trajectory,
        "  - {name: hbond, sel: ['type 1 3 and prop z > 20', "
        "'type 5 6 and prop z > 20', 'type 1 3 and prop z > 20']}\n",
        extra="view:\n  origin: [0, 0, 5.0]\n",
    )
    probe = read_system(path)
    plan = build_plan(probe, load_registry())
    prepared = prepare(probe, plan)
    item = plan[0]
    ctx = types.SimpleNamespace(
        universe=prepared.views[item.view],
        groups=prepared.item_groups(item),
        params=item.params,
    )
    analysis = hbond_module._build(ctx)
    assert set(analysis._acceptors.indices) == set(
        ctx.groups["acceptor"].atoms.indices
    )
    assert len(ctx.groups["acceptor"].atoms) < 144  # 视图平移确实缩小了选择


def test_hbond_normalization_uses_donor_atoms_and_residues(real, tmp_path):
    cfg, _ = real
    path = write_system(
        tmp_path,
        cfg.topology,
        cfg.trajectory,
        "  - {name: hbond, sel: [all_atoms, all_atoms, all_atoms]}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    summary = pd.read_csv(
        out / "hbond/tables/hbond_summary.csv", encoding="utf-8-sig"
    )
    assert list(summary.columns) == [
        "n_frames",
        "mean_hbonds",
        "std_hbonds",
        "per_donor_atom",
        "per_donor_residue",
    ]
    donor = load_universe(read_system(path)).select_atoms("all")
    mean = float(summary["mean_hbonds"].iloc[0])
    assert summary["per_donor_atom"].iloc[0] == pytest.approx(
        mean / donor.n_atoms
    )
    assert summary["per_donor_residue"].iloc[0] == pytest.approx(
        mean / donor.residues.n_residues
    )


def test_hbond_type_totals_match_count(real, tmp_path):
    cfg, _ = real
    path = write_system(
        tmp_path,
        cfg.topology,
        cfg.trajectory,
        "  - {name: hbond, sel: [all_atoms, all_atoms, all_atoms]}\n"
        "  - {name: hbond_type, sel: [all_atoms, all_atoms, all_atoms]}\n",
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    counts = pd.read_csv(
        out / "hbond/tables/hbond_count.csv", encoding="utf-8-sig"
    )
    types = pd.read_csv(
        out / "hbond_type/tables/hbond_type.csv", encoding="utf-8-sig"
    )
    assert types["count"].sum() == counts["hbond_count"].sum()
    assert types["share"].sum() == pytest.approx(1.0)
    assert np.allclose(
        types["per_frame"], types["count"] / len(counts)
    )
