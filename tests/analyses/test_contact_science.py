from __future__ import annotations

from types import SimpleNamespace

import MDAnalysis as mda
import numpy as np
import pytest
from MDAnalysis.coordinates.memory import MemoryReader

from mdanal.analyses.contact._impl import run as contact_run
from mdanal.errors import ValidationError


def _universe(frames: int = 1):
    u = mda.Universe.empty(
        4,
        n_residues=2,
        atom_resindex=[0, 0, 1, 1],
        trajectory=True,
    )
    u.add_TopologyAttr("masses", [1.0, 1.0, 1.0, 1.0])
    u.add_TopologyAttr("resids", [1, 2])
    coords = np.zeros((frames, 4, 3), dtype=float)
    coords[:, 0:2, :] = [1.0, 5.0, 5.0]
    coords[:, 2:4, :] = [3.0, 5.0, 5.0]
    u.load_new(
        coords,
        format=MemoryReader,
        dimensions=np.tile([10.0, 10.0, 10.0, 90.0, 90.0, 90.0], (frames, 1)),
    )
    return u


def _ctx(u, first, second, *, frames=1, cutoff=2.5, block_ps=0.0):
    return SimpleNamespace(
        universe=u,
        groups={
            "first": SimpleNamespace(atoms=first, key="first", selection="first"),
            "second": SimpleNamespace(atoms=second, key="second", selection="second"),
        },
        start=0,
        stop=frames,
        params={"mode": "com", "cutoff": cutoff, "block_ps": block_ps},
        frame_dt_ps=1.0,
        requested_tables=frozenset({"contact"}),
    )


def test_cross_molecule_count_and_coordination():
    u = _universe()
    table = contact_run(_ctx(u, u.atoms[:2], u.atoms[2:]))["contact"]
    assert table["count"].tolist() == [1.0]
    assert table["coordination"].tolist() == [1.0]


def test_self_contacts_are_not_double_counted():
    u = _universe()
    table = contact_run(_ctx(u, u.atoms, u.atoms))["contact"]
    assert table["count"].tolist() == [1.0]
    assert table["coordination"].tolist() == [1.0]


def test_cutoff_excludes_far_molecules():
    u = _universe()
    table = contact_run(_ctx(u, u.atoms[:2], u.atoms[2:], cutoff=1.0))["contact"]
    assert table["count"].tolist() == [0.0]
    assert table["coordination"].tolist() == [0.0]


def test_block_average_keeps_head_and_tail_endpoints():
    u = _universe(frames=5)
    table = contact_run(_ctx(u, u.atoms[:2], u.atoms[2:], frames=5, block_ps=2.0))["contact"]
    assert table["time_ps"].tolist() == [0.0, 0.5, 2.5, 4.0]
    assert table["count"].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert table["coordination"].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert int(table["block_frames"].iloc[0]) == 2
    assert int(table["block_frames"].iloc[-1]) == 1


def test_single_frame_has_one_endpoint():
    u = _universe()
    table = contact_run(_ctx(u, u.atoms[:2], u.atoms[2:], block_ps=5.0))["contact"]
    assert table["time_ps"].tolist() == [0.0]
    assert table["count"].tolist() == [1.0]


def test_partial_molecule_is_rejected():
    u = _universe()
    with pytest.raises(ValidationError, match="部分原子"):
        contact_run(_ctx(u, u.atoms[[0]], u.atoms[2:]))


def test_empty_group_is_rejected():
    u = _universe()
    with pytest.raises(ValidationError, match="为空"):
        contact_run(_ctx(u, u.atoms[[]], u.atoms[2:]))


def test_pbc_minimum_image_contact():
    u = mda.Universe.empty(4, n_residues=2, atom_resindex=[0, 0, 1, 1], trajectory=True)
    u.add_TopologyAttr("masses", [1.0, 1.0, 1.0, 1.0])
    u.add_TopologyAttr("resids", [1, 2])
    coords = np.array([[[0.5, 5.0, 5.0], [0.5, 5.0, 5.0], [9.5, 5.0, 5.0], [9.5, 5.0, 5.0]]])
    u.load_new(
        coords,
        format=MemoryReader,
        dimensions=np.tile([10.0, 10.0, 10.0, 90.0, 90.0, 90.0], (1, 1)),
    )
    table = contact_run(_ctx(u, u.atoms[:2], u.atoms[2:], cutoff=2.5))["contact"]
    assert table["count"].tolist() == [1.0]


def test_block_average_values_and_endpoints_with_motion():
    u = mda.Universe.empty(3, n_residues=3, atom_resindex=[0, 1, 2], trajectory=True)
    u.add_TopologyAttr("masses", [1.0, 1.0, 1.0])
    u.add_TopologyAttr("resids", [1, 2, 3])
    coords = np.array([
        [[1.0, 5.0, 5.0], [3.0, 5.0, 5.0], [8.0, 5.0, 5.0]],
        [[1.0, 5.0, 5.0], [8.0, 5.0, 5.0], [8.0, 5.0, 5.0]],
        [[1.0, 5.0, 5.0], [3.0, 5.0, 5.0], [8.0, 5.0, 5.0]],
        [[1.0, 5.0, 5.0], [8.0, 5.0, 5.0], [8.0, 5.0, 5.0]],
        [[1.0, 5.0, 5.0], [3.0, 5.0, 5.0], [8.0, 5.0, 5.0]],
    ])
    u.load_new(coords, format=MemoryReader, dimensions=np.tile([10.0, 10.0, 10.0, 90.0, 90.0, 90.0], (5, 1)))
    table = contact_run(_ctx(u, u.atoms[[0]], u.atoms[[1]], frames=5, block_ps=2.0))["contact"]
    assert table["time_ps"].tolist() == [0.0, 0.5, 2.5, 4.0]
    assert table["count"].tolist() == [0.5, 0.5, 0.5, 1.0]


def test_window_time_origin_starts_at_zero():
    u = _universe(frames=5)
    ctx = _ctx(u, u.atoms[:2], u.atoms[2:], frames=5)
    ctx.start = 2
    ctx.stop = 5
    ctx.params = {"mode": "com", "cutoff": 2.5, "block_ps": 0.0, "time_origin": "window"}
    table = contact_run(ctx)["contact"]
    assert table["time_ps"].tolist() == [0.0, 1.0, 2.0]
