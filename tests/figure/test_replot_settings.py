from __future__ import annotations

from pathlib import Path

import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
from mdanal.figure.replot import replot_from
import mdanal.figure.replot as replot_module

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def test_replot_keeps_render_language_dpi_annotate_and_style(tmp_path, monkeypatch):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: settings
render: {{lang: en, dpi: 60, annotate: true}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: all}}
figures:
  - name: f
    title: {{zh: 中文标题, en: English title}}
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {{group: all}}
        plot: {{title: {{zh: 中文, en: English}}}}
      - source: A
        pack: msd
        product: msd-raw
        select: {{group: all}}
        plot:
          palette: ["#00aa00"]
          rc: {{lines.linewidth: 7}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    captured = {}
    original = replot_module.chart.save

    def save(fig, target, dpi):
        captured["fig"] = fig
        captured["dpi"] = dpi
        return original(fig, target, dpi)

    monkeypatch.setattr(replot_module.chart, "save", save)
    replot_from(out, tmp_path / "replot")
    assert captured["dpi"] == 60
    fig = captured["fig"]
    assert fig._suptitle.get_text() == "English title"
    assert fig.axes[0].get_title() == "English"
    # 第二个 Panel 的显式 rc 是整图共享样式，重绘不能退回默认。
    assert fig.axes[0].lines[0].get_linewidth() == pytest.approx(7.0)
    # annotate=true 至少留下自动说明文本。
    assert fig.axes[0].texts
