"""msd 的算术测试。

审计中按插件拆分；A2–A5 继续补解析/守恒用例。
"""

from __future__ import annotations

import json

import MDAnalysis as mda
import numpy as np
import pandas as pd
import pytest
from MDAnalysis.analysis.msd import EinsteinMSD
from MDAnalysis.coordinates.memory import MemoryReader
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
    raw_universe,
    selection_count,
    split_trajectory,
    write_system,
)

pytestmark = pytest.mark.analysis


def test_msd_matches_raw_coordinates(real):
    cfg, _ = real
    continuous = load_universe(cfg, coordinates="continuous")
    raw = raw_universe(cfg)

    lab_positions = []
    dimensions = []
    for frame in range(START, STOP):
        continuous.trajectory[frame]
        raw.trajectory[frame]
        # 新契约的 continuous 是实验室绝对坐标；raw 读取器返回盒局部坐标。
        origin = np.asarray(cfg.geometry.frame(frame).origin, dtype=float)
        lab = raw.atoms.positions + origin
        assert np.allclose(continuous.atoms.positions, lab, atol=1e-6)
        lab_positions.append(lab.copy())
        dimensions.append(raw.trajectory.ts.dimensions.copy())

    lab_universe = mda.Universe.empty(continuous.atoms.n_atoms, trajectory=True)
    lab_universe.load_new(
        np.asarray(lab_positions),
        dimensions=np.asarray(dimensions),
        format=MemoryReader,
    )

    results = []
    for universe in (continuous, lab_universe):
        analysis = EinsteinMSD(
            universe.atoms, select="all", msd_type="xyz", fft=True
        )
        analysis.run(start=START, stop=STOP)
        results.append(np.asarray(analysis.results.timeseries))
    assert np.allclose(results[0], results[1], rtol=1e-6, atol=1e-9)


# --------------------------------------------------------------------------- #
# 端到端：输出、视图、确定性
# --------------------------------------------------------------------------- #


