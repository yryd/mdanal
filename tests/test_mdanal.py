"""集成测试：全部跑在仓库自带的 tiny 体系上，不依赖外部算例。

`tests/fixtures/tiny` 是真实 LAMMPS 输出的 20 帧截取（24 个 TMA、504 原子），
断言只写性质（守恒、对称、单调、边界），不写死原子数与帧号。
"""

from __future__ import annotations

import importlib.metadata
import json
import shutil
from pathlib import Path

import MDAnalysis as mda
import numpy as np
import pandas as pd
import pytest
import yaml
from MDAnalysis.analysis.msd import EinsteinMSD
from PIL import Image

from mdanal import chart, cli, plotutil
from mdanal import registry as registry_module
from mdanal.errors import MdanalError, ValidationError
from mdanal.registry import RESERVED_KEYS, build_plan, check_packages, load_registry
from mdanal.runner import prepare
from mdanal.system import ALLOWED_KEYS, load_universe, read_system, resolve_group

SYSTEM = Path(__file__).resolve().parent / "fixtures" / "tiny"
START, STOP = 0, 5  # 五帧窗口：够算寿命（4 帧滞后），且跑得快


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
dump_every: 5000
frames: {frames}
{extra}groups:
  all_atoms: "all"
  tma_o: "type 1 3"
  tma_h: "type 5 6"
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


def selection_count(cfg, selection: str) -> int:
    universe = load_universe(cfg)
    return universe.select_atoms(selection).n_atoms


# --------------------------------------------------------------------------- #
# 注册表与配置
# --------------------------------------------------------------------------- #


def test_registry_has_builtin_analyses(real):
    _, registry = real
    assert set(registry) == {
        "density", "lineardensity", "rdf", "hbond", "hbond_type",
        "hbond_lifetime", "msd", "velocity",
    }
    assert registry["hbond"].slots == ("donor", "hydrogen", "acceptor")
    assert registry["velocity"].requires == ("velocities",)
    assert registry["density"].coordinates == "in_box"
    assert registry["msd"].coordinates == "continuous"
    assert registry["rdf"].coordinates == "any"


def test_plan_from_system(real):
    cfg, registry = real
    plan = build_plan(cfg, registry)
    assert [item.order for item in plan] == list(range(1, len(plan) + 1))
    for item in plan:
        expected = f"{item.name}-{item.tag}" if item.tag else item.name
        assert item.directory == expected
    assert len({item.directory for item in plan}) == len(plan)
    assert {item.name: item.view for item in plan}["msd"] == "continuous"
    assert {item.name: item.view for item in plan}["velocity"] == "in_box"


def test_example_config_matches_registry():
    """模板示例的字段必须与当前程序一致，防止示例腐化。"""
    example = cli.PROGRAM_DIR.parent.parent / "example" / "system.yaml"
    data = yaml.safe_load(example.read_text(encoding="utf-8"))

    assert set(data) <= ALLOWED_KEYS

    registry = load_registry(cli.REGISTRY_PATH)
    for entry in data["analyses"]:
        assert entry["name"] in registry
        allowed = RESERVED_KEYS | set(registry[entry["name"]].params)
        assert set(entry) <= allowed, f"{entry['name']} 含未知字段"

    assert set(data["naming"]) <= {"from_data", "residues", "atoms"} if "naming" in data else True
    assert set(data["view"]) <= {"origin", "window"} if "view" in data else True


def test_missing_system_yaml(tmp_path):
    with pytest.raises(ValidationError, match="找不到 system.yaml"):
        read_system(tmp_path)


def test_wrong_selection_count(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: rdf, sel: ["all"]}'
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


def test_annotation_unknown_field_is_rejected(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - name: msd\n'
        '    sel: ["all"]\n'
        '    annotate:\n'
        '      - {kind: hline, at: 1.0, colour: red}',
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), registry)


# --------------------------------------------------------------------------- #
# 坐标视图与选择
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# 端到端：输出、视图、确定性
# --------------------------------------------------------------------------- #


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
    # 网格按 delta 取整，盒边缘可能有极少数原子落在网格外，故留 2% 余量
    assert total == pytest.approx(selection_count(cfg, "all"), rel=0.02)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


