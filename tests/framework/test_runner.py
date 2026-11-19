"""执行层：假分析跑通 prepare/execute、窗口、切片、内存、多段与落盘。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from mdanal.errors import ValidationError
from helpers import SYSTEM, load_fake, run_fake, split_trajectory, write_system

FAKE = "  - {name: fake, sel: [all_atoms, all_atoms]}\n"


def _plain_system(tmp_path, *, extra: str = "", frames: str = "[0, 5]"):
    return write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        FAKE,
        frames=frames,
        extra=extra,
    )


def test_fake_analysis_end_to_end(tmp_path):
    path = _plain_system(tmp_path)
    cfg, prepared = run_fake(path, tmp_path / "out")

    out = tmp_path / "out"
    assert (out / "fake" / "tables" / "fake.csv").is_file()
    assert (out / "fake" / "figures" / "fake.png").is_file()

    table = pd.read_csv(out / "fake/tables/fake.csv", encoding="utf-8-sig")
    assert list(table.columns) == ["x_angstrom", "y", "y2", "start", "stop"]
    assert len(table) == 5
    assert set(table["start"]) == {0}
    assert set(table["stop"]) == {5}

    manifest = pd.read_csv(out / "manifest.csv", encoding="utf-8-sig")
    assert list(manifest["directory"]) == ["fake"]
    assert json.loads(manifest.loc[0, "params"]) == {"scale": 2.0, "label": "fake"}

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["analyses"][0]["meta"] == {
        "start": 0,
        "stop": 5,
        "scale": 2.0,
    }
    assert "window" not in provenance["view"]
    assert provenance["analyses"][0]["section"] is None


def test_window_only_affects_figure(tmp_path):
    plain = _plain_system(tmp_path / "plain")
    windowed = write_system(
        tmp_path / "windowed",
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        "  - {name: fake, sel: [all_atoms, all_atoms], "
        "plot: {window: {x: [2.0, 6.0]}}}\n",
        frames="[0, 5]",
    )

    run_fake(plain, tmp_path / "plain/out")
    run_fake(windowed, tmp_path / "windowed/out")

    a = pd.read_csv(tmp_path / "plain/out/fake/tables/fake.csv", encoding="utf-8-sig")
    b = pd.read_csv(tmp_path / "windowed/out/fake/tables/fake.csv", encoding="utf-8-sig")
    pd.testing.assert_frame_equal(a, b)
    assert (tmp_path / "windowed/out/fake/figures/fake.png").is_file()

    provenance = json.loads(
        (tmp_path / "windowed/out/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["analyses"][0]["window"] == {"x": [2.0, 6.0]}


def test_section_narrows_frames(tmp_path):
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        '  - {name: fake, sel: [all_atoms, all_atoms], section: [1, 4]}\n',
        frames="[0, 5]",
    )
    run_fake(path, tmp_path / "out")

    table = pd.read_csv(tmp_path / "out/fake/tables/fake.csv", encoding="utf-8-sig")
    assert len(table) == 3
    assert set(table["start"]) == {1}
    assert set(table["stop"]) == {4}

    provenance = json.loads(
        (tmp_path / "out/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["analyses"][0]["section"] == [1, 4]


def test_section_out_of_range_is_rejected(tmp_path):
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        '  - {name: fake, sel: [all_atoms, all_atoms], section: [0, 100]}\n',
        frames="[0, 5]",
    )
    with pytest.raises(ValidationError, match="超出体系窗口"):
        load_fake(path)


def test_selection_frame_is_window_start(tmp_path):
    path = _plain_system(tmp_path, frames="[1, 4]")
    prepared = load_fake(path)
    assert prepared.selection_frame == 1
    assert prepared.views["in_box"].trajectory.ts.frame == 1


def test_deterministic_tables(tmp_path):
    path = _plain_system(tmp_path)
    run_fake(path, tmp_path / "a")
    run_fake(path, tmp_path / "b")
    assert (tmp_path / "a/fake/tables/fake.csv").read_bytes() == (
        tmp_path / "b/fake/tables/fake.csv"
    ).read_bytes()


def test_aligned_tables_equal_plain_plus_shift(tmp_path):
    path = _plain_system(tmp_path, extra="view:\n  origin: [0, 0, 5.0]\n")
    cfg, _ = run_fake(path, tmp_path / "plain")
    run_fake(path, tmp_path / "aligned", aligned=True)

    plain = pd.read_csv(tmp_path / "plain/fake/tables/fake.csv", encoding="utf-8-sig")
    shifted = pd.read_csv(
        tmp_path / "aligned/fake/tables/fake.aligned.csv", encoding="utf-8-sig"
    )
    delta = shifted["x_angstrom"] - plain["x_angstrom"]
    assert np.allclose(delta, cfg.view.shift[0])
    pd.testing.assert_series_equal(shifted["y"], plain["y"])

    provenance = json.loads(
        (tmp_path / "aligned/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["render"]["aligned"] is True


def test_memory_and_disk_runs_agree(tmp_path):
    analyses = (
        '  - {name: fake, tag: one, sel: [all_atoms, all_atoms]}\n'
        '  - {name: fake, tag: two, sel: [all_atoms, all_atoms]}'
    )
    path = write_system(
        tmp_path, SYSTEM / "data.lmp", SYSTEM / "run.lammpstrj", analyses, frames="[0, 20]"
    )
    run_fake(path, tmp_path / "memory", memory=True)
    run_fake(path, tmp_path / "disk", memory=False)
    provenance = json.loads(
        (tmp_path / "memory/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["memory"]["enabled"] is True

    for directory in ("fake-one", "fake-two"):
        a = pd.read_csv(
            tmp_path / f"memory/{directory}/tables/fake.csv", encoding="utf-8-sig"
        )
        b = pd.read_csv(
            tmp_path / f"disk/{directory}/tables/fake.csv", encoding="utf-8-sig"
        )
        pd.testing.assert_frame_equal(a, b)


def test_merged_segments_match_single_file(tmp_path):
    first, second, total = split_trajectory(tmp_path)
    single = write_system(
        tmp_path / "single",
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        FAKE,
        frames=f"[0, {total}]",
    )
    merged = write_system(
        tmp_path / "merged",
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        FAKE,
        frames=f"[0, {total}]",
    )
    run_fake(single, tmp_path / "single/out")
    run_fake(merged, tmp_path / "merged/out")

    a = pd.read_csv(tmp_path / "single/out/fake/tables/fake.csv", encoding="utf-8-sig")
    b = pd.read_csv(tmp_path / "merged/out/fake/tables/fake.csv", encoding="utf-8-sig")
    pd.testing.assert_frame_equal(a, b)


def test_existing_output_refused_then_forced(tmp_path):
    path = _plain_system(tmp_path)
    run_fake(path, tmp_path / "out")
    with pytest.raises(ValidationError, match="已存在"):
        run_fake(path, tmp_path / "out")
    run_fake(path, tmp_path / "out", force=True)
    assert (tmp_path / "out/fake/tables/fake.csv").is_file()


def test_language_switch_renders_figure(tmp_path):
    path = _plain_system(tmp_path)
    run_fake(path, tmp_path / "en", lang="en")
    assert (tmp_path / "en/fake/figures/fake.png").is_file()
    provenance = json.loads(
        (tmp_path / "en/provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["render"]["language"] == "en"


def test_frame_times_ignore_timestep_reset(tmp_path):
    """多段续跑 TIMESTEP 归零时，所有视图仍按全局帧号计时。"""
    from mdanal.config.system import load_universe, read_system

    first, second, total = split_trajectory(tmp_path, reset_second_steps=True)
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        FAKE,
        frames=f"[0, {total}]",
    )
    cfg = read_system(path)
    expected = np.arange(total) * (cfg.dump_every * cfg.dt_ps)
    for view in ("in_box", "continuous"):
        universe = load_universe(cfg, coordinates=view)
        times = []
        for frame in range(len(universe.trajectory)):
            universe.trajectory[frame]
            times.append(universe.trajectory.ts.time)
        assert np.allclose(times, expected)


def test_force_refuses_to_clear_inputs_inside_output(tmp_path):
    """输出目录内若有输入文件，--force 必须在删除前拒绝。"""
    case = tmp_path / "case"
    path = write_system(
        case, SYSTEM / "data.lmp", SYSTEM / "run.lammpstrj", FAKE, frames="[0, 5]"
    )
    (case / "provenance.json").write_text("{}", encoding="utf-8")
    before = {item.name for item in case.iterdir()}
    with pytest.raises(ValidationError, match="位于输出目录"):
        run_fake(path, case, force=True)
    assert {item.name for item in case.iterdir()} == before
    assert (case / "system.yaml").is_file()


def test_force_refuses_symlink_to_input_inside_output(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "provenance.json").write_text("{}", encoding="utf-8")
    link = case / "traj-link"
    link.symlink_to(SYSTEM / "run.lammpstrj")
    path = tmp_path / "system.yaml"
    path.write_text(
        f"""name: link
topology: {SYSTEM / 'data.lmp'}
trajectory: {SYSTEM / 'run.lammpstrj'}
timestep_fs: 1.0
dump_every: 5000
frames: [0, 5]
groups:
  all_atoms: "all"
analyses:
  - {{name: fake, sel: [all_atoms, all_atoms]}}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="符号链接"):
        run_fake(path, case, force=True)
    assert link.is_symlink()