def test_msd_matches_ballistic_motion():
    """匀速直线运动时 MSD = (v·Δt)²，用来验证时间轴与单位。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import msd as msd_module

    n_frames, n_atoms, dt, vx = 6, 2, 2.0, 1.5
    coords = np.zeros((n_frames, n_atoms, 3))
    coords[:, :, 0] = np.arange(n_frames)[:, None] * dt * vx
    universe = mda.Universe.empty(n_atoms, trajectory=True)
    universe.load_new(coords, format=MemoryReader)
    universe.trajectory.ts.dt = dt

    ctx = SimpleNamespace(
        groups={"group": SimpleNamespace(atoms=universe.atoms)},
        start=0,
        stop=n_frames,
        params={"msd_type": "xyz", "fft": False},
    )
    table = msd_module.run(ctx)["msd"]
    lag_ns = np.arange(n_frames) * dt / 1000.0
    lag_ps = np.arange(n_frames) * dt
    assert np.allclose(table["dt_ns"], lag_ns)
    assert np.allclose(table["msd_A2"], (vx * lag_ps) ** 2)


def _write_coordinate_dump(path, columns: str, rows: list[tuple], n_atoms: int) -> None:
    """写一个 3 帧、只有第 1 个原子移动的 LAMMPS dump。"""
    lines: list[str] = []
    for step, values in enumerate(rows):
        lines += [
            "ITEM: TIMESTEP",
            str(step),
            "ITEM: NUMBER OF ATOMS",
            str(n_atoms),
            "ITEM: BOX BOUNDS pp pp pp",
            "0 10",
            "0 10",
            "0 10",
            f"ITEM: ATOMS {columns}",
        ]
        n_coordinates = len(columns.split()) - 2
        for atom in range(1, n_atoms + 1):
            if atom == 1:
                lines.append("1 1 " + " ".join(str(value) for value in values))
            else:
                lines.append(
                    f"{atom} 1 " + " ".join(["0.5"] * n_coordinates)
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_dual_coordinate_columns_use_unwrapped(real, tmp_path):
    """同时有 x 和 xu 时，连续位移必须用 xu，不能按读取器的默认 x。"""
    cfg, _ = real
    n_atoms = len(raw_universe(cfg).atoms)
    trajectory = tmp_path / "dual.lammpstrj"
    _write_coordinate_dump(
        trajectory,
        "id type x y z xu yu zu",
        [(9.0, 0.05, 0.05, 9.0, 0.05, 0.05),
         (1.0, 0.05, 0.05, 11.0, 0.05, 0.05),
         (3.0, 0.05, 0.05, 13.0, 0.05, 0.05)],
        n_atoms,
    )
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        trajectory,
        "  - {name: msd, sel: [bynum 1], fft: false}\n",
        frames="[0, 3]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]


def test_segmented_reset_steps_keep_frame_time(tmp_path):
    """第二段 TIMESTEP 归零时，MSD 按帧序号计时，内存/读盘结果一致。"""
    first, second, total = split_trajectory(tmp_path, reset_second_steps=True)
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        "  - {name: msd, tag: one, sel: [all_atoms]}\n"
        "  - {name: msd, tag: two, sel: [all_atoms]}\n",
        frames=f"[0, {total}]",
    )
    out_memory = tmp_path / "memory"
    out_disk = tmp_path / "disk"
    assert cli.main(["run", "--system", str(path), "--out", str(out_memory)]) == 0
    assert (
        cli.main(
            ["run", "--system", str(path), "--out", str(out_disk), "--no-memory"]
        )
        == 0
    )
    provenance = json.loads(
        (out_memory / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["memory"]["enabled"] is True

    for tag in ("one", "two"):
        memory = pd.read_csv(
            out_memory / f"msd-{tag}/tables/msd.csv", encoding="utf-8-sig"
        )
        disk = pd.read_csv(
            out_disk / f"msd-{tag}/tables/msd.csv", encoding="utf-8-sig"
        )
        pd.testing.assert_frame_equal(memory, disk)
        assert memory["dt_ns"].min() >= 0
        assert np.allclose(memory["dt_ns"], np.arange(total) * 5.0 / 1000.0)


def test_merged_reset_segments_match_single_file(tmp_path):
    """单段与"第二段 TIMESTEP 归零"的拼接段，MSD 数值和时间必须一致。"""
    first, second, total = split_trajectory(tmp_path, reset_second_steps=True)
    analyses = "  - {name: msd, sel: [all_atoms], fft: false}\n"
    single = write_system(
        tmp_path / "single",
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        analyses,
        frames=f"[0, {total}]",
    )
    merged = write_system(
        tmp_path / "merged",
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        analyses,
        frames=f"[0, {total}]",
    )
    out_single = tmp_path / "single/out"
    out_merged = tmp_path / "merged/out"
    assert cli.main(["run", "--system", str(single), "--out", str(out_single)]) == 0
    assert cli.main(["run", "--system", str(merged), "--out", str(out_merged)]) == 0
    a = pd.read_csv(out_single / "msd/tables/msd.csv", encoding="utf-8-sig")
    b = pd.read_csv(out_merged / "msd/tables/msd.csv", encoding="utf-8-sig")
    pd.testing.assert_frame_equal(a, b)


def _no_bond_system(
    tmp_path, *, scaled=False, wrapped_scaled=False, analyses=None, frames="[0, 3]"
):
    data = tmp_path / "data.lmp"
    data.write_text(
        """LAMMPS data file

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

1 1.0

Atoms # full

