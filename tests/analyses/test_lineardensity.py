"""lineardensity 的算术测试。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from MDAnalysis.units import constants

from mdanal import cli
from mdanal.config.system import load_universe
from helpers import START, write_system

pytestmark = pytest.mark.analysis

AVOGADRO = constants["N_Avogadro"]
VOLUME_CONVERSION = 1e-24


def _load(cfg):
    universe = load_universe(cfg, coordinates="in_box")
    universe.trajectory[START]
    lengths = np.asarray(universe.dimensions[:3], dtype=float)
    group = universe.select_atoms("all")
    positions = np.asarray(group.positions, dtype=float)
    wrapped = positions - np.floor(positions / lengths) * lengths
    return lengths, wrapped, np.asarray(group.masses, float), np.asarray(group.charges, float)


def _run(tmp_path, cfg, analyses, frames="[0, 5]"):
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses, frames=frames)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    return out


def _direct_density(cfg, axis: str, binsize: float):
    lengths, wrapped, masses, charges = _load(cfg)
    index = "xyz".index(axis)
    bins = int(np.floor(lengths[index] / binsize))
    edges = np.linspace(0.0, lengths[index], bins + 1)
    mass_hist, _ = np.histogram(wrapped[:, index], weights=masses, bins=edges)
    charge_hist, _ = np.histogram(wrapped[:, index], weights=charges, bins=edges)
    volume = float(np.prod(lengths))
    bin_volume = volume / bins
    mass_density = mass_hist / (AVOGADRO * VOLUME_CONVERSION * bin_volume)
    charge_density = charge_hist / bin_volume
    centers = 0.5 * (edges[1:] + edges[:-1])
    return centers, mass_density, charge_density


def test_single_frame_matches_direct_histogram(real, tmp_path):
    """单帧的线密度必须与独立直方图逐点一致（含 g/cm³ 与 e/Å³ 换算）。"""
    cfg, _ = real
    out = _run(
        tmp_path,
        cfg,
        "  - {name: lineardensity, sel: [all_atoms], binsize: 0.5, dim: z, section: [0, 1]}\n",
    )
    table = pd.read_csv(
        out / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    assert list(table.columns) == [
        "z_angstrom",
        "mass_density_g_cm3",
        "charge_density_e_A3",
    ]
    centers, mass, charge = _direct_density(cfg, "z", 0.5)
    assert np.allclose(table["z_angstrom"], centers)
    assert np.allclose(table["mass_density_g_cm3"], mass)
    assert np.allclose(table["charge_density_e_A3"], charge)


def test_box_change_warns_and_uses_first_frame(real, tmp_path):
    """变盒子时只算首帧，并给出警告；结果应与单帧一致。"""
    cfg, _ = real
    full_dir = tmp_path / "full"
    single_dir = tmp_path / "single"
    analyses = "  - {name: lineardensity, sel: [all_atoms], binsize: 0.5, dim: z}\n"
    out_full = _run(full_dir, cfg, analyses, frames="[0, 5]")
    out_single = _run(
        single_dir,
        cfg,
        "  - {name: lineardensity, sel: [all_atoms], binsize: 0.5, dim: z, section: [0, 1]}\n",
        frames="[0, 5]",
    )
    full = pd.read_csv(
        out_full / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    single = pd.read_csv(
        out_single / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    pd.testing.assert_frame_equal(full, single)

    provenance = json.loads((out_full / "provenance.json").read_text(encoding="utf-8"))
    warnings = provenance["analyses"][0]["warnings"]
    assert any("盒子在变化" in message for message in warnings)


def test_binsize_not_dividing_box(real, tmp_path):
    """盒长不能被 binsize 整除时，bin 数与 bin 体积仍与直方图一致。"""
    cfg, _ = real
    out = _run(
        tmp_path,
        cfg,
        "  - {name: lineardensity, sel: [all_atoms], binsize: 0.7, dim: z, section: [0, 1]}\n",
    )
    table = pd.read_csv(
        out / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    centers, mass, charge = _direct_density(cfg, "z", 0.7)
    assert len(table) == len(centers)
    assert np.allclose(table["z_angstrom"], centers)
    assert np.allclose(table["mass_density_g_cm3"], mass)
    assert np.allclose(table["charge_density_e_A3"], charge)
    assert len(table) == int(np.floor(np.asarray(_load(cfg)[0])[2] / 0.7))
