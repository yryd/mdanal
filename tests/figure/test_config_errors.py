from __future__ import annotations

from pathlib import Path

import pytest

from mdanal.errors import ValidationError
from mdanal.figure.config import read_project

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _base(figures: str, *, name: str = "test") -> str:
    return f"""schema_version: 1
name: {name}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 5]
    groups: {{all: "all"}}
figures:
{figures}
"""


def test_unknown_field_rejected(tmp_path):
    text = _base(
        """  - name: f
    layout: {ncols: 1}
    panels:
      - {source: A, pack: msd, product: msd-raw, select: {group: all}, typo: 1}
"""
    )
    with pytest.raises(ValidationError, match="typo"):
        read_project(_write(tmp_path, text))


def test_unsafe_figure_name_rejected(tmp_path):
    text = _base(
        """  - name: ../escape
    layout: {ncols: 1}
    panels:
      - {source: A, pack: msd, product: msd-raw, select: {group: all}}
"""
    )
    with pytest.raises(ValidationError, match="路径分隔符"):
        read_project(_write(tmp_path, text))


def test_duplicate_figure_name_rejected(tmp_path):
    panel = """      - {source: A, pack: msd, product: msd-raw, select: {group: all}}
"""
    text = _base("  - name: f\n    panels:\n" + panel + "  - name: f\n    panels:\n" + panel)
    with pytest.raises(ValidationError, match="重复"):
        read_project(_write(tmp_path, text))


def test_compare_requires_two_sources(tmp_path):
    text = _base(
        """  - name: f
    panels:
      - compare:
          pack: msd
          product: msd-raw
          select: {group: all}
          sources: [{source: A, label: A}]
"""
    )
    with pytest.raises(ValidationError, match="至少两个"):
        read_project(_write(tmp_path, text))


def test_missing_source_rejected(tmp_path):
    text = _base(
        """  - name: f
    panels:
      - {source: B, pack: msd, product: msd-raw, select: {group: all}}
"""
    )
    with pytest.raises(ValidationError, match="sources"):
        read_project(_write(tmp_path, text))
