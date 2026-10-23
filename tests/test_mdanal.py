"""集成测试。需要 MDANAL_SYSTEM 指向一个含 system.yaml 与轨迹的目录，未设置时整组跳过。"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pandas as pd
import pytest
from MDAnalysis.analysis.msd import EinsteinMSD
from PIL import Image

from mdanal import cli, plotutil
from mdanal import registry as registry_module
from mdanal.errors import ValidationError
from mdanal.registry import build_plan, check_packages, load_registry
from mdanal.runner import prepare
from mdanal.system import load_universe, read_system, resolve_group

_SYSTEM_ENV = os.environ.get("MDANAL_SYSTEM")
SYSTEM = Path(_SYSTEM_ENV) if _SYSTEM_ENV else None

pytestmark = pytest.mark.skipif(
    SYSTEM is None or not (SYSTEM / "system.yaml").is_file(),
    reason="未设置 MDANAL_SYSTEM，或该目录下没有 system.yaml",
)

START, STOP = 400, 402


def _write_system(
    tmp_path: Path,
    data_lmp: Path,
    traj: Path,
    analyses: str,
    frames: str = f"[{START}, {STOP}]",
    extra: str = "",
) -> Path:
    content = f"""\
name: probe
topology: {data_lmp}
trajectory: {traj}
timestep_fs: 1.0
dump_every: 10000
frames: {frames}
{extra}groups:
  all_atoms: "all"
  water: "type 17 18"
