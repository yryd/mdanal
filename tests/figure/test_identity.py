from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mdanal.errors import ValidationError
from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
from mdanal.figure.replot import replot_from

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _source(name: str = "A") -> str:
    return f"""  {name}:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 20]
    naming: {{from_data: {TINY / 'data.lmp'}}}
    groups:
      all: "all"
      o13: "type 1 3"
"""


def _panel(source: str, select: str, window: str = "[0.0, 0.05]") -> str:
    return f"""      - source: {source}
        pack: msd
        product: msd-fit
        select: {{group: {select}}}
        compute: {{msd_type: xyz, grouping: residues}}
        derive: {{fit: {{window_ns: {window}, intercept: free}}}}
"""


def _records(out: Path, figure: str) -> list[dict]:
    payload = json.loads((out / "figures" / f"{figure}.json").read_text(encoding="utf-8"))
    return payload["items"]


def _summary(root: Path, record: dict) -> pd.Series:
    path = root / record["tables"]["msd_fit_summary"]["path"]
    return pd.read_csv(path, encoding="utf-8-sig").iloc[0]


def test_derive_cache_separates_select_groups(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: selections\nsources:\n"
        + _source()
        + "figures:\n  - name: both\n    layout: {ncols: 2}\n    panels:\n"
        + _panel("A", "all")
        + _panel("A", "o13"),
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    records = _records(out, "both")
    assert records[0]["base"] != records[1]["base"]
    assert records[0]["tables"]["msd"]["sha256"] != records[1]["tables"]["msd"]["sha256"]
    d0 = _summary(out, records[0])["D_A2_per_ps"]
    d1 = _summary(out, records[1])["D_A2_per_ps"]
    assert d0 != pytest.approx(d1)


def test_multiple_derive_windows_do_not_overwrite(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: windows\nsources:\n"
        + _source()
        + "figures:\n  - name: early\n    panels:\n"
        + _panel("A", "all", "[0.0, 0.02]")
        + "  - name: late\n    panels:\n"
        + _panel("A", "all", "[0.03, 0.05]"),
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    early = _records(out, "early")[0]
    late = _records(out, "late")[0]
    assert early["derive"] != late["derive"]
    assert early["tables"]["msd_fit_summary"]["sha256"] != late["tables"]["msd_fit_summary"]["sha256"]
    assert _summary(out, early)["fit_end_ns"] != _summary(out, late)["fit_end_ns"]

    replot_from(out, tmp_path / "replot", dpi=40)
    assert (tmp_path / "replot" / "figures" / "early.png").is_file()
    assert (tmp_path / "replot" / "figures" / "late.png").is_file()


def test_replot_rejects_tampered_table(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: tamper\nsources:\n"
        + _source()
        + "figures:\n  - name: f\n    panels:\n"
        + _panel("A", "all"),
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    record = _records(out, "f")[0]
    table = out / record["tables"]["msd"]["path"]
    table.write_text(table.read_text(encoding="utf-8") + "\n1,999\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="已变化"):
        replot_from(out, tmp_path / "replot")


def test_replot_rejects_unsafe_overwrite(tmp_path):
    path = tmp_path / "figures.yaml"
    path.write_text(
        "schema_version: 1\nname: safe\nsources:\n"
        + _source()
        + "figures:\n  - name: f\n    panels:\n"
        + _panel("A", "all"),
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    target = tmp_path / "replot" / "figures" / "f.png"
    target.parent.mkdir(parents=True)
    target.write_text("human image", encoding="utf-8")
    with pytest.raises(ValidationError, match="已存在"):
        replot_from(out, tmp_path / "replot")
    replot_from(out, tmp_path / "replot", force=True)
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
