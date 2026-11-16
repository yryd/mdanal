"""density 的算术测试。

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

from helpers import (
    SYSTEM,
    START,
    STOP,
    constant_box_trajectory,
    raw_universe,
    selection_count,
    write_system,
)

pytestmark = pytest.mark.analysis


def test_density_and_msd_end_to_end(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y}\n'
        '  - {name: msd, sel: [all_atoms]}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"

    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    density_csv = out / "density-xz" / "tables" / "density_xz.csv"
    assert density_csv.is_file()
    table = pd.read_csv(density_csv, encoding="utf-8-sig")
    assert list(table.columns) == ["x_angstrom", "z_angstrom", "number_density_A3"]

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["input"] == {
        "coordinates": "unwrapped",
        "detected_from": "xu yu zu",
        "conventions": ["unwrapped"],
    }
    assert provenance["selection"]["frame"] == START
    assert provenance["view"]["origin"] == [0.0, 0.0, 0.0]
    assert provenance["view"]["shift"][2] == pytest.approx(cfg.box_low[2])
    assert provenance["analyses"][0]["coordinates"] == "in_box"

    meta = provenance["analyses"][0]["meta"]
    extent = meta["grid_extent"]
    delta = float(meta["delta"])
    # Σρ · Δa · Δb · extent_k = 原子数（extent 为网格沿求和方向的覆盖长度）
    total = float(table["number_density_A3"].sum()) * delta * delta * extent[meta["sum_axis"]]
    assert total == pytest.approx(selection_count(cfg, "all"), rel=1e-6)

    # 变盒子：只算首帧，并给出警告
    warnings = provenance["analyses"][0]["warnings"]
    assert any("盒子在变化" in message for message in warnings)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


def test_density_projection_conserves_at_two_deltas(real, tmp_path):
    """delta=1 与 delta=2 都必须严格守恒；旧实现 delta≠1 会低 Δ³ 倍。"""
    cfg, _ = real
    for delta in (1.0, 2.0):
        directory = tmp_path / f"d{delta}"
        path = write_system(
            directory,
            cfg.topology,
            cfg.trajectory,
            f"  - {{name: density, sel: [all_atoms], sum_axis: y, delta: {delta}}}\n",
        )
        out = directory / "out"
        assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
        table = pd.read_csv(out / "density/tables/density_xz.csv", encoding="utf-8-sig")
        meta = json.loads((out / "provenance.json").read_text(encoding="utf-8"))[
            "analyses"
        ][0]["meta"]
        total = (
            float(table["number_density_A3"].sum())
            * delta
            * delta
            * meta["grid_extent"]["y"]
        )
        assert total == pytest.approx(selection_count(cfg, "all"), rel=1e-6)


def test_density_constant_box_averages_frames(real, tmp_path):
    """固定盒时多帧平均应等于各单帧密度的平均。"""
    cfg, _ = real
    directory = tmp_path / "fixed"
    directory.mkdir()
    trajectory = constant_box_trajectory(directory)
    full = write_system(
        directory,
        cfg.topology,
        trajectory,
        "  - {name: density, sel: [all_atoms], sum_axis: y}\n",
        frames="[0, 5]",
    )
    out_full = directory / "out-full"
    assert cli.main(["run", "--system", str(full), "--out", str(out_full)]) == 0
    full_table = pd.read_csv(
        out_full / "density/tables/density_xz.csv", encoding="utf-8-sig"
    )
    provenance = json.loads((out_full / "provenance.json").read_text(encoding="utf-8"))
    assert not any(
        "盒子在变化" in message
        for message in provenance["analyses"][0]["warnings"]
    )

    singles = []
    for frame in range(5):
        single_dir = directory / f"f{frame}"
        single = write_system(
            single_dir,
            cfg.topology,
            trajectory,
            f"  - {{name: density, sel: [all_atoms], sum_axis: y, section: [{frame}, {frame + 1}]}}\n",
            frames="[0, 5]",
        )
        out = single_dir / "out"
        assert cli.main(["run", "--system", str(single), "--out", str(out)]) == 0
        singles.append(
            pd.read_csv(
                out / "density/tables/density_xz.csv", encoding="utf-8-sig"
            )["number_density_A3"].to_numpy()
        )
    assert np.allclose(
        full_table["number_density_A3"].to_numpy(), np.mean(singles, axis=0), atol=1e-9
    )
