"""velocity 的算术测试。

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


def test_velocity_axis_uses_view_coordinates(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}\n'
        '  - {name: velocity, sel: [all_atoms, tma_o], bin_width: 2.0}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    probe = read_system(path)
    universe = load_universe(probe)
    universe.trajectory[START]
    length = float(universe.dimensions[2])
    reference = universe.select_atoms("type 1 3").center_of_mass()[2]  # 盒坐标

    velocity = pd.read_csv(out / "velocity/tables/velocity.csv", encoding="utf-8-sig")
    assert list(velocity.columns) == ["z_angstrom", "vx_A_per_ps", "error_A_per_ps"]
    z = velocity["z_angstrom"]

    # 剖面网格覆盖盒长，坐标是盒坐标
    assert z.max() - z.min() < length
    assert z.min() >= 0.0
    assert z.max() <= length

    meta = json.loads((out / "provenance.json").read_text(encoding="utf-8"))["analyses"][1]["meta"]
    assert meta["ref_com"] == pytest.approx(reference, abs=1e-9)
    assert meta["ref_frame"] == START

    # 与 lineardensity 同框架：网格起点就是盒下角（0）。
    lineardensity = pd.read_csv(
        out / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    centers = lineardensity["z_angstrom"].to_numpy()
    spacing = float(centers[1] - centers[0])
    assert centers[0] - spacing / 2 == pytest.approx(0.0, abs=1e-5)


def test_velocity_axis_accepts_axis_names(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: velocity, tag: by-index, sel: [all_atoms, tma_o],'
        ' dim: 0, vdim: 0, bin_width: 2.0}\n'
        '  - {name: velocity, tag: by-name, sel: [all_atoms, tma_o],'
        ' dim: x, vdim: x, bin_width: 2.0}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    by_index = pd.read_csv(
        out / "velocity-by-index/tables/velocity.csv", encoding="utf-8-sig"
    )
    by_name = pd.read_csv(
        out / "velocity-by-name/tables/velocity.csv", encoding="utf-8-sig"
    )
    assert list(by_name.columns) == ["x_angstrom", "vx_A_per_ps", "error_A_per_ps"]
    pd.testing.assert_frame_equal(by_index, by_name)


def test_velocity_symmetric_profile(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: velocity, sel: [all_atoms, tma_o],'
        ' bin_width: 2.0, sym: true}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(out / "velocity/tables/velocity.csv", encoding="utf-8-sig")
    values = table.iloc[:, 1].to_numpy()
    # 对称化把 ±z 折叠平均，剖面必须关于参考组质心镜像对称
    assert np.allclose(values, values[::-1], equal_nan=True)


def test_unknown_axis_is_rejected(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: velocity, sel: [all_atoms, tma_o], dim: q}'
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


# --------------------------------------------------------------------------- #
# 命名
# --------------------------------------------------------------------------- #


def test_uniform_velocity_profile_is_flat():
    """所有原子同速时剖面为常数，误差为 0，坐标落在盒内。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import velocity as velocity_module

    n_frames, n_atoms, length = 4, 8, 20.0
    rng = np.random.default_rng(1)
    coords = np.zeros((n_frames, n_atoms, 3))
    coords[:, :, 0] = rng.uniform(1.0, length - 1.0, size=(n_atoms,))[None, :]
    coords[:, :, 1] = rng.uniform(1.0, length - 1.0, size=(n_atoms,))[None, :]
    coords[:, :, 2] = np.linspace(1.0, length - 1.0, n_atoms)[None, :]
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[:, :, 0] = 2.0
    dimensions = np.tile([length, length, length, 90, 90, 90], (n_frames, 1))

    universe = mda.Universe.empty(n_atoms, trajectory=True)
    universe.load_new(
        coords, velocities=velocities, dimensions=dimensions, format=MemoryReader
    )
    universe.add_TopologyAttr("mass", np.ones(n_atoms))

    ctx = SimpleNamespace(
        universe=universe,
        groups={
            "group": SimpleNamespace(atoms=universe.atoms),
            "ref": SimpleNamespace(atoms=universe.atoms[:2]),
        },
        start=0,
        stop=n_frames,
        selection_frame=0,
        extras={},
        params={
            "dim": "z",
            "vdim": "x",
            "bin_width": 2.0,
            "grouping": "atoms",
            "sym": False,
        },
    )
    table = velocity_module.run(ctx)["velocity"]
    finite = table["vx_A_per_ps"].notna()
    assert finite.any()
    assert np.allclose(table.loc[finite, "vx_A_per_ps"], 2.0)
    assert np.allclose(table.loc[finite, "error_A_per_ps"], 0.0)
    assert table["z_angstrom"].min() >= 0.0
    assert table["z_angstrom"].max() <= length


