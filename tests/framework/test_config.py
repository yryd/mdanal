"""配置层：system.yaml、视图、选择、命名、多段拼接。"""

from __future__ import annotations

import json

import pytest

from mdanal.config.registry import build_plan
from mdanal.config.system import load_universe, read_system, resolve_group
from mdanal.errors import ValidationError
from mdanal.run.runner import prepare

from helpers import (
    SYSTEM,
    fake_registry,
    load_fake,
    raw_universe,
    split_trajectory,
    write_system,
)


def test_missing_system_yaml(tmp_path):
    with pytest.raises(ValidationError, match="找不到 system.yaml"):
        read_system(tmp_path)


def test_wrong_selection_count(tiny, tmp_path):
    path = write_system(
        tmp_path, tiny.topology, tiny.trajectory, '  - {name: fake, sel: ["all"]}'
    )
    with pytest.raises(ValidationError, match="需要 2 个"):
        build_plan(read_system(path), fake_registry())


def test_unknown_analysis(tiny, tmp_path):
    path = write_system(
        tmp_path, tiny.topology, tiny.trajectory, '  - {name: foo, sel: ["all"]}'
    )
    with pytest.raises(ValidationError, match="不存在"):
        build_plan(read_system(path), fake_registry())


def test_unknown_parameter(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"], deltax: 1}',
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), fake_registry())


def test_duplicate_directory(tiny, tmp_path):
    analyses = (
        '  - {name: fake, sel: ["all", "all"]}\n'
        '  - {name: fake, sel: ["all", "all"]}'
    )
    path = write_system(tmp_path, tiny.topology, tiny.trajectory, analyses)
    with pytest.raises(ValidationError, match="重复使用"):
        build_plan(read_system(path), fake_registry())


def test_unknown_view_field(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra="view:\n  centre: [0, 0, 0]\n",
    )
    with pytest.raises(ValidationError, match="未知字段"):
        read_system(path)


def test_view_window_is_moved_to_analysis(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra="view:\n  window:\n    z: [1, 2]\n",
    )
    with pytest.raises(ValidationError, match="plot.window"):
        read_system(path)


def test_annotation_unknown_field_is_rejected(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        "  - name: fake\n"
        '    sel: ["all", "all"]\n'
        "    annotate:\n"
        "      - {kind: hline, at: 1.0, colour: red}",
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), fake_registry())


def test_empty_selection_is_rejected(tiny):
    universe = load_universe(tiny)
    with pytest.raises(ValidationError, match="解析为空"):
        resolve_group(tiny, universe, "type 3-13")


def test_input_state_matches_dump_header(tiny):
    assert tiny.input_state == "unwrapped"
    assert tiny.input_evidence == "xu yu zu"


def test_coordinates_use_original_frame(tiny):
    universe = load_universe(tiny)
    universe.trajectory[tiny.frames[0]]

    z = universe.atoms.positions[:, 2]
    assert z.min() >= -1e-6
    assert z.max() <= universe.dimensions[2] + 1e-6

    import numpy as np

    low, high = (float(np.quantile(z, q)) for q in (0.4, 0.6))
    low += tiny.view.shift[2]
    high += tiny.view.shift[2]
    expected = int(
        ((z + tiny.view.shift[2] > low) & (z + tiny.view.shift[2] < high)).sum()
    )
    assert universe.select_atoms(f"prop z > {low} and prop z < {high}").n_atoms == expected


def test_in_box_view_keeps_atoms_inside(tiny):
    import numpy as np

    universe = load_universe(tiny, coordinates="in_box")
    for frame in (tiny.frames[0], tiny.frames[0] + 1):
        universe.trajectory[frame]
        length = np.asarray(universe.dimensions[:3])
        positions = universe.atoms.positions
        assert np.all(positions >= -1e-6)
        assert np.all(positions <= length + 1e-6)


def test_naming_from_data(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra=f"naming:\n  from_data: {tiny.topology}\n",
    )
    probe = read_system(path)
    prepared = prepare(probe, build_plan(probe, fake_registry()))
    universe = prepared.views["in_box"]

    assert set(universe.atoms.elements) == {"C", "H", "O"}
    assert universe.select_atoms("resname TMA").n_atoms == universe.atoms.n_atoms
    assert prepared.naming is not None
    assert prepared.naming.residue_counts["TMA"] == universe.residues.n_residues
    assert prepared.naming.overrides == ()
    assert prepared.naming.atom_count == universe.atoms.n_atoms


def test_naming_rules_override_warns(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra=(
            f"naming:\n  from_data: {tiny.topology}\n"
            "  residues:\n    - {name: HONEY, types: [1, 2, 3, 4, 5, 6]}\n"
            '  atoms:\n    "1": OX\n'
        ),
    )
    probe = read_system(path)
    prepared = prepare(probe, build_plan(probe, fake_registry()))

    assert prepared.naming is not None
    assert prepared.naming.overrides
    assert "TMA→HONEY" in prepared.naming.warning
    universe = prepared.views["in_box"]
    assert prepared.naming.residue_counts["HONEY"] == universe.residues.n_residues
    assert universe.select_atoms("resname HONEY").n_atoms == universe.atoms.n_atoms
    assert (
        universe.select_atoms("resname HONEY and name OX").n_atoms
        == load_universe(tiny).select_atoms("type 1").n_atoms
    )


