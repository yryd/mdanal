from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
from mdanal.figure.replot import replot_from
import mdanal.figure.engine as engine

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""schema_version: 1
name: contact
sources:
  T:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1000.0
    dump_every: 1
    frames: [0, 4]
    groups: {{all: all}}
figures:
{body}
""",
        encoding="utf-8",
    )
    return path


def _panel(product: str, **extra: str) -> str:
    lines = [
        "  - name: fig",
        "    panels:",
        "      - source: T",
        f"        pack: contact",
        f"        product: {product}",
        "        select: {first: all, second: all}",
    ]
    if extra:
        lines.append("        compute: {" + ", ".join(f"{key}: {value}" for key, value in extra.items()) + "}")
    return "\n".join(lines) + "\n"


def test_contact_count_and_coordination_share_blocked_table(tmp_path):
    path = _config(
        tmp_path,
        _panel("contact-count", cutoff="10.0", block_ps="1.5")
        .replace("      - source: T", "      - source: T")
        + "      - source: T\n        pack: contact\n        product: contact-coordination\n"
        "        select: {first: all, second: all}\n"
        "        compute: {cutoff: 10.0, block_ps: 1.5}\n",
    )
    out = render_project(read_project(path), tmp_path / "out")
    tables = list((out / "data" / "T" / "contact").glob("*/tables/contact.csv"))
    assert len(tables) == 1
    frame = pd.read_csv(tables[0])
    assert frame["time_ps"].iloc[0] == 0.0
    assert frame["time_ps"].iloc[-1] == 3.0
    assert frame["block_frames"].iloc[0] == 2
    assert (out / "figures" / "fig.png").is_file()


def test_contact_compare_and_stack(tmp_path):
    compare = _config(
        tmp_path,
        """  - name: cmp
    panels:
      - compare:
          pack: contact
          product: contact-count
          sources:
            - {source: T, label: cut8, select: {first: all, second: all}, compute: {cutoff: 8.0}}
            - {source: T, label: cut10, select: {first: all, second: all}, compute: {cutoff: 10.0}}
""",
    )
    out = render_project(read_project(compare), tmp_path / "cmp-out")
    assert (out / "figures" / "cmp.png").is_file()

    stack = _config(
        tmp_path / "stack",
        """  - name: stack
    panels:
      - stack:
          pack: contact
          product: contact-count
          sources:
            - {source: T, label: cut8, select: {first: all, second: all}, compute: {cutoff: 8.0, block_ps: 1.5}}
            - {source: T, label: cut10, select: {first: all, second: all}, compute: {cutoff: 10.0, block_ps: 1.5}}
""",
    )
    # _config uses tmp_path/figures.yaml; stack path parent exists
    stack.write_text(
        stack.read_text().replace(f"name: contact", "name: contact-stack"),
        encoding="utf-8",
    )
    captured = {}
    original = engine.chart.save

    def save(fig, target, dpi):
        captured["fig"] = fig
        return original(fig, target, dpi)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(engine.chart, "save", save)
    out = render_project(read_project(stack), tmp_path / "stack-out")
    monkeypatch.undo()
    ax = captured["fig"].axes[0]
    assert len(ax.collections) == 2
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert labels[:2] == ["cut8", "cut10"]
    assert "total" not in labels
    assert (out / "figures" / "stack.png").is_file()

    # replot stack from snapshot
    replot_from(out, tmp_path / "stack-replot")
    assert (tmp_path / "stack-replot" / "figures" / "stack.png").is_file()


def test_stack_rejects_x_mismatch(tmp_path):
    path = _config(
        tmp_path,
        """  - name: bad
    panels:
      - stack:
          pack: contact
          product: contact-count
          sources:
            - {source: T, label: a, select: {first: all, second: all}, compute: {block_ps: 1.0}}
            - {source: T, label: b, select: {first: all, second: all}, compute: {block_ps: 1.5}}
""",
    )
    with pytest.raises(Exception, match="x 轴"):
        render_project(read_project(path), tmp_path / "out")


def test_stack_rejects_product_without_curve_request(tmp_path):
    path = _config(
        tmp_path,
        """  - name: bad
    panels:
      - stack:
          pack: density
          product: density-line
          sources:
            - {source: T, label: a, select: {group: all}}
            - {source: T, label: b, select: {group: all}}
""",
    )
    from mdanal.errors import ValidationError
    with pytest.raises(ValidationError, match="不是可 stack"):
        render_project(read_project(path), tmp_path / "out")
