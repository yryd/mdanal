from __future__ import annotations

from pathlib import Path

import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
from mdanal.figure.replot import replot_from
from mdanal.figure.overrides import read_overrides
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


def test_replot_config_overrides_presentation_only(tmp_path, monkeypatch):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: override
render: {{lang: zh, dpi: 70}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: all}}
figures:
  - name: f
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {{group: all}}
        plot:
          palette: ["#ff0000"]
          rc: {{lines.linewidth: 3}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    override_path = tmp_path / "plot.yaml"
    override_path.write_text(
        """schema_version: 1
figures:
  f:
    title: {zh: 中文标题, en: English title}
    lang: en
    dpi: 45
    annotate: true
    ncols: 1
    style:
      palette: ["#00aa00"]
      rc: {lines.linewidth: 7}
    panels:
      - title: {zh: 中文, en: English panel}
        xlabel: tau
        xlim: [0.0, 0.02]
""",
        encoding="utf-8",
    )
    captured = {}
    original = replot_module.chart.save

    def save(fig, target, dpi):
        captured["fig"] = fig
        captured["dpi"] = dpi
        return original(fig, target, dpi)

    monkeypatch.setattr(replot_module.chart, "save", save)
    replot_from(
        out,
        tmp_path / "replot",
        overrides=read_overrides(override_path),
    )
    assert captured["dpi"] == 45
    fig = captured["fig"]
    assert fig._suptitle.get_text() == "English title"
    ax = fig.axes[0]
    assert ax.get_title() == "English panel"
    assert ax.get_xlabel() == "tau"
    assert ax.get_xlim()[1] == pytest.approx(0.02)
    assert ax.lines[0].get_linewidth() == pytest.approx(7.0)
    assert ax.lines[0].get_color() == "#00aa00"
    assert ax.texts


def test_rdc_replot_keeps_optional_fit_summary(tmp_path, monkeypatch):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: rdc
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 8]
    groups: {{all: all}}
figures:
  - name: rdc
    panels:
      - source: A
        pack: msd
        product: msd-rdc
        select: {{group: all}}
        compute: {{msd_type: xyz, grouping: residues}}
        derive: {{fit: {{window_ns: [0.0, 0.01]}}, rdc: {{}}}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    seen = {}

    def save(fig, target, dpi):
        seen["fig"] = fig
        return original(fig, target, dpi)

    original = replot_module.chart.save
    monkeypatch.setattr(replot_module.chart, "save", save)
    replot_from(out, tmp_path / "replot")
    ax = seen["fig"].axes[0]
    labels = {line.get_label() for line in ax.lines}
    assert "D" in labels
    assert len(ax.lines) >= 2
    assert len(ax.patches) >= 1


def test_replot_window_override_keeps_other_axes(tmp_path, monkeypatch):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: window
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: all}}
figures:
  - name: f
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {{group: all}}
        plot: {{window: {{y: [0, 20]}}}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    override = tmp_path / "plot.yaml"
    override.write_text(
        """schema_version: 1
figures:
  f:
    panels:
      - window: {x: [0.0, 0.01]}
""",
        encoding="utf-8",
    )
    seen = {}
    original = replot_module.chart.save

    def save(fig, target, dpi):
        seen["fig"] = fig
        return original(fig, target, dpi)

    monkeypatch.setattr(replot_module.chart, "save", save)
    replot_from(out, tmp_path / "replot", overrides=read_overrides(override))
    ax = seen["fig"].axes[0]
    assert ax.get_xlim()[1] == pytest.approx(0.01)
    assert ax.get_ylim() == pytest.approx((0.0, 20.0))


def test_replot_panel_style_overrides_snapshot_style(tmp_path, monkeypatch):
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: panel-style
render:
  dpi: 60
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 8]
    groups: {{all: all}}
figures:
  - name: f
    panels:
      - source: A
        pack: msd
        product: msd-raw
        select: {{group: all}}
""",
        encoding="utf-8",
    )
    out = render_project(read_project(path), tmp_path / "out")
    override = tmp_path / "plot.yaml"
    override.write_text(
        """schema_version: 1
figures:
  f:
    panels:
      - palette: ["#00aa00"]
        rc: {lines.linewidth: 7}
""",
        encoding="utf-8",
    )
    seen = {}
    original = replot_module.chart.save

    def save(fig, target, dpi):
        seen["fig"] = fig
        return original(fig, target, dpi)

    monkeypatch.setattr(replot_module.chart, "save", save)
    replot_from(out, tmp_path / "replot", overrides=read_overrides(override))
    line = seen["fig"].axes[0].lines[0]
    assert line.get_color() == "#00aa00"
    assert line.get_linewidth() == pytest.approx(7.0)
