from __future__ import annotations

from pathlib import Path

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _source(name: str) -> str:
    return f"""  {name}:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: "all"}}
"""


def test_cross_source_density_side_by_side(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: cross\nsources:\n"
        + _source("A")
        + _source("B")
        + """figures:
  - name: density-ab
    layout: {ncols: 2}
    panels:
      - {source: A, pack: density, product: density-2d, select: {group: all}, compute: {delta: 2.0, binsize: 2.0}, plot: {plane: xy}}
      - {source: B, pack: density, product: density-2d, select: {group: all}, compute: {delta: 2.0, binsize: 2.0}, plot: {plane: xy}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    assert (out / "figures" / "density-ab.png").is_file()
    assert len(list((out / "data" / "A" / "density").iterdir())) == 1
    assert len(list((out / "data" / "B" / "density").iterdir())) == 1


def test_compare_rdf(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: cross\nsources:\n"
        + _source("A")
        + _source("B")
        + """figures:
  - name: rdf-compare
    layout: {ncols: 1}
    panels:
      - compare:
          pack: rdf
          product: rdf
          select: {a: all, b: all}
          compute: {range: [1.0, 6.0], nbins: 20}
          sources: [{source: A, label: A}, {source: B, label: B}]
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    assert (out / "figures" / "rdf-compare.png").is_file()


def test_compare_same_source_different_params(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: params
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: "all"}}
figures:
  - name: msd-params
    panels:
      - compare:
          pack: msd
          product: msd-raw
          select: {{group: all}}
          sources:
            - {{source: A, label: xyz, compute: {{msd_type: xyz}}}}
            - {{source: A, label: xy, compute: {{msd_type: xy}}}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    assert (out / "figures" / "msd-params.png").is_file()
    assert len(list((out / "data" / "A" / "msd").iterdir())) == 2