1 1 1 0.0 0.5 0.5 0.5
""",
        encoding="utf-8",
    )
    trajectory = tmp_path / "run.lammpstrj"
    lines = []
    values = [9.0, 11.0, 13.0] if scaled else [9.0, 1.0, 3.0]
    if wrapped_scaled:
        values = [value / 10.0 for value in [9.0, 1.0, 3.0]]
        columns = "id type xs ys zs"
    else:
        columns = "id type xsu ysu zsu" if scaled else "id type x y z"
    for step, value in enumerate(values):
        lines += [
            "ITEM: TIMESTEP",
            str(step),
            "ITEM: NUMBER OF ATOMS",
            "1",
            "ITEM: BOX BOUNDS pp pp pp",
            "0 10",
            "0 10",
            "0 10",
            f"ITEM: ATOMS {columns}",
        ]
        if wrapped_scaled:
            lines.append(f"1 1 {value} 0.5 0.5")
        else:
            lines.append(
                f"1 1 {value / 10 if scaled else value} 0.5 0.5"
            )
    trajectory.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return write_system(
        tmp_path,
        data,
        trajectory,
        analyses or "  - {name: msd, sel: [all_atoms], fft: false}\n",
        frames=frames,
    )


def test_wrapped_no_bond_continuous_view(tmp_path):
    """无键、只有包裹坐标时，按最小镜像逐帧展开后 MSD 应为 [0,4,16]。"""
    path = _no_bond_system(tmp_path)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]


def test_wrapped_no_bond_section_replays_from_zero(tmp_path):
    """section 从非零帧开始时，连续视图必须从 0 重放。"""
    path = _no_bond_system(
        tmp_path,
        analyses="  - {name: msd, sel: [all_atoms], fft: false, section: [1, 3]}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0]


def test_wrapped_scaled_unwrapped_no_bond(tmp_path):
    """xsu/ysu/zsu 也应走未包裹路径并得到同样 MSD。"""
    path = _no_bond_system(tmp_path, scaled=True)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]


def test_repeated_analyses_on_wrapped_view(tmp_path):
    """同一条连续视图被多条分析按不同 section 读取时，结果仍一致。"""
    path = _no_bond_system(
        tmp_path,
        analyses=(
            "  - {name: msd, tag: full, sel: [all_atoms], fft: false}\n"
            "  - {name: msd, tag: late, sel: [all_atoms], fft: false, section: [1, 3]}\n"
        ),
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    full = pd.read_csv(out / "msd-full/tables/msd.csv", encoding="utf-8-sig")
    late = pd.read_csv(out / "msd-late/tables/msd.csv", encoding="utf-8-sig")
    assert full["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]
    assert late["msd_A2"].round(6).tolist() == [0.0, 4.0]


def test_wrapped_no_bond_multi_segment_with_reset_steps(tmp_path):
    """两段包裹坐标、第二段 TIMESTEP 归零时，连续视图仍跨段展开。"""
    data = tmp_path / "data.lmp"
    data.write_text(
        """LAMMPS data file

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

1 1.0

Atoms # full

1 1 1 0.0 0.5 0.5 0.5
""",
        encoding="utf-8",
    )
    def frame(step, x):
        return [
            "ITEM: TIMESTEP", str(step), "ITEM: NUMBER OF ATOMS", "1",
            "ITEM: BOX BOUNDS pp pp pp", "0 10", "0 10", "0 10",
            "ITEM: ATOMS id type x y z", f"1 1 {x} 0.5 0.5",
        ]
    first = tmp_path / "a.lammpstrj"
    second = tmp_path / "b.lammpstrj"
    first.write_text("\n".join(frame(0, 9.0) + frame(1, 1.0)) + "\n", encoding="utf-8")
    second.write_text("\n".join(frame(0, 3.0)) + "\n", encoding="utf-8")
    path = write_system(
        tmp_path,
        data,
        f"[{first}, {second}]",
        "  - {name: msd, sel: [all_atoms], fft: false}\n",
        frames="[0, 3]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]
    assert np.allclose(table["dt_ns"], [0.0, 0.005, 0.01])


def test_wrapped_no_bond_memory_and_disk_agree(tmp_path):
    data = tmp_path / "data.lmp"
    data.write_text(
        """LAMMPS data file

1 atoms
1 atom types

0.0 10.0 xlo xhi
0.0 10.0 ylo yhi
0.0 10.0 zlo zhi

Masses

1 1.0

Atoms # full

