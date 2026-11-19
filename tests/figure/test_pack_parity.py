from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import check_project, render_project

ROOT = Path(__file__).resolve().parents[1]
TINY = ROOT / "fixtures" / "tiny"
BASELINE = ROOT / "baseline"


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: parity
render: {{lang: zh, dpi: 60}}
sources:
  tiny:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 20]
    naming: {{from_data: {TINY / 'data.lmp'}}}
    groups:
      all: "all"
      o1: "type 1"
      o3: "type 3"
      o13: "type 1 3"
      oh: "type 5 6"
figures:
  - name: density
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: density, product: density-2d, select: {{group: all}}, compute: {{delta: 1.0, binsize: 0.5}}, plot: {{plane: xy}}}}
  - name: line
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: density, product: density-line, select: {{group: all}}, compute: {{delta: 1.0, binsize: 0.5}}, plot: {{axis: z}}}}
  - name: rdf
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: rdf, product: rdf, select: {{a: o3, b: o1}}, compute: {{range: [2.0, 12.0], nbins: 50}}}}
  - name: hbond
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: hbond, product: hbond-count, select: {{donor: o13, hydrogen: oh, acceptor: o13}}, compute: {{d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150}}}}
  - name: hbond_type
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: hbond, product: hbond-type, select: {{donor: o13, hydrogen: oh, acceptor: o13}}, compute: {{d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, figure_axis: rate}}}}
  - name: hbond_lifetime
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: hbond, product: hbond-lifetime, select: {{donor: o13, hydrogen: oh, acceptor: o13}}, compute: {{d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}}}
  - name: msd
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: msd, product: msd-raw, select: {{group: all}}, compute: {{msd_type: xyz, fft: true}}}}
  - name: velocity
    layout: {{ncols: 1}}
    panels:
      - {{source: tiny, pack: velocity, product: velocity, select: {{group: all, ref: all}}, compute: {{dim: z, vdim: z, bin_width: 2.0, grouping: molecules, sym: false}}}}
""",
        encoding="utf-8",
    )
    return path


@pytest.mark.analysis
def test_hbond_tables_match_baseline(tmp_path):
    if not BASELINE.is_dir():
        pytest.skip("本地 baseline 快照不存在（tests/baseline 不入库）")
    project = read_project(_config(tmp_path))
    assert check_project(project) == []
    out = render_project(project, tmp_path / "out")
    produced = {path.stem: path for path in (out / "data").rglob("*.csv")}

    for table in ("density_xy", "density_xz", "lineardensity_z", "rdf", "msd", "velocity"):
        assert table in produced, table
    for table in ("hbond_count", "hbond_occupancy", "hbond_type", "hbond_lifetime"):
        assert table in produced, table

    expected = {
        "hbond_count": "hbond/tables/hbond_count.csv",
        "hbond_occupancy": "hbond/tables/hbond_occupancy.csv",
        "hbond_type": "hbond_type/tables/hbond_type.csv",
        "hbond_lifetime": "hbond_lifetime/tables/hbond_lifetime.csv",
    }
    for table, rel in expected.items():
        old = pd.read_csv(BASELINE / rel, encoding="utf-8-sig")
        new = pd.read_csv(produced[table], encoding="utf-8-sig")
        assert len(new.columns) == len(old.columns), table
        assert len(new) == len(old), table
        for index, (new_col, old_col) in enumerate(zip(new.columns, old.columns)):
            if pd.api.types.is_numeric_dtype(old[old_col]):
                assert np.allclose(
                    new[new_col].to_numpy(dtype=float),
                    old[old_col].to_numpy(dtype=float),
                    rtol=1e-7,
                    atol=1e-9,
                    equal_nan=True,
                ), f"{table}[{index}]"

    msd = pd.read_csv(produced["msd"], encoding="utf-8-sig")
    assert "dt_ns" in msd.columns
    assert msd["dt_ns"].iloc[1] == pytest.approx(0.005)
