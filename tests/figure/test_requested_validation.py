from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import check_project, render_project
from mdanal.figure import engine

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _base(tmp_path: Path, figures: str, *, dump_every=5000, frames="[0, 8]") -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: req
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: {dump_every}
    frames: {frames}
    naming: {{from_data: {TINY / 'data.lmp'}}}
    groups:
      all: "all"
      o13: "type 1 3"
      oh: "type 5 6"
figures:
{figures}""",
        encoding="utf-8",
    )
    return path


def test_hbond_count_does_not_require_lifetime(tmp_path):
    path = _base(
        tmp_path,
        """  - name: count
    panels:
      - source: A
        pack: hbond
        product: hbond-count
        select: {donor: o13, hydrogen: oh, acceptor: o13}
""",
        dump_every=100,
    )
    out = render_project(read_project(path), tmp_path / "out")
    names = {p.stem for p in (out / "data").rglob("*.csv")}
    assert "hbond_count" in names
    assert "hbond_lifetime" not in names
    assert (out / "figures" / "count.png").is_file()


def test_density_line_does_not_build_3d_grid(tmp_path):
    path = _base(
        tmp_path,
        """  - name: line
    panels:
      - source: A
        pack: density
        product: density-line
        select: {group: all}
        compute: {delta: 2.0, binsize: 2.0}
""",
    )
    out = render_project(read_project(path), tmp_path / "out")
    names = {p.stem for p in (out / "data").rglob("*.csv")}
    assert "lineardensity_z" in names
    assert "density_xy" not in names


def test_check_rejects_bad_param_values_and_unknown_derive(tmp_path):
    path = _base(
        tmp_path,
        """  - name: bad
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {group: all}
        compute: {msd_type: abc, fft: "false"}
      - source: A
        pack: rdf
        product: rdf
        select: {a: all, b: all}
        compute: {nbins: -1}
        derive: {fit: {}}
""",
    )
    problems = check_project(read_project(path))
    text = "\n".join(problems)
    assert "msd_type" in text
    assert "fft" in text
    assert "nbins" in text
    assert "不支持 derive" in text


def test_only_requested_packs_are_loaded(tmp_path, monkeypatch):
    path = _base(
        tmp_path,
        """  - name: msd
    panels:
      - {source: A, pack: msd, product: msd-raw, select: {group: all}}
""",
    )
    project = read_project(path)
    original = engine.load_pack

    def guarded(name):
        if name == "broken":
            raise RuntimeError("broken plugin")
        return original(name)

    monkeypatch.setattr(engine, "load_pack", guarded)
    assert check_project(project) == []


def test_removed_density_control_params_are_rejected(tmp_path):
    path = _base(
        tmp_path,
        """  - name: density
    panels:
      - source: A
        pack: density
        product: density-2d
        select: {group: all}
        compute: {delta: 2.0, directions: [xy], sum_axis: y}
""",
    )
    text = "\n".join(check_project(read_project(path)))
    assert "directions" in text
    assert "sum_axis" in text
