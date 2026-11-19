from __future__ import annotations

from types import SimpleNamespace

import MDAnalysis as mda
import numpy as np
import pytest
from MDAnalysis.coordinates.memory import MemoryReader

from mdanal.analyses.rdf._impl import run as rdf_run


def _ctx(universe, groups, *, rng=(0.5, 4.0), nbins=4):
    return SimpleNamespace(
        universe=universe,
        groups={key: SimpleNamespace(atoms=atoms) for key, atoms in groups.items()},
        start=0,
        stop=1,
        params={"range": list(rng), "nbins": nbins},
    )


def test_ideal_gas_rdf_is_unity():
    rng = np.random.default_rng(0)
    n, length = 400, 30.0
    coords = rng.uniform(0.0, length, size=(1, n, 3))
    universe = mda.Universe.empty(n, trajectory=True)
    universe.load_new(coords, format=MemoryReader)
    universe.dimensions = [length, length, length, 90, 90, 90]
    table = rdf_run(
        _ctx(
            universe,
            {"a": universe.atoms[: n // 2], "b": universe.atoms[n // 2 :]},
            rng=(0.5, 10.0),
            nbins=30,
        )
    )["rdf"]
    window = table[(table["r_angstrom"] > 2.0) & (table["r_angstrom"] < 9.0)]
    assert window["g_r"].mean() == pytest.approx(1.0, abs=0.15)


def test_same_group_self_pairs_are_excluded():
    universe = mda.Universe.empty(2, trajectory=True)
    universe.load_new(
        np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0]]]), format=MemoryReader
    )
    universe.dimensions = [10.0, 10.0, 10.0, 90, 90, 90]
    table = rdf_run(
        _ctx(universe, {"a": universe.atoms, "b": universe.atoms}, rng=(0.0, 4.0))
    )["rdf"]
    assert table["g_r"].iloc[0] == pytest.approx(0.0, abs=1e-12)
    assert table["g_r"].iloc[1:].sum() > 0.0


def test_distinct_single_atom_groups_are_finite():
    universe = mda.Universe.empty(2, trajectory=True)
    universe.load_new(
        np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0]]]), format=MemoryReader
    )
    universe.dimensions = [10.0, 10.0, 10.0, 90, 90, 90]
    table = rdf_run(
        _ctx(
            universe,
            {"a": universe.atoms[[0]], "b": universe.atoms[[1]]},
        )
    )["rdf"]
    assert np.isfinite(table["g_r"]).all()
    assert table["g_r"].sum() > 0.0


def test_partial_overlap_excludes_only_true_self_pairs():
    universe = mda.Universe.empty(3, trajectory=True)
    universe.load_new(
        np.array([[[0.0, 5.0, 5.0], [2.0, 5.0, 5.0], [4.0, 5.0, 5.0]]]),
        format=MemoryReader,
    )
    universe.dimensions = [20.0, 20.0, 20.0, 90, 90, 90]
    table = rdf_run(
        _ctx(
            universe,
            {"a": universe.atoms[[0, 1]], "b": universe.atoms[[1, 2]]},
            rng=(0.5, 5.0),
            nbins=10,
        )
    )["rdf"]
    assert np.isfinite(table["g_r"]).all()
    assert table["g_r"].sum() > 0.0
