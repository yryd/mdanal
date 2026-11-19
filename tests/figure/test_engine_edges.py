from __future__ import annotations

from pathlib import Path

import pytest

from mdanal.errors import ValidationError
from mdanal.figure.config import read_project
from mdanal.figure.engine import check_project, render_project
from mdanal.figure.replot import replot_from

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _project(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: edge
render: {{lang: zh, dpi: 60}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: "all", o: "type 1 3", h: "type 5 6"}}
figures:
{body}""",
        encoding="utf-8",
    )
    return path


def test_msd_fit_and_rdc(tmp_path):
    path = _project(
        tmp_path,
        """  - name: fit
    panels:
      - source: A
        pack: msd
        product: msd-fit
        select: {group: all}
        compute: {msd_type: xyz}
        derive: {fit: {window_ns: [0.000001, 0.000005]}}
  - name: rdc
    panels:
      - source: A
        pack: msd
        product: msd-rdc
        select: {group: all}
        compute: {msd_type: xyz}
        derive: {rdc: {}}
""",
    )
    project = read_project(path)
    assert check_project(project) == []
    out = render_project(project, tmp_path / "out")
    assert (out / "figures" / "fit.png").is_file()
    assert (out / "figures" / "rdc.png").is_file()


def test_hbond_type_without_naming_is_check_error(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: edge
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{o: "type 1 3", h: "type 5 6"}}
figures:
  - name: type
    panels:
      - source: A
        pack: hbond
        product: hbond-type
        select: {{donor: o, hydrogen: h, acceptor: o}}
""",
        encoding="utf-8",
    )
    problems = check_project(read_project(path))
    assert any("naming" in problem for problem in problems)


def test_force_guard_rejects_foreign_output(tmp_path):
    path = _project(
        tmp_path,
        """  - name: msd
    panels:
      - {source: A, pack: msd, product: msd-raw, select: {group: all}}
""",
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(ValidationError, match="不是本程序"):
        render_project(read_project(path), out, force=True)
    assert (out / "keep.txt").is_file()


def test_replot_compare(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: cmp\nsources:\n"
        f"  A:\n    topology: {TINY / 'data.lmp'}\n    trajectory: {TINY / 'run.lammpstrj'}\n    frames: [0, 8]\n    groups: {{all: all}}\n"
        f"  B:\n    topology: {TINY / 'data.lmp'}\n    trajectory: {TINY / 'run.lammpstrj'}\n    frames: [0, 8]\n    groups: {{all: all}}\n"
        """figures:
  - name: cmp
    panels:
      - compare:
          pack: msd
          product: msd-raw
          select: {group: all}
          sources: [{source: A, label: A}, {source: B, label: B}]
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    written = replot_from(out, tmp_path / "replot", dpi=50)
    assert written and written[0].is_file()
