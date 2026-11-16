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
    lag = np.arange(n_frames) * dt
    assert np.allclose(table["dt_ps"], lag)
    assert np.allclose(table["msd_A2"], (vx * lag) ** 2)


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
        assert memory["dt_ps"].min() >= 0
        assert np.allclose(memory["dt_ps"], np.arange(total) * 5.0)


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
    assert np.allclose(table["dt_ps"], [0.0, 5.0, 10.0])


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