analyses:
{analyses}
"""
    path = tmp_path / "system.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _raw_universe(cfg) -> mda.Universe:
    """不做任何变换的 Universe，用于对照。"""
    return mda.Universe(
        str(cfg.topology),
        str(cfg.trajectory),
        format="LAMMPSDUMP",
        topology_format="data",
        dt=cfg.dt_ps,
    )


@pytest.fixture(scope="module")
def real():
    cfg = read_system(SYSTEM)
    registry = load_registry(cli.REGISTRY_PATH)
    return cfg, registry


def test_registry_has_six_analyses(real):
    _, registry = real
    assert set(registry) == {"density", "lineardensity", "rdf", "hbond", "msd", "velocity"}
    assert registry["hbond"].slots == ("donor", "hydrogen", "acceptor")
    assert registry["velocity"].requires == ("velocities",)
    assert registry["density"].coordinates == "in_box"
    assert registry["msd"].coordinates == "continuous"
    assert registry["rdf"].coordinates == "any"


def test_plan_from_real_system(real):
    cfg, registry = real
    plan = build_plan(cfg, registry)
    assert [item.order for item in plan] == list(range(1, len(plan) + 1))
    for item in plan:
        expected = f"{item.name}-{item.tag}" if item.tag else item.name
        assert item.directory == expected
    assert len({item.directory for item in plan}) == len(plan)
    assert {item.name: item.view for item in plan}["msd"] == "continuous"
    assert {item.name: item.view for item in plan}["velocity"] == "in_box"


def test_missing_system_yaml(tmp_path):
    with pytest.raises(ValidationError, match="找不到 system.yaml"):
        read_system(tmp_path)


def test_wrong_selection_count(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: rdf, sel: ["all"]}',
    )
    with pytest.raises(ValidationError, match="需要 2 个"):
        build_plan(read_system(path), registry)


def test_unknown_analysis(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: foo, sel: ["all"]}'
    )
    with pytest.raises(ValidationError, match="不存在"):
        build_plan(read_system(path), registry)


def test_unknown_parameter(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: ["all"], deltax: 1}',
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), registry)


def test_duplicate_directory(real, tmp_path):
    cfg, registry = real
    analyses = '  - {name: msd, sel: ["all"]}\n  - {name: msd, sel: ["all"]}'
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    with pytest.raises(ValidationError, match="重复使用"):
        build_plan(read_system(path), registry)


def test_unknown_view_field(real, tmp_path):
    cfg, _ = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: ["all"]}',
        extra="view:\n  centre: [0, 0, 0]\n",
    )
    with pytest.raises(ValidationError, match="未知字段"):
        read_system(path)


def test_empty_selection_is_rejected(real):
    cfg, _ = real
    universe = load_universe(cfg)
    with pytest.raises(ValidationError, match="解析为空"):
        resolve_group(cfg, universe, "type 3-13")


def test_input_state_matches_dump_header(real, capsys):
    cfg, _ = real
    assert cfg.input_state == "unwrapped"
    assert cfg.input_evidence == "xu yu zu"

    assert cli.main(["check", "--system", str(SYSTEM)]) == 0
    out = capsys.readouterr().out
    assert "未包裹坐标（xu yu zu）" in out
    assert f"选择：按第 {cfg.frames[0]} 帧解析" in out


def test_selection_frame_is_window_start(real):
    cfg, registry = real
    prepared = prepare(cfg, build_plan(cfg, registry))
    assert prepared.selection_frame == cfg.frames[0]
    assert prepared.views["in_box"].trajectory.ts.frame == cfg.frames[0]


def test_coordinates_use_original_frame(real):
    cfg, _ = real
    universe = load_universe(cfg)
    universe.trajectory[cfg.frames[0]]

    z = universe.atoms.positions[:, 2]
    # Universe 内为盒坐标，范围 0…L
    assert z.min() >= -1e-6
    assert z.max() <= universe.dimensions[2] + 1e-6

    # prop 选择按视图坐标求值：盒坐标加视图偏移
    low, high = (float(np.quantile(z, q)) for q in (0.4, 0.6))
    low += cfg.view.shift[2]
    high += cfg.view.shift[2]
    expected = int(((z + cfg.view.shift[2] > low) & (z + cfg.view.shift[2] < high)).sum())
    assert universe.select_atoms(f"prop z > {low} and prop z < {high}").n_atoms == expected


def test_in_box_view_keeps_atoms_inside(real):
    cfg, _ = real
    universe = load_universe(cfg, coordinates="in_box")

    for frame in (cfg.frames[0], cfg.frames[0] + 1):
        universe.trajectory[frame]
        length = np.asarray(universe.dimensions[:3])
        positions = universe.atoms.positions
        assert np.all(positions >= -1e-6)
        assert np.all(positions <= length + 1e-6)


def test_msd_matches_raw_coordinates(real):
    cfg, _ = real
    continuous = load_universe(cfg, coordinates="continuous")
    raw = _raw_universe(cfg)

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


def test_density_and_msd_end_to_end(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y}\n'
        '  - {name: msd, sel: [all_atoms]}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
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
    assert total == pytest.approx(selection_count(cfg, "all"), rel=1e-9)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


def test_view_origin_shifts_selection_and_tables(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}'
    origin = 5.0

    paths = {}
    for name, extra in (
        ("plain", ""),
        ("shifted", f"view:\n  origin: [0, 0, {origin}]\n"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        paths[name] = _write_system(directory, cfg.topology, cfg.trajectory, analyses, extra=extra)
        assert cli.main(["run", "--system", str(paths[name]), "--out", str(directory / "out")]) == 0

    plain = pd.read_csv(tmp_path / "plain/out/lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig")
    shifted = pd.read_csv(tmp_path / "shifted/out/lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig")
    assert len(plain) == len(shifted)
    assert np.allclose(plain["z (Å)"] - shifted["z (Å)"], origin)
    # 改 origin 只平移坐标，剖面数值必须逐行不变
    assert np.allclose(plain["质量密度 (g/cm^3)"], shifted["质量密度 (g/cm^3)"])
    assert np.allclose(plain["电荷密度 (e/Å^3)"], shifted["电荷密度 (e/Å^3)"])

    # 选择串按视图坐标书写：同一批原子在新坐标下的区间随之平移
    plain_cfg = read_system(paths["plain"])
    shifted_cfg = read_system(paths["shifted"])
    low, high = 20.0, 21.0
    assert np.array_equal(
        resolve_group(
            plain_cfg, load_universe(plain_cfg), f"prop z > {low} and prop z < {high}"
        ).atoms.indices,
        resolve_group(
            shifted_cfg,
            load_universe(shifted_cfg),
            f"prop z > {low - origin} and prop z < {high - origin}",
        ).atoms.indices,
    )


def test_window_only_affects_figure(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}'

    paths = {}
    for name, extra in (
        ("plain", ""),
        ("windowed", "view:\n  window:\n    z: [20.0, 24.0]\n"),
    ):
        directory = tmp_path / name
        directory.mkdir()
        paths[name] = _write_system(directory, cfg.topology, cfg.trajectory, analyses, extra=extra)
        assert cli.main(["run", "--system", str(paths[name]), "--out", str(directory / "out")]) == 0

    plain = pd.read_csv(tmp_path / "plain/out/lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig")
    windowed = pd.read_csv(
        tmp_path / "windowed/out/lineardensity/tables/lineardensity_z.csv",
        encoding="utf-8-sig",
    )
    pd.testing.assert_frame_equal(plain, windowed)
    assert (tmp_path / "windowed/out/lineardensity/figures/lineardensity_z.png").is_file()

    provenance = json.loads(
        (tmp_path / "windowed/out/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["view"]["window"] == {"z": [20.0, 24.0]}


def test_window_limit_ignores_bounds_outside_data():
    fig, ax = plotutil.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])

    plotutil.limit(ax, "x", (-5.0, 1.5))  # 下界落在数据之外，忽略该边界
    plotutil.limit(ax, "y", (0.5, 1.5))

    assert ax.get_xlim() == pytest.approx((0.0, 1.5))
    assert ax.get_ylim() == pytest.approx((0.5, 1.5))

    fig, ax = plotutil.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    plotutil.limit(ax, "x", (10.0, 20.0))  # 整个窗口在数据之外，保持数据范围

    assert ax.get_xlim() == pytest.approx((0.0, 2.0))


def test_velocity_axis_uses_view_coordinates(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}\n'
        '  - {name: velocity, sel: ["type 17 18", "resid 1 or resid 90"], bin_width: 2.0}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    probe = read_system(path)
    universe = load_universe(probe)
    universe.trajectory[START]
    length = float(universe.dimensions[2])
    low = probe.view.lower[2]
    reference = universe.select_atoms("resid 1 or resid 90").center_of_mass()[2]

    velocity = pd.read_csv(out / "velocity/tables/velocity.csv", encoding="utf-8-sig")
    assert list(velocity.columns) == ["z (Å)", "vx (Å/ps)", "误差 (Å/ps)"]
    z = velocity["z (Å)"]

    # 剖面网格以参考组质心为中心，覆盖整个盒长
    reference += low
    assert 0.5 * (z.min() + z.max()) == pytest.approx(reference, abs=1e-4)
    assert z.max() - z.min() < length
    assert z.min() >= low
    assert z.max() <= low + length

    meta = json.loads((out / "provenance.json").read_text(encoding="utf-8"))["analyses"][1]["meta"]
    assert meta["ref_com"] == pytest.approx(reference, abs=1e-9)
    assert meta["ref_frame"] == START

    # 与 lineardensity 同框架：后者的网格起点就是视图坐标下的盒下角。
    # 库给出的 bin 宽为 max(L)/n_bins，不正好等于 binsize，按实际间距反推。
    lineardensity = pd.read_csv(
        out / "lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig"
    )
    centers = lineardensity["z (Å)"].to_numpy()
    spacing = float(centers[1] - centers[0])
    assert centers[0] - spacing / 2 == pytest.approx(low, abs=1e-5)


def test_rdf_range_beyond_half_box_is_rejected(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: rdf, sel: [all_atoms, all_atoms], range: [0.5, 40.0], nbins: 100}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "rdf").exists()


def test_existing_output_refused(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_force_replaces_previous_output(real, tmp_path):
    cfg, _ = real
    first_cfg = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(first_cfg), "--out", str(out)]) == 0
    assert (out / "msd").is_dir()

    second_cfg = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y}'
    )
    assert cli.main(["run", "--system", str(second_cfg), "--out", str(out), "--force"]) == 0
    assert (out / "density-xz").is_dir()
    assert not (out / "msd").exists()


def test_deterministic_tables(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    first, second = tmp_path / "a", tmp_path / "b"
    assert cli.main(["run", "--system", str(path), "--out", str(first)]) == 0
    assert cli.main(["run", "--system", str(path), "--out", str(second)]) == 0
    assert (first / "msd/tables/msd.csv").read_bytes() == (second / "msd/tables/msd.csv").read_bytes()


def test_list_commands_run(real, capsys):
    assert cli.main(["list"]) == 0
    assert "density" in capsys.readouterr().out
    assert cli.main(["list", "--system", str(SYSTEM)]) == 0
    out = capsys.readouterr().out
    assert "将要运行的分析" in out
    assert "未包裹坐标" in out


def test_missing_package_reported(real, monkeypatch):
    cfg, registry = real
    plan = [item for item in build_plan(cfg, registry) if item.name == "velocity"]
    assert plan, "样例体系应包含 velocity"

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(registry_module.importlib.metadata, "version", missing)
    problems = check_packages(plan)
    assert problems and "未安装" in problems[0]


def selection_count(cfg, selection: str) -> int:
    universe = load_universe(cfg)
    return universe.select_atoms(selection).n_atoms
