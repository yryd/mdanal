from __future__ import annotations

from pathlib import Path

import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import check_project, render_project
from mdanal.figure.replot import replot_from
from mdanal.errors import ValidationError

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: test
render: {{lang: zh, dpi: 80}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 20]
    groups: {{tma: "all"}}
""",
        encoding="utf-8",
    )
    path.write_text(path.read_text(encoding="utf-8") + body, encoding="utf-8")
    return path


def test_render_msd_raw(tmp_path):
    config = _config(
        tmp_path,
        """figures:
  - name: msd
    layout: {ncols: 1}
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {group: tma}
        compute: {msd_type: xyz, grouping: residues}
""",
    )
    project = read_project(config)
    assert check_project(project) == []
    out = render_project(project, tmp_path / "out")
    assert (out / "figures" / "msd.png").is_file()
    assert (out / "figures" / "msd.json").is_file()
    assert list((out / "data" / "A" / "msd").glob("*/tables/msd.csv"))


def test_density_plane_reuses_compute(tmp_path):
    body = """figures:
  - name: density
    layout: {ncols: 2}
    panels:
"""
    for plane in ("xy", "xz"):
        body += f"""      - source: A
        pack: density
        product: density-2d
        select: {{group: tma}}
        compute: {{delta: 2.0, binsize: 2.0}}
        plot: {{plane: {plane}}}
"""
    body += """      - source: A
        pack: density
        product: density-line
        select: {group: tma}
        compute: {delta: 2.0, binsize: 2.0}
        plot: {axis: z}
"""
    project = read_project(_config(tmp_path, body))
    out = render_project(project, tmp_path / "out")
    dirs = list((out / "data" / "A" / "density").iterdir())
    assert len(dirs) == 1
    assert (out / "figures" / "density.png").is_file()


def test_compare_msd_curves(tmp_path):
    config = tmp_path / "figures.yaml"
    config.write_text(
        f"""schema_version: 1
name: compare
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 20]
    groups: {{tma: "all"}}
  B:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 20]
    groups: {{tma: "all"}}
figures:
  - name: msd-compare
    layout: {{ncols: 1}}
    panels:
      - compare:
          pack: msd
          product: msd-raw
          select: {{group: tma}}
          sources:
            - {{source: A, label: A}}
            - {{source: B, label: B}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(config), tmp_path / "out")
    assert (out / "figures" / "msd-compare.png").is_file()
    payload = (out / "figures" / "msd-compare.json").read_text(encoding="utf-8")
    assert '"kind": "compare"' in payload


def test_render_then_replot(tmp_path):
    config = _config(
        tmp_path,
        """figures:
  - name: msd
    layout: {ncols: 1}
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {group: tma}
""",
    )
    out = render_project(read_project(config), tmp_path / "out")
    written = replot_from(out, tmp_path / "replot", dpi=60)
    assert len(written) == 1
    assert written[0].is_file()


def test_check_missing_derive(tmp_path):
    config = _config(
        tmp_path,
        """figures:
  - name: msd
    layout: {ncols: 1}
    panels:
      - source: A
        pack: msd
        product: msd-fit
        select: {group: tma}
""",
    )
    problems = check_project(read_project(config))
    assert any("derive.fit" in problem for problem in problems)


def test_field_compare_rejected(tmp_path):
    body = """figures:
  - name: density
    layout: {ncols: 1}
    panels:
      - compare:
          pack: density
          product: density-2d
          select: {group: tma}
          sources:
            - {source: A, label: A}
            - {source: B, label: B}
"""
    path = _config(tmp_path, body)
    data = path.read_text(encoding="utf-8")
    data = data.replace(
        "sources:\n  A:",
        "sources:\n  B:\n    topology: %s\n    trajectory: %s\n    groups: {tma: all}\n  A:"
        % (TINY / "data.lmp", TINY / "run.lammpstrj"),
    )
    path.write_text(data, encoding="utf-8")
    problems = check_project(read_project(path))
    assert any("不能 compare" in problem or "不是可 compare" in problem for problem in problems)
