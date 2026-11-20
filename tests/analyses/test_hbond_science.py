from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from mdanal.analyses._geometry import geometry_meta
from mdanal.analyses import _hbond
from helpers import compute_pack

SELECT = {"donor": "o13", "hydrogen": "oh", "acceptor": "o13"}
PARAMS = {"d_a_cutoff": 3.5, "d_h_a_angle_cutoff": 150, "tau_max_ps": 20}


def test_hbond_family_tables_and_normalization():
    tables, ctx = compute_pack(
        "hbond", select=SELECT, compute=PARAMS, names=True
    )
    assert {"hbond_count", "hbond_summary", "hbond_occupancy", "hbond_type", "hbond_lifetime"} <= set(tables)
    summary = tables["hbond_summary"].iloc[0]
    mean = float(summary["mean_hbonds"])
    donor = ctx.groups["donor"].atoms
    assert summary["per_donor_atom"] == pytest.approx(mean / donor.n_atoms)
    assert summary["per_donor_residue"] == pytest.approx(mean / donor.residues.n_residues)


def test_hbond_type_matches_count_and_shares():
    tables, _ = compute_pack(
        "hbond", select=SELECT, compute={**PARAMS, "figure_axis": "rate"}, names=True
    )
    counts = tables["hbond_count"]
    types = tables["hbond_type"]
    assert int(types["count"].sum()) == int(counts["hbond_count"].sum())
    assert types["share"].sum() == pytest.approx(1.0)
    assert np.allclose(types["per_frame"], types["count"] / len(counts))


def test_hbond_lifetime_summary_status_and_units():
    tables, _ = compute_pack(
        "hbond", select=SELECT, compute={**PARAMS, "intermittency": 1}, names=True
    )
    lifetime = tables["hbond_lifetime"]
    summary = tables["hbond_lifetime_summary"]
    assert list(lifetime.columns) == ["lag_ps", "continuous", "intermittent"]
    assert set(summary["criterion"]) == {"continuous", "intermittent"}
    assert set(summary["status"]) <= {"reached", "not_reached", "no_events"}
    assert lifetime["lag_ps"].iloc[0] == 0.0


def test_hbond_family_constructs_one_hba():
    _hbond._CACHE.clear()
    from mdanal.analyses._hbond import build as real_build

    with patch("mdanal.analyses._hbond.build", wraps=real_build) as mock_build:
        compute_pack("hbond", select=SELECT, compute=PARAMS, names=True)
    assert mock_build.call_count == 1


def test_geometry_meta_marks_nonperiodic_unsupported():
    ctx = SimpleNamespace(
        geometry=SimpleNamespace(pbc=(True, False, True)),
        system=None,
    )
    meta = geometry_meta(ctx)
    assert meta["kernel_pbc"] == [True, False, True]
    assert meta["geometry_status"] == "unsupported_geometry"