1 1 1 0.0 0.5 0.5 0.5
""",
        encoding="utf-8",
    )
    values = [9.0, 1.0, 3.0, 5.0, 7.0, 9.0, 1.0, 3.0]
    lines = []
    for step, value in enumerate(values):
        lines += [
            "ITEM: TIMESTEP", str(step), "ITEM: NUMBER OF ATOMS", "1",
            "ITEM: BOX BOUNDS pp pp pp", "0 10", "0 10", "0 10",
            "ITEM: ATOMS id type x y z", f"1 1 {value} 0.5 0.5",
        ]
    trajectory = tmp_path / "run.lammpstrj"
    trajectory.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path = write_system(
        tmp_path,
        data,
        trajectory,
        "  - {name: msd, tag: one, sel: [all_atoms], fft: false}\n"
        "  - {name: msd, tag: two, sel: [all_atoms], fft: false}\n",
        frames="[0, 8]",
    )
    memory = tmp_path / "memory"
    disk = tmp_path / "disk"
    assert cli.main(["run", "--system", str(path), "--out", str(memory)]) == 0
    assert (
        cli.main(
            ["run", "--system", str(path), "--out", str(disk), "--no-memory"]
        )
        == 0
    )
    provenance = json.loads(
        (memory / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["memory"]["enabled"] is True
    for tag in ("one", "two"):
        a = pd.read_csv(memory / f"msd-{tag}/tables/msd.csv", encoding="utf-8-sig")
        b = pd.read_csv(disk / f"msd-{tag}/tables/msd.csv", encoding="utf-8-sig")
        pd.testing.assert_frame_equal(a, b)
        assert np.allclose(a["msd_A2"], 4.0 * np.arange(8) ** 2)


def test_wrapped_scaled_no_bond(tmp_path):
    """xs/ys/zs 的包裹坐标也应按同一连续视图展开。"""
    path = _no_bond_system(tmp_path, wrapped_scaled=True)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd/tables/msd.csv", encoding="utf-8-sig")
    assert table["msd_A2"].round(6).tolist() == [0.0, 4.0, 16.0]


def test_msd_default_uses_residue_com():
    """两个反向运动的原子同属一个残基时，质心 MSD 应接近 0。"""
    from types import SimpleNamespace

    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader
    from mdanal.analyses import msd as msd_module

    n_frames, dt = 6, 2.0
    coords = np.zeros((n_frames, 2, 3))
    coords[:, 0, 0] = np.arange(n_frames) * dt
    coords[:, 1, 0] = -np.arange(n_frames) * dt
    universe = mda.Universe.empty(
        2,
        n_residues=1,
        atom_resindex=[0, 0],
        trajectory=True,
    )
    universe.load_new(coords, format=MemoryReader)
    universe.trajectory.ts.dt = dt

    ctx = SimpleNamespace(
        groups={"group": SimpleNamespace(atoms=universe.atoms)},
        start=0,
        stop=n_frames,
        params={
            "msd_type": "xyz",
            "grouping": "residues",
            "fft": False,
        },
    )
    table = msd_module.run(ctx)["msd"]
    assert np.allclose(table["msd_A2"], 0.0, atol=1e-12)


def test_msd_fft_matches_direct_on_random_com():
    """FFT 路径与直接时间平均在随机质心轨迹上应一致。"""
    from mdanal.analyses import msd as msd_module

    rng = np.random.default_rng(7)
    com = rng.normal(size=(30, 4, 3))
    for msd_type in ("xyz", "xy", "z"):
        direct = msd_module._msd_from_com(com, msd_type, fft=False)
        fast = msd_module._msd_from_com(com, msd_type, fft=True)
        assert np.allclose(fast, direct, rtol=1e-10, atol=1e-10)


def test_msd_old_dt_ps_table_is_converted_to_ns():
    """旧 MSD 快照的 dt_ps 表仍可用于当前 ns 绘图。"""
    from types import SimpleNamespace
    from mdanal.analyses import msd as msd_module

    table = pd.DataFrame({"dt_ps": [0.0, 5.0, 10.0], "msd_A2": [0.0, 1.0, 4.0]})
    series = msd_module.build_series(SimpleNamespace(label=lambda key: key), {"msd": table})
    x = series[0].curves[0].x
    assert np.allclose(x, [0.0, 0.005, 0.01])


def test_msd_compare_panel_shows_series_legend():
    """compare 传入两个系列时，MSD render_panel 必须显示图例。"""
    from types import SimpleNamespace
    from mdanal.plot.figure import Figure
    from mdanal.plot.specs import Curve, PanelRequest, Series
    from mdanal.analyses import msd as msd_module

    ctx = SimpleNamespace(
        meta={},
        annotate=False,
        annotations=(),
        label=lambda key: key,
        window=lambda axis: None,
        size=lambda name="single": (3.5, 2.6),
        shift=(0.0, 0.0, 0.0),
    )
    series = [
        Series(name="a", curves=[Curve(x=[0, 1], y=[0, 1], label="water")]),
        Series(name="b", curves=[Curve(x=[0, 1], y=[0, 2], label="PIP")]),
    ]
    request = PanelRequest(
        recipe="msd",
        series=series,
        title="MSD",
        xlabel="t",
        ylabel="msd",
        options={"legend": True},
    )
    fig = Figure([msd_module.render_panel(ctx, request)], ncols=1).build()
    legend = fig.axes[0].get_legend()
    assert legend is not None
    assert {text.get_text() for text in legend.get_texts()} == {"water", "PIP"}


def test_msd_fft_is_translation_stable():
    """整体平移不应改变 MSD（检查大绝对坐标下的 FFT 抵消）。"""
    from mdanal.analyses import msd as msd_module

    rng = np.random.default_rng(11)
    com = rng.normal(size=(20, 3, 3))
    offset = np.array([1.0e6, 1.0e6, 1.0e6])
    direct = msd_module._msd_from_com(com, "xyz", fft=False)
    shifted = msd_module._msd_from_com(com + offset, "xyz", fft=True)
    assert np.allclose(shifted, direct, rtol=1e-6, atol=1e-6)


def test_msd_package_derives_and_multiple_figures(tmp_path):
    """一个 MSD run 可同时输出 raw/fit/rdc，且只计算一次基础表。"""
    from mdanal import cli
    from helpers import SYSTEM, write_system

    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        "  - name: msd\n"
        "    tag: multi\n"
        "    sel: [all_atoms]\n"
        "    section: [0, 8]\n"
        "    derive:\n"
        "      fit: {window_ns: [0.0, 0.02], intercept: free}\n"
        "      rdc: {}\n"
        "    figures:\n"
        "      raw: {}\n"
        "      fit: {}\n"
        "      rdc: {}\n",
        frames="[0, 8]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    base = out / "msd-multi"
    assert (base / "figures" / "msd.png").is_file()
    assert (base / "figures" / "msd-fit.png").is_file()
    assert (base / "figures" / "msd-rdc.png").is_file()
    assert (base / "tables" / "msd.csv").is_file()
    assert (base / "tables" / "msd_fit.csv").is_file()
    assert (base / "tables" / "msd_fit_summary.csv").is_file()
    assert (base / "tables" / "msd_rdc.csv").is_file()


def test_msd_derive_formula_and_rdc():
    """三维 MSD 的 D/RDC 公式和 ns→ps 换算。"""
    from types import SimpleNamespace
    from mdanal.analyses.msd import derive

    table = pd.DataFrame({"dt_ns": [0.0, 1.0, 2.0], "msd_A2": [0.0, 6.0, 12.0]})
    ctx = SimpleNamespace(params={"msd_type": "xyz"})
    out = derive.run(ctx, {"msd": table}, {"fit": {"window_ns": [0.0, 2.0]}, "rdc": {}})
    summary = out["msd_fit_summary"].iloc[0]
    assert summary["D_A2_per_ps"] == pytest.approx(0.001)
    rdc = out["msd_rdc"]["rdc_A2_per_ps"].to_numpy()
    assert np.isnan(rdc[0])
    assert np.allclose(rdc[1:], 0.001)
