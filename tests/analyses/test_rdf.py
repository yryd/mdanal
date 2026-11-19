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


def test_rdf_range_beyond_half_box_warns_but_runs(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: rdf, sel: [all_atoms, all_atoms], range: [0.5, 40.0], nbins: 100}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    assert (out / "rdf").exists()


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


def test_same_group_self_pairs_are_excluded():
    """同组 RDF 不能把 i-i 自配对计入第一个 bin。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import rdf as rdf_module

    universe = mda.Universe.empty(2, trajectory=True)
    coords = np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0]]])
    universe.load_new(coords, format=MemoryReader)
    universe.dimensions = [10.0, 10.0, 10.0, 90, 90, 90]
    ctx = SimpleNamespace(
        groups={"a": SimpleNamespace(atoms=universe.atoms),
                "b": SimpleNamespace(atoms=universe.atoms)},
        universe=universe,
        start=0,
        stop=1,
        params={"range": [0.0, 4.0], "nbins": 4},
    )
    table = rdf_module.run(ctx)["rdf"]
    assert table["g_r"].iloc[0] == pytest.approx(0.0, abs=1e-12)
    assert table["g_r"].iloc[1:].sum() > 0.0


def test_distinct_single_atom_groups_are_finite():
    """两个不同单原子组不能被 exclusion_block 误删成 NaN。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import rdf as rdf_module

    universe = mda.Universe.empty(2, trajectory=True)
    universe.load_new(
        np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0]]]), format=MemoryReader
    )
    universe.dimensions = [10.0, 10.0, 10.0, 90, 90, 90]
    ctx = SimpleNamespace(
        groups={
            "a": SimpleNamespace(atoms=universe.atoms[[0]]),
            "b": SimpleNamespace(atoms=universe.atoms[[1]]),
        },
        universe=universe,
        start=0,
        stop=1,
        params={"range": [0.5, 4.0], "nbins": 4},
    )
    table = rdf_module.run(ctx)["rdf"]
    assert np.isfinite(table["g_r"]).all()
    assert table["g_r"].sum() > 0.0


def test_partial_overlap_excludes_only_true_self_pairs():
    """部分重叠组不能把真实自配对算进 g(r)。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import rdf as rdf_module

    universe = mda.Universe.empty(3, trajectory=True)
    universe.load_new(
        np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0], [4.0, 5.0, 5.0]]]),
        format=MemoryReader,
    )
    universe.dimensions = [20.0, 20.0, 20.0, 90, 90, 90]
    ctx = SimpleNamespace(
        groups={
            "a": SimpleNamespace(atoms=universe.atoms[[0, 1]]),
            "b": SimpleNamespace(atoms=universe.atoms[[1, 2]]),
        },
        universe=universe,
        start=0,
        stop=1,
        params={"range": [0.5, 5.0], "nbins": 10},
    )
    table = rdf_module.run(ctx)["rdf"]
    assert np.isfinite(table["g_r"]).all()
    assert table["g_r"].sum() > 0.0


def test_variable_box_is_frame_local_and_order_independent(tmp_path):
    """变盒 RDF 必须逐帧用当前盒；同参数换分析顺序结果不变。"""
    source = (SYSTEM / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(source) if line.startswith("ITEM: TIMESTEP")]
    frames = source[starts[0] : starts[2]]
    # 第二帧 z 盒长翻倍；第一帧保持不变。
    second = [i for i, line in enumerate(frames) if line.startswith("ITEM: BOX BOUNDS")][1]
    for offset in (1, 2, 3):
        low, high = frames[second + offset].split()
        frames[second + offset] = f"{float(low):.16e} {float(high) * 2:.16e}\n"
    trajectory = tmp_path / "variable.lammpstrj"
    trajectory.write_text("".join(frames), encoding="utf-8")
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        trajectory,
        '  - {name: rdf, tag: first, sel: [all_atoms, all_atoms], range: [0.5, 8.0], nbins: 30}\n'
        '  - {name: rdf, tag: second, sel: [all_atoms, all_atoms], range: [0.5, 8.0], nbins: 30}\n',
        frames="[0, 2]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    first = pd.read_csv(out / "rdf-first/tables/rdf.csv", encoding="utf-8-sig")
    second = pd.read_csv(out / "rdf-second/tables/rdf.csv", encoding="utf-8-sig")
    pd.testing.assert_frame_equal(first, second)


def test_nonperiodic_axis_does_not_wrap_distant_pair():
    """非周期方向不能把 0.5/9.5 Å 折成 1 Å 的假近邻。"""
    from types import SimpleNamespace

    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import rdf as rdf_module

    universe = mda.Universe.empty(2, trajectory=True)
    universe.load_new(
        np.array([[[0.5, 5.0, 5.0], [9.5, 5.0, 5.0]]]), format=MemoryReader
    )
    universe.dimensions = [10.0, 10.0, 10.0, 90, 90, 90]
    ctx = SimpleNamespace(
        groups={
            "a": SimpleNamespace(atoms=universe.atoms),
            "b": SimpleNamespace(atoms=universe.atoms),
        },
        universe=universe,
        start=0,
        stop=1,
        geometry=SimpleNamespace(pbc=(False, True, True)),
        params={"range": [0.0, 4.0], "nbins": 4},
        extras={},
        warn=lambda message: None,
    )
    table = rdf_module.run(ctx)["rdf"]
    assert table["g_r"].sum() == pytest.approx(0.0, abs=1e-12)
    meta = rdf_module.meta(ctx, {"rdf": table})
    assert meta["input_pbc"] == [False, True, True]
    assert meta["kernel_pbc"] == [False, True, True]
    assert meta["geometry_status"] == "qualitative"