def test_naming_incomplete_is_rejected(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra='naming:\n  atoms:\n    "1": OX\n',
    )
    probe = read_system(path)
    with pytest.raises(ValidationError, match="没有分子名"):
        prepare(probe, build_plan(probe, fake_registry()))


def test_naming_keyword_is_rejected(tiny, tmp_path):
    path = write_system(
        tmp_path,
        tiny.topology,
        tiny.trajectory,
        '  - {name: fake, sel: ["all", "all"]}',
        extra=(
            f"naming:\n  from_data: {tiny.topology}\n"
            "  residues:\n    - {name: water, types: [1, 2, 3, 4, 5, 6]}\n"
        ),
    )
    probe = read_system(path)
    with pytest.raises(ValidationError, match="关键字"):
        prepare(probe, build_plan(probe, fake_registry()))


def test_segment_state_mismatch_is_rejected(tmp_path):
    first, second, _ = split_trajectory(tmp_path)
    second.write_text(
        second.read_text(encoding="utf-8").replace("xu yu zu", "x y z", 1),
        encoding="utf-8",
    )
    merged = tmp_path / "merged"
    merged.mkdir()
    path = write_system(
        merged,
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        '  - {name: fake, sel: [all_atoms, all_atoms]}',
        frames="[0, 10]",
    )
    with pytest.raises(ValidationError, match="坐标"):
        load_fake(path)


def test_seam_time_backward_is_reported(tmp_path):
    first, second, _ = split_trajectory(tmp_path)
    text = second.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("ITEM: TIMESTEP"):
            lines[index + 1] = "0\n"
            break
    second.write_text("".join(lines), encoding="utf-8")

    merged = tmp_path / "merged"
    merged.mkdir()
    path = write_system(
        merged,
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        '  - {name: fake, sel: [all_atoms, all_atoms]}',
        frames="[0, 10]",
    )
    from helpers import run_fake

    _, prepared = run_fake(path, tmp_path / "out")
    notes = prepared.cfg.seam_notes
    assert any("时间倒退" in note for note in notes)


def _write_dump_header(path, columns: str) -> None:
    path.write_text(
        "ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n1\n"
        "ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n"
        f"ITEM: ATOMS {columns}\n1 1 0.5 0.5 0.5\n",
        encoding="utf-8",
    )


def test_scan_matches_reader_coordinate_precedence(tmp_path):
    """扫描器必须和 MDAnalysis 的自动选列顺序一致：unscaled → scaled → unwrapped。"""
    from mdanal.config.system import _scan_dump

    both = tmp_path / "both.lammpstrj"
    _write_dump_header(both, "id type x y z xu yu zu")
    scan = _scan_dump(both)
    assert scan.conventions == ("unscaled", "unwrapped")
    assert scan.state == "wrapped"
    assert scan.evidence == "x y z"

    scaled = tmp_path / "scaled.lammpstrj"
    _write_dump_header(scaled, "id type xs ys zs")
    scan = _scan_dump(scaled)
    assert scan.conventions == ("scaled",)
    assert scan.state == "wrapped"

    scaled_unwrapped = tmp_path / "scaled_unwrapped.lammpstrj"
    _write_dump_header(scaled_unwrapped, "id type xsu ysu zsu")
    scan = _scan_dump(scaled_unwrapped)
    assert scan.conventions == ("scaled_unwrapped",)
    assert scan.state == "unwrapped"


def test_irregular_timestep_is_diagnosed(tmp_path):
    """同一段内 TIMESTEP 步差异常时，配置层必须留下明确提示。"""
    lines = (SYSTEM / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("ITEM: TIMESTEP")]
    frames = lines[starts[0] : starts[3]]
    steps = [i for i, line in enumerate(frames) if line.startswith("ITEM: TIMESTEP")]
    for index, step in zip(steps, (0, 100, 300)):
        frames[index + 1] = f"{step}\n"
    trajectory = tmp_path / "irregular.lammpstrj"
    trajectory.write_text("".join(frames), encoding="utf-8")
    path = tmp_path / "system.yaml"
    path.write_text(
        f"""name: irregular
topology: {SYSTEM / 'data.lmp'}
trajectory: {trajectory}
timestep_fs: 1.0
dump_every: 100
frames: [0, 3]
groups:
  all_atoms: "all"
analyses:
  - {{name: fake, sel: [all_atoms, all_atoms]}}
""",
        encoding="utf-8",
    )
    cfg = read_system(path)
    assert len(cfg.time_notes) == 1
    assert "TIMESTEP" in cfg.time_notes[0]
    assert "300" in cfg.time_notes[0]


def test_legal_segment_reset_has_no_time_note(tmp_path):
    first, second, total = split_trajectory(tmp_path, reset_second_steps=True)
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        f"[{first}, {second}]",
        "  - {name: fake, sel: [all_atoms, all_atoms]}\n",
        frames=f"[0, {total}]",
    )
    assert read_system(path).time_notes == ()
