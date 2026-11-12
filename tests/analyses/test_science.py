"""分析侧科学断言：密度守恒、氢键计数/类型/寿命、RDF、MSD、速度剖面。

默认不跑；需要时显式执行：

    pytest tests/analyses
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


def test_msd_matches_raw_coordinates(real):
    cfg, _ = real
    continuous = load_universe(cfg, coordinates="continuous")
    raw = raw_universe(cfg)

    for frame in range(START, STOP):
        continuous.trajectory[frame]
        raw.trajectory[frame]
        assert np.allclose(continuous.atoms.positions, raw.atoms.positions, atol=1e-9)

    results = []
    for universe in (continuous, raw):
        analysis = EinsteinMSD(
            universe.atoms, select="all", msd_type="xyz", fft=True
        )
        analysis.run(start=START, stop=STOP)
        results.append(np.asarray(analysis.results.timeseries))
    assert np.allclose(results[0], results[1], rtol=1e-6, atol=1e-9)


# --------------------------------------------------------------------------- #
# 端到端：输出、视图、确定性
# --------------------------------------------------------------------------- #


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
    assert list(table.columns) == ["x (Å)", "z (Å)", "数密度 (Å^-3)"]

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["input"] == {
        "coordinates": "unwrapped",
        "detected_from": "xu yu zu",
    }
    assert provenance["selection"]["frame"] == START
    assert provenance["view"]["origin"] == [0.0, 0.0, 0.0]
    assert provenance["view"]["shift"][2] == pytest.approx(cfg.box_low[2])
    assert provenance["analyses"][0]["coordinates"] == "in_box"

    meta = provenance["analyses"][0]["meta"]
    extent = meta["grid_extent"]
    delta = float(meta["delta"])
    # Σρ · Δa · Δb · L_axis = 原子数（L_axis 为网格沿求和方向的覆盖长度）
    total = float(table["数密度 (Å^-3)"].sum()) * delta * delta * extent[meta["sum_axis"]]
    # 网格按 delta 取整，盒边缘可能有极少数原子落在网格外，故留 2% 余量
    assert total == pytest.approx(selection_count(cfg, "all"), rel=0.02)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


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
    assert list(velocity.columns) == ["z (Å)", "vx (Å/ps)", "误差 (Å/ps)"]
    z = velocity["z (Å)"]

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
    centers = lineardensity["z (Å)"].to_numpy()
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
    assert list(by_name.columns) == ["x (Å)", "vx (Å/ps)", "误差 (Å/ps)"]
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


def test_hbond_lifetime_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_lifetime, sel: ["type 1 3", "type 5 6", "type 1 3"],'
        ' tau_max_ps: 20}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(
        out / "hbond_lifetime/tables/hbond_lifetime.csv", encoding="utf-8-sig"
    )
    assert list(table.columns) == ["滞后 (ps)", "连续", "间歇"]
    assert table["滞后 (ps)"].iloc[0] == 0
    assert table["连续"].iloc[0] == 1 and table["间歇"].iloc[0] == 1
    # 每帧 5 ps，tau_max_ps=20 -> 4 帧，最后一行是 20 ps
    assert table["滞后 (ps)"].iloc[-1] == pytest.approx(20.0)

    summary = pd.read_csv(
        out / "hbond_lifetime/tables/hbond_lifetime_summary.csv", encoding="utf-8-sig"
    )
    assert list(summary["判据"]) == ["连续", "间歇"]
    assert (out / "hbond_lifetime/figures/hbond_lifetime.png").is_file()

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    warnings = provenance["analyses"][0]["warnings"]
    assert any("不可信" in message for message in warnings)


def test_hbond_lifetime_rejects_tau_below_one_frame(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_lifetime, sel: ["type 1 3", "type 5 6", "type 1 3"],'
        ' tau_max_ps: 1}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_hbond_type_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_type, sel: ["type 1 3", "type 5 6", "type 1 3"]}'
    )
    path = write_system(
        tmp_path, cfg.topology, cfg.trajectory, analyses,
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(out / "hbond_type/tables/hbond_type.csv", encoding="utf-8-sig")
    assert list(table.columns) == ["供体", "受体", "次数", "每帧平均", "占比"]
    assert not table.empty
    assert table["次数"].is_monotonic_decreasing
    assert set(table["供体"].str.split("-").str[0]) == {"TMA"}
    assert table["供体"].str.match(r"^[A-Z]{3}-[A-Z][a-z]?$").all()
    assert np.allclose(table["每帧平均"], table["次数"] / (STOP - START))
    assert table["占比"].sum() == pytest.approx(1.0)
    assert (out / "hbond_type/figures/hbond_type.png").is_file()

    # 横轴可切换为总次数
    total = write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: hbond_type, figure_axis: total,'
        ' sel: ["type 1 3", "type 5 6", "type 1 3"]}',
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    out_total = tmp_path / "out-total"
    assert cli.main(["run", "--system", str(total), "--out", str(out_total)]) == 0
    assert (out_total / "hbond_type/figures/hbond_type.png").is_file()


def test_hbond_type_requires_naming(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: hbond_type, sel: ["type 1 3", "type 5 6", "type 1 3"]}'
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "hbond_type/tables").exists()


# --------------------------------------------------------------------------- #
# 杂项
# --------------------------------------------------------------------------- #


def test_hbond_family_keeps_same_detection(real, tmp_path):
    """三个 hbond 分析各自构造检测时，判据与接线必须一致。"""
    import importlib
    import types

    cfg, _ = real
    analyses = (
        '  - {name: hbond, sel: [tma_o, tma_h, tma_o]}\n'
        '  - {name: hbond_type, sel: [tma_o, tma_h, tma_o]}\n'
        '  - {name: hbond_lifetime, sel: [tma_o, tma_h, tma_o], tau_max_ps: 20}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    config = read_system(path)
    plan = build_plan(config, load_registry())
    prepared = prepare(config, plan)

    curves = []
    for item in plan:
        module = importlib.import_module(item.definition.module)
        ctx = types.SimpleNamespace(
            universe=prepared.views[item.view],
            groups=prepared.item_groups(item),
            params=item.params,
        )
        analysis = module._build(ctx)
        analysis.run(start=prepared.start, stop=prepared.stop)
        curves.append(np.asarray(analysis.count_by_time(), dtype=int))

    assert np.array_equal(curves[0], curves[1])
    assert np.array_equal(curves[0], curves[2])


def test_rdf_range_beyond_half_box_is_rejected(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: rdf, sel: [all_atoms, all_atoms], range: [0.5, 40.0], nbins: 100}'
    )
    path = write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "rdf").exists()
