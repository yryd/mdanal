from __future__ import annotations

from types import SimpleNamespace

import MDAnalysis as mda
import numpy as np
import pytest
from MDAnalysis.coordinates.memory import MemoryReader

from mdanal.analyses.velocity._impl import run as velocity_run


def _velocity_universe(positions, velocities, length=20.0):
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


def _ctx(universe, group, ref, *, dim="z", vdim="x", width=2.0):
    return SimpleNamespace(
        universe=universe,
        groups={"group": group, "ref": ref},
        start=0,
        stop=universe.trajectory.n_frames,
        selection_frame=0,
        extras={},
        params={
            "dim": dim,
            "vdim": vdim,
            "bin_width": width,
            "grouping": "atoms",
            "sym": False,
        },
    )


def test_uniform_velocity_profile_is_flat():
    n_frames, n_atoms, length = 4, 8, 20.0
    rng = np.random.default_rng(1)
    coords = np.zeros((n_frames, n_atoms, 3))
    coords[:, :, 0] = rng.uniform(1.0, length - 1.0, size=(n_atoms,))[None, :]
    coords[:, :, 1] = rng.uniform(1.0, length - 1.0, size=(n_atoms,))[None, :]
    coords[:, :, 2] = np.linspace(1.0, length - 1.0, n_atoms)[None, :]
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[:, :, 0] = 2.0
    universe = _velocity_universe(coords, velocities, length)
    table = velocity_run(
        _ctx(universe, universe.atoms, universe.atoms[:2])
    )["velocity"]
    finite = table["vx_A_per_ps"].notna()
    assert finite.any()
    assert np.allclose(table.loc[finite, "vx_A_per_ps"], 2.0)
    assert np.allclose(table.loc[finite, "error_A_per_ps"], 0.0)


def test_nonuniform_profile_uses_box_coordinates():
    n_frames, n_atoms, length = 4, 10, 20.0
    z = np.linspace(1.0, length - 1.0, n_atoms)
    positions = np.zeros((n_frames, n_atoms, 3))
    positions[:, :, 0] = 5.0
    positions[:, :, 1] = 5.0
    positions[:, :, 2] = z[None, :]
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[:, :, 0] = z[None, :]
    universe = _velocity_universe(positions, velocities, length)
    table = velocity_run(
        _ctx(universe, universe.atoms, universe.atoms[:1])
    )["velocity"]
    assert np.allclose(table["z_angstrom"], table["z_angstrom"].round(6))
    assert np.allclose(table["vx_A_per_ps"], table["z_angstrom"])


def test_pooled_samples_mean_and_naive_sem():
    n_frames, n_atoms, length = 2, 3, 10.0
    positions = np.zeros((n_frames, n_atoms, 3))
    positions[:, :, 0] = 5.0
    positions[:, :, 1] = 5.0
    positions[0, 0, 2] = 0.5
    positions[0, 1:, 2] = 8.5
    positions[1, :, 2] = 0.5
    velocities = np.zeros((n_frames, n_atoms, 3))
    velocities[1, :, 0] = 10.0
    universe = _velocity_universe(positions, velocities, length)
    table = velocity_run(
        _ctx(universe, universe.atoms, universe.atoms[:1], width=1.0)
    )["velocity"]
    # 第一帧 1 个 v=0、第二帧 3 个 v=10：均值 7.5；样本方差 75 → SEM 2.5。
    row = table.iloc[0]
    assert row["vx_A_per_ps"] == pytest.approx(7.5)
    assert row["error_A_per_ps"] == pytest.approx(2.5)
