from __future__ import annotations

from types import SimpleNamespace

import MDAnalysis as mda
import numpy as np
import pandas as pd
import pytest
from MDAnalysis.coordinates.memory import MemoryReader

from mdanal.analyses.msd.compute import _msd_from_com, run as msd_run
from mdanal.analyses.msd.derive import run as derive_run


def _universe(coords):
    coords = np.asarray(coords, dtype=float)
    universe = mda.Universe.empty(coords.shape[1], trajectory=True)
    universe.load_new(coords, format=MemoryReader)
    universe.trajectory.ts.dt = 2.0
    return universe


def test_ballistic_motion_msd_and_time_axis():
    n_frames, n_atoms, dt, vx = 6, 2, 2.0, 1.5
    coords = np.zeros((n_frames, n_atoms, 3))
    coords[:, :, 0] = np.arange(n_frames)[:, None] * dt * vx
    universe = _universe(coords)
    universe.trajectory.ts.dt = dt
    ctx = SimpleNamespace(
        groups={"group": SimpleNamespace(atoms=universe.atoms)},
        start=0,
        stop=n_frames,
        params={"msd_type": "xyz", "grouping": "atoms", "fft": False},
        frame_dt_ps=dt,
    )
    table = msd_run(ctx)["msd"]
    assert np.allclose(table["dt_ns"], np.arange(n_frames) * dt / 1000.0)
    assert np.allclose(table["msd_A2"], (vx * np.arange(n_frames) * dt) ** 2)


def test_residue_com_cancels_opposite_motion():
    n_frames, dt = 6, 2.0
    coords = np.zeros((n_frames, 2, 3))
    coords[:, 0, 0] = np.arange(n_frames) * dt
    coords[:, 1, 0] = -np.arange(n_frames) * dt
    universe = mda.Universe.empty(
        2, n_residues=1, atom_resindex=[0, 0], trajectory=True
    )
    universe.load_new(coords, format=MemoryReader)
    universe.trajectory.ts.dt = dt
    ctx = SimpleNamespace(
        groups={"group": SimpleNamespace(atoms=universe.atoms)},
        start=0,
        stop=n_frames,
        params={"msd_type": "xyz", "grouping": "residues", "fft": False},
        frame_dt_ps=dt,
    )
    table = msd_run(ctx)["msd"]
    assert np.allclose(table["msd_A2"], 0.0, atol=1e-12)


def test_fft_matches_direct_and_translation_stable():
    rng = np.random.default_rng(7)
    com = rng.normal(size=(30, 4, 3))
    for msd_type in ("xyz", "xy", "z"):
        assert np.allclose(
            _msd_from_com(com, msd_type, fft=True),
            _msd_from_com(com, msd_type, fft=False),
            rtol=1e-10,
            atol=1e-10,
        )
    shifted = _msd_from_com(com + 1e6, "xyz", fft=True)
    direct = _msd_from_com(com, "xyz", fft=False)
    assert np.allclose(shifted, direct, rtol=1e-6, atol=1e-6)


def test_derive_fit_and_rdc_formula():
    table = pd.DataFrame({"dt_ns": [0.0, 1.0, 2.0], "msd_A2": [0.0, 6.0, 12.0]})
    ctx = SimpleNamespace(params={"msd_type": "xyz"})
    out = derive_run(
        ctx, {"msd": table}, {"fit": {"window_ns": [0.0, 2.0]}, "rdc": {}}
    )
    summary = out["msd_fit_summary"].iloc[0]
    assert summary["D_A2_per_ps"] == pytest.approx(0.001)
    rdc = out["msd_rdc"]["rdc_A2_per_ps"].to_numpy()
    assert np.isnan(rdc[0])
    assert np.allclose(rdc[1:], 0.001)


def test_two_point_free_fit_has_no_stderr():
    table = pd.DataFrame({"dt_ns": [0.0, 1.0], "msd_A2": [0.0, 2.0]})
    out = derive_run(
        SimpleNamespace(params={"msd_type": "xyz"}),
        {"msd": table},
        {"fit": {"window_ns": [0.0, 1.0], "intercept": "free"}},
    )
    summary = out["msd_fit_summary"].iloc[0]
    assert summary["n_points"] == 2
    assert summary["dof"] == 0
    assert np.isnan(summary["D_stderr_A2_per_ps"])


def test_fit_requires_explicit_window():
    from mdanal.analyses.msd.derive import validate_spec
    import pytest

    with pytest.raises(ValueError, match="window_ns"):
        validate_spec({"fit": {}})