def test_view_origin_shifts_selection_and_aligned_tables(real, tmp_path):
    """表恒为盒坐标；改 origin 只影响选择串与 --aligned 副本。"""
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
        assert cli.main(
            ["run", "--system", str(paths[name]), "--out", str(directory / "out"), "--aligned"]
        ) == 0

    plain = pd.read_csv(tmp_path / "plain/out/lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig")
    shifted = pd.read_csv(tmp_path / "shifted/out/lineardensity/tables/lineardensity_z.csv", encoding="utf-8-sig")
    pd.testing.assert_frame_equal(plain, shifted)  # 正表与呈现无关

    plain_aligned = pd.read_csv(
        tmp_path / "plain/out/lineardensity/tables/lineardensity_z.aligned.csv", encoding="utf-8-sig"
    )
    shifted_aligned = pd.read_csv(
        tmp_path / "shifted/out/lineardensity/tables/lineardensity_z.aligned.csv", encoding="utf-8-sig"
    )
    assert np.allclose(plain_aligned["z (Å)"] - shifted_aligned["z (Å)"], origin)
    assert np.allclose(plain_aligned["质量密度 (g/cm^3)"], shifted_aligned["质量密度 (g/cm^3)"])

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
    fig, ax = chart.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])

    plotutil.limit(ax, "x", (-5.0, 1.5))  # 下界落在数据之外，忽略该边界
    plotutil.limit(ax, "y", (0.5, 1.5))

    assert ax.get_xlim() == pytest.approx((0.0, 1.5))
    assert ax.get_ylim() == pytest.approx((0.5, 1.5))

    fig, ax = chart.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    plotutil.limit(ax, "x", (10.0, 20.0))  # 整个窗口在数据之外，保持数据范围

    assert ax.get_xlim() == pytest.approx((0.0, 2.0))


def test_deterministic_tables(tmp_path):
    """同一输入两次运行，输出逐字节一致。"""
    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        assert cli.main(
            ["run", "--system", str(SYSTEM), "--out", str(out)]
        ) == 0
    for relative in (
        "lineardensity/tables/lineardensity_z.csv",
        "hbond/tables/hbond_count.csv",
        "msd/tables/msd.csv",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    for relative in (
        "lineardensity/figures/lineardensity_z.png",
        "hbond_type/figures/hbond_type.png",
    ):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_all_analyses_render_both_languages(tmp_path):
    """夹具的八条分析在中英两种语言下都要出图；表不随语言变。"""
    for lang in ("zh", "en"):
        out = tmp_path / lang
        assert cli.main(
            ["run", "--system", str(SYSTEM), "--out", str(out), "--lang", lang]
        ) == 0
        provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
        assert len(provenance["analyses"]) == 8
        # 夹具含 velocity：MAICoS 会就地改坐标，故整轮不读入内存
        assert provenance["memory"]["enabled"] is False
        figures = list(out.glob("*/figures/*.png"))
        assert len(figures) == 8
        assert all(path.stat().st_size > 1000 for path in figures)

    for relative in (
        "lineardensity/tables/lineardensity_z.csv",
        "hbond/tables/hbond_count.csv",
    ):
        assert (tmp_path / "zh" / relative).read_bytes() == (
            tmp_path / "en" / relative
        ).read_bytes()


def test_font_is_available():
    assert chart.missing_fonts() == []


# --------------------------------------------------------------------------- #
# 速度剖面
# --------------------------------------------------------------------------- #


def test_velocity_axis_uses_view_coordinates(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}\n'
        '  - {name: velocity, sel: [all_atoms, tma_o], bin_width: 2.0}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
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
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
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
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    table = pd.read_csv(out / "velocity/tables/velocity.csv", encoding="utf-8-sig")
    values = table.iloc[:, 1].to_numpy()
    # 对称化把 ±z 折叠平均，剖面必须关于参考组质心镜像对称
    assert np.allclose(values, values[::-1], equal_nan=True)


def test_unknown_axis_is_rejected(real, tmp_path):
    cfg, _ = real
    analyses = '  - {name: velocity, sel: [all_atoms, tma_o], dim: q}'
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


# --------------------------------------------------------------------------- #
# 命名
# --------------------------------------------------------------------------- #


def test_naming_from_data(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: [all_atoms]}',
        extra=f"naming:\n  from_data: {cfg.topology}\n",
    )
    probe = read_system(path)
    prepared = prepare(probe, build_plan(probe, registry))
    universe = prepared.views["in_box"]

    assert set(universe.atoms.elements) == {"C", "H", "O"}
    assert universe.select_atoms("resname TMA").n_atoms == universe.atoms.n_atoms
    assert prepared.naming is not None
    assert prepared.naming.residue_counts["TMA"] == universe.residues.n_residues
    assert prepared.naming.overrides == ()
    assert prepared.naming.atom_count == universe.atoms.n_atoms


