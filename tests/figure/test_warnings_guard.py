from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdanal.errors import ValidationError
from mdanal.figure.catalog import load_pack
from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project, source_warnings
from mdanal.figure.model import PanelRef
from mdanal.figure.runtime import SourceRuntime, compute_context
from mdanal.config.source import parse_source

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _source_entry() -> str:
    return f"""  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 100
    frames: [0, 8]
    groups: {{all: "all"}}
"""


def _project(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text("schema_version: 1\nname: warn\nsources:\n" + _source_entry() + "figures:\n" + body, encoding="utf-8")
    return path


def test_time_notes_reach_project_and_context(tmp_path):
    path = _project(
        tmp_path,
        """  - name: msd
    panels:
      - {source: A, pack: msd, product: msd-raw, select: {group: all}}
""",
    )
    project = read_project(path)
    assert any("TIMESTEP" in warning for warning in source_warnings(project))
    out = render_project(project, tmp_path / "out")
    project_json = json.loads((out / "project.json").read_text(encoding="utf-8"))
    assert any("TIMESTEP" in warning for warning in project_json["warnings"])
    context_files = list((out / "data").rglob("context.json"))
    assert context_files
    context = json.loads(context_files[0].read_text(encoding="utf-8"))
    assert any("TIMESTEP" in warning for warning in context["warnings"])


def test_naming_from_data_is_guarded(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    names = out / "names.data"
    names.write_bytes((TINY / "data.lmp").read_bytes())
    (out / "project.json").write_text('{"schema_version": 1}', encoding="utf-8")
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: guard
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 3]
    naming: {{from_data: {names}}}
    groups: {{all: all}}
figures:
  - name: f
    panels:
      - {{source: A, pack: msd, product: msd-raw, select: {{group: all}}}}
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="位于输出目录"):
        render_project(read_project(path), out, force=True)
    assert names.is_file()


def test_nonperiodic_hbond_records_kernel_assumption(tmp_path):
    lines = (TINY / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("ITEM: BOX BOUNDS"):
            lines[index] = "ITEM: BOX BOUNDS pp pp ff\n"
    trajectory = tmp_path / "nonperiodic.lammpstrj"
    trajectory.write_text("".join(lines), encoding="utf-8")
    cfg = parse_source(
        "A",
        {
            "topology": str(TINY / "data.lmp"),
            "trajectory": str(trajectory),
            "frames": [0, 2],
            "naming": {"from_data": str(TINY / "data.lmp")},
            "groups": {"o13": "type 1 3", "oh": "type 5 6"},
        },
        base_dir=tmp_path,
        yaml_path=tmp_path / "figures.yaml",
    )
    pack = load_pack("hbond")
    ref = PanelRef(
        source="A",
        pack="hbond",
        product="hbond-count",
        select={"donor": "o13", "hydrogen": "oh", "acceptor": "o13"},
        compute={},
        plot={},
    )
    ctx = compute_context(SourceRuntime("A", cfg), pack, ref, requested_tables=frozenset({"hbond_count"}))
    assert ctx.geometry_meta["kernel_pbc"] == [True, True, True]
    assert ctx.geometry_meta["pbc_match"] is False
    assert any("内核" in warning or "PBC" in warning for warning in ctx.warnings)


def test_check_warns_nonperiodic_hbond_before_render(tmp_path):
    lines = (TINY / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("ITEM: BOX BOUNDS"):
            lines[index] = "ITEM: BOX BOUNDS pp pp ff\n"
    trajectory = tmp_path / "nonperiodic.lammpstrj"
    trajectory.write_text("".join(lines), encoding="utf-8")
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: geom
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {trajectory}
    frames: [0, 2]
    naming: {{from_data: {TINY / 'data.lmp'}}}
    groups: {{o13: "type 1 3", oh: "type 5 6"}}
figures:
  - name: hbond
    panels:
      - {{source: A, pack: hbond, product: hbond-count, select: {{donor: o13, hydrogen: oh, acceptor: o13}}}}
""",
        encoding="utf-8",
    )
    from mdanal.figure.engine import check_warnings
    assert any("内核" in warning or "PBC" in warning for warning in check_warnings(read_project(path)))
