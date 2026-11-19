from __future__ import annotations

import numpy as np
import pytest

from mdanal.analyses.density._impl import _project_grid
from helpers import compute_pack


def test_projection_with_exact_box_tiling_is_uniform():
    cells = 4
    width = 10.0 / cells
    counts = np.full((cells, cells, cells), 1000.0 / cells**3)
    edges = [np.linspace(0.0, 10.0, cells + 1)] * 3
    grid = counts / width**3
    _, _, density, _ = _project_grid(grid, edges, "y")
    assert np.allclose(density, 1.0)


@pytest.mark.parametrize("delta", [1.0, 2.0])
def test_density_projection_conserves_atoms(delta):
    tables, ctx = compute_pack(
        "density",
        select={"group": "all"},
        compute={"delta": delta, "binsize": 0.5},
    )
    table = tables["density_xy"]
    widths = ctx.extras["density_widths"]
    extent = ctx.extras["density_extent"]
    total = (
        float(table["number_density_A3"].sum())
        * widths["x"]
        * widths["y"]
        * extent["z"]
    )
    assert total == pytest.approx(504, rel=1e-6)


def test_density_compute_produces_all_projections_and_line_tables():
    tables, _ = compute_pack(
        "density",
        select={"group": "all"},
        compute={"delta": 2.0, "binsize": 0.5},
    )
    assert {"density_xy", "density_xz", "density_yz"} <= set(tables)
    assert {"lineardensity_x", "lineardensity_y", "lineardensity_z"} <= set(tables)
    for name in ("density_xy", "density_xz", "density_yz"):
        assert list(tables[name].columns) == [
            f"{name[-2]}_angstrom",
            f"{name[-1]}_angstrom",
            "number_density_A3",
        ]
    assert set(tables["lineardensity_z"].columns) == {
        "z_angstrom",
        "mass_density_g_cm3",
        "charge_density_e_A3",
    }