def test_naming_rules_override_warns(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: [all_atoms]}',
        extra=(
            f"naming:\n  from_data: {cfg.topology}\n"
            "  residues:\n    - {name: HONEY, types: [1, 2, 3, 4, 5, 6]}\n"
            '  atoms:\n    "1": OX\n'
        ),
    )
    probe = read_system(path)
    prepared = prepare(probe, build_plan(probe, registry))

    assert prepared.naming is not None
    assert prepared.naming.overrides
    assert "TMA→HONEY" in prepared.naming.warning
    universe = prepared.views["in_box"]
    assert prepared.naming.residue_counts["HONEY"] == universe.residues.n_residues
    assert universe.select_atoms("resname HONEY").n_atoms == universe.atoms.n_atoms
    assert universe.select_atoms("resname HONEY and name OX").n_atoms == selection_count(
        cfg, "type 1"
    )


def test_naming_incomplete_is_rejected(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: [all_atoms]}',
        extra='naming:\n  atoms:\n    "1": OX\n',
    )
    probe = read_system(path)
    with pytest.raises(ValidationError, match="没有分子名"):
        prepare(probe, build_plan(probe, registry))


def test_naming_keyword_is_rejected(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: [all_atoms]}',
        extra=(
            f"naming:\n  from_data: {cfg.topology}\n"
            "  residues:\n    - {name: water, types: [1, 2, 3, 4, 5, 6]}\n"
        ),
    )
    probe = read_system(path)
    with pytest.raises(ValidationError, match="关键字"):
        prepare(probe, build_plan(probe, registry))


# --------------------------------------------------------------------------- #
# 氢键
# --------------------------------------------------------------------------- #