def _velocity_universe(positions, velocities, length=20.0):
    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader

    n_frames, n_atoms = positions.shape[:2]
    universe = mda.Universe.empty(n_atoms, trajectory=True)
    universe.load_new(
        positions,
        velocities=velocities,
        dimensions=np.tile([length, length, length, 90, 90, 90], (n_frames, 1)),
        format=MemoryReader,
    )
    universe.add_TopologyAttr("mass", np.ones(n_atoms))
    return universe


def test_nonuniform_profile_uses_box_coordinates():
    """vx=z、参考组在 z=1 时，机器标为 z 的 bin 必须给出该处的 vx。"""
    from types import SimpleNamespace

    from mdanal.analyses import velocity as velocity_module

    n_frames, n_atoms, length = 4, 10, 20.0
    z = np.linspace(1.0, length - 1.0, n_atoms)
    positions = np.zeros((n_frames, n_atoms, 3))
    positions[:, :, 0] = 5.0
    positions[:, :, 1] = 5.0
    positions[:, :, 2] = z[None, :]
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[:, :, 0] = z[None, :]
    universe = _velocity_universe(positions, velocities, length)

    ctx = SimpleNamespace(
        universe=universe,
        groups={
            "group": SimpleNamespace(atoms=universe.atoms),
            "ref": SimpleNamespace(atoms=universe.atoms[:1]),
        },
        start=0,
        stop=n_frames,
        selection_frame=0,
        extras={},
        params={
            "dim": "z",
            "vdim": "x",
            "bin_width": 2.0,
            "grouping": "atoms",
            "sym": False,
        },
    )
    table = velocity_module.run(ctx)["velocity"]
    assert np.allclose(table["z_angstrom"], [1, 3, 5, 7, 9, 11, 13, 15, 17, 19])
    assert np.allclose(table["vx_A_per_ps"], table["z_angstrom"])


def test_moving_reference_does_not_shift_profile():
    """参考组移动不应改变原盒坐标中的剖面（参考组只用于记录位置）。"""
    from types import SimpleNamespace

    from mdanal.analyses import velocity as velocity_module

    n_frames, length = 4, 20.0
    group_z = np.array([3.0, 5.0, 7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0])
    n_atoms = len(group_z) + 1
    positions = np.zeros((n_frames, n_atoms, 3))
    positions[:, :, 0] = 5.0
    positions[:, :, 1] = 5.0
    positions[:, 1:, 2] = group_z[None, :]
    positions[:, 0, 2] = 1.0 + np.arange(n_frames)
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[:, 1:, 0] = group_z[None, :]
    universe = _velocity_universe(positions, velocities, length)

    ctx = SimpleNamespace(
        universe=universe,
        groups={
            "group": SimpleNamespace(atoms=universe.atoms[1:]),
            "ref": SimpleNamespace(atoms=universe.atoms[:1]),
        },
        start=0,
        stop=n_frames,
        selection_frame=0,
        extras={},
        params={
            "dim": "z",
            "vdim": "x",
            "bin_width": 2.0,
            "grouping": "atoms",
            "sym": False,
        },
    )
    table = velocity_module.run(ctx)["velocity"]
    finite = table["vx_A_per_ps"].notna()
    assert np.allclose(table.loc[finite, "z_angstrom"], group_z)
    assert np.allclose(table.loc[finite, "vx_A_per_ps"], group_z)