def test_hbond_lifetime_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_lifetime, sel: ["type 1 3", "type 5 6", "type 1 3"],'
        ' tau_max_ps: 20}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
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
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_hbond_type_output(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: hbond_type, sel: ["type 1 3", "type 5 6", "type 1 3"]}'
    )
    path = _write_system(
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
    total = _write_system(
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
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3
    assert not (out / "hbond_type/tables").exists()


# --------------------------------------------------------------------------- #
# 杂项
# --------------------------------------------------------------------------- #


def test_missing_label_is_rejected():
    labels = plotutil.Labels({"zh": {"title": "t"}}, {})
    with pytest.raises(MdanalError, match="缺少标签"):
        labels("axis_x")


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
    assert plan, "夹具体系应包含 velocity"

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(registry_module.importlib.metadata, "version", missing)
    problems = check_packages(plan)
    assert problems and "未安装" in problems[0]


# --------------------------------------------------------------------------- #
# 多段轨迹
# --------------------------------------------------------------------------- #


def _split_trajectory(directory: Path) -> tuple[Path, Path, int]:
    """把夹具轨迹从中间切成两段，返回 (第一段, 第二段, 总帧数)。"""
    lines = (SYSTEM / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("ITEM: TIMESTEP")]
    cut = starts[len(starts) // 2]
    first = directory / "a.lammpstrj"
    second = directory / "b.lammpstrj"
    first.write_text("".join(lines[:cut]), encoding="utf-8")
    second.write_text("".join(lines[cut:]), encoding="utf-8")
    return first, second, len(starts)


def _segmented_system(directory: Path, trajectory: str) -> Path:
    """照抄夹具体系，只换轨迹与绝对路径。"""
    content = (SYSTEM / "system.yaml").read_text(encoding="utf-8")
    content = content.replace("topology: data.lmp", f"topology: {SYSTEM / 'data.lmp'}")
    content = content.replace("trajectory: run.lammpstrj", f"trajectory: {trajectory}")
    content = content.replace(
        "from_data: data.lmp", f"from_data: {SYSTEM / 'data.lmp'}"
    )
    path = directory / "system.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_merged_segments_match_single_file(tmp_path):
    """两段合并后的八条分析，必须与单文件跑出来的表逐字节一致。"""
    first, second, total = _split_trajectory(tmp_path)
    merged = tmp_path / "merged"
    merged.mkdir()
    path = _segmented_system(merged, f"[{first}, {second}]")

    out_merged = tmp_path / "out-merged"
    out_single = tmp_path / "out-single"
    assert cli.main(["run", "--system", str(path), "--out", str(out_merged)]) == 0
    assert cli.main(["run", "--system", str(SYSTEM), "--out", str(out_single)]) == 0

    provenance = json.loads((out_merged / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["trajectory"]["segments"]["count"] == 2
    assert provenance["trajectory"]["segments"]["frames"] == [total // 2, total - total // 2]
    assert len(provenance["frames"]) == 4  # start/stop/n_frames/frame_dt_ps

    for table in out_single.glob("*/tables/*.csv"):
        relative = table.relative_to(out_single)
        assert (out_merged / relative).read_bytes() == table.read_bytes(), relative


def test_segment_state_mismatch_is_rejected(tmp_path):
    first, second, _ = _split_trajectory(tmp_path)
    text = second.read_text(encoding="utf-8")
    second.write_text(
        text.replace("xu yu zu", "x y z", 1), encoding="utf-8"
    )
    merged = tmp_path / "merged"
    merged.mkdir()
    path = _segmented_system(merged, f"[{first}, {second}]")
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_seam_time_backward_is_reported(tmp_path):
    first, second, _ = _split_trajectory(tmp_path)
    text = second.read_text(encoding="utf-8")
    # 把第二段首帧的步数改成 0：续跑常见的时间倒退
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("ITEM: TIMESTEP"):
            lines[index + 1] = "0\n"
            break
    second.write_text("".join(lines), encoding="utf-8")

    merged = tmp_path / "merged"
    merged.mkdir()
    path = _segmented_system(merged, f"[{first}, {second}]")
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    notes = provenance["trajectory"]["segments"]["seam_notes"]
    assert any("时间倒退" in note for note in notes)


# --------------------------------------------------------------------------- #
# 轨迹读入内存
# --------------------------------------------------------------------------- #


def test_memory_and_disk_runs_agree(tmp_path):
    """默认读入内存与 --no-memory 的结果必须逐字节一致。"""
    cfg = read_system(SYSTEM)
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 0.5}\n'
        '  - {name: hbond, sel: ["type 1 3", "type 5 6", "type 1 3"]}\n'
        '  - {name: msd, sel: [all_atoms]}',
        frames="[0, 20]",
    )
    memory, disk = tmp_path / "memory", tmp_path / "disk"
    assert cli.main(["run", "--system", str(path), "--out", str(memory)]) == 0
    assert cli.main(
        ["run", "--system", str(path), "--out", str(disk), "--no-memory"]
    ) == 0

    for relative in (
        "lineardensity/tables/lineardensity_z.csv",
        "hbond/tables/hbond_count.csv",
        "hbond/figures/hbond_count.png",
        "msd/tables/msd.csv",  # 时间轴必须与磁盘读一致
    ):
        assert (memory / relative).read_bytes() == (disk / relative).read_bytes()

    enabled = json.loads((memory / "provenance.json").read_text(encoding="utf-8"))
    disabled = json.loads((disk / "provenance.json").read_text(encoding="utf-8"))
    assert enabled["memory"]["enabled"] is True
    assert disabled["memory"]["enabled"] is False


# --------------------------------------------------------------------------- #
# 表坐标与 aligned 副本
# --------------------------------------------------------------------------- #


def test_aligned_tables_equal_plain_plus_shift(tmp_path):
    """正表是盒坐标；--aligned 副本的坐标列恰好加上视图平移。"""
    out = tmp_path / "out"
    assert cli.main(
        ["run", "--system", str(SYSTEM), "--out", str(out), "--aligned"]
    ) == 0
    cfg = read_system(SYSTEM)

    checked = 0
    for plain_path in out.glob("*/tables/*.csv"):
        if plain_path.name.endswith(".aligned.csv"):
            continue
        aligned_path = plain_path.with_name(
            plain_path.name.replace(".csv", ".aligned.csv")
        )
        assert aligned_path.is_file(), aligned_path
        plain = pd.read_csv(plain_path, encoding="utf-8-sig")
        aligned = pd.read_csv(aligned_path, encoding="utf-8-sig")

        coordinate_columns = [
            column for column in plain.columns
            if column in ("x (Å)", "y (Å)", "z (Å)")
        ]
        for column in plain.columns:
            if column in coordinate_columns:
                axis = column.split(" ")[0]
                delta = aligned[column] - plain[column]
                assert np.allclose(delta, cfg.view.shift["xyz".index(axis)]), column
                checked += 1
            else:
                pd.testing.assert_series_equal(
                    aligned[column], plain[column], check_names=False
                )
    assert checked > 0

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"]["aligned"] is True
    assert len(provenance["box"]["length"]) == 3


# --------------------------------------------------------------------------- #
# 多体系对比
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def compare_runs(tmp_path_factory):
    """两个体系：同一份数据，视图零点不同（5 Å）。"""
    base = tmp_path_factory.mktemp("compare")
    for name in ("a", "b"):
        shutil.copytree(SYSTEM, base / name)
    config = base / "b" / "system.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "frames: [0, 20]", "frames: [0, 20]\n\nview:\n  origin: [0, 0, 5.0]"
        ),
        encoding="utf-8",
    )
    for name in ("a", "b"):
        assert cli.main(
            ["run", "--system", str(base / name), "--out", str(base / name / "out")]
        ) == 0
    return base


def _compare_config(
    directory: Path, align: str, runs: Path, analysis: str = "lineardensity"
) -> Path:
    config = directory / "compare.yaml"
    config.write_text(
        f"""items:
  - {{root: {runs / 'a' / 'out'}, label: 零点 0}}
  - {{root: {runs / 'b' / 'out'}, label: 零点 5}}
figure:
  analysis: {analysis}
  align: {align}
""",
        encoding="utf-8",
    )
    return config


def test_compare_aligns_box_axis(compare_runs, tmp_path):
    box = json.loads(
        (compare_runs / "a/out/provenance.json").read_text(encoding="utf-8")
    )["box"]["length"]
    length = float(box[2])  # 剖面沿 z

    cases = {
        "left": (0.0, length),
        "center": (-0.5 * length, 0.5 * length),
        "{z: 22.0}": (-22.0, length - 22.0),
    }
    for align, (low, high) in cases.items():
        out = tmp_path / f"cmp-{align}"
        config = _compare_config(tmp_path, align, compare_runs)
        assert cli.main(["compare", "--config", str(config), "--out", str(out)]) == 0

        provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
        assert provenance["xlim"] == pytest.approx([low, high])
        expected_shift = {
            "left": 0.0, "center": -0.5 * length, "{z: 22.0}": -22.0,
        }[align]
        assert all(
            item["shift"]["z"] == pytest.approx(expected_shift)
            for item in provenance["items"]
        )

        table = pd.read_csv(out / "tables" / "lineardensity_z.csv", encoding="utf-8-sig")
        assert table["x"].min() >= low
        assert table["x"].max() <= high


def test_compare_rejects_two_dimensional_analysis(compare_runs, tmp_path):
    config = _compare_config(tmp_path, "center", compare_runs, analysis="density-xy")
    assert cli.main(["compare", "--config", str(config), "--out", str(tmp_path / "x")]) == 3
