from __future__ import annotations

from pathlib import Path

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
import mdanal.figure.engine as engine

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: hbond-lifetime
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 8]
    naming: {{from_data: {TINY / 'data.lmp'}}}
    groups:
      donor: "type 1 3"
      hydrogen: "type 5 6"
      acceptor: "type 1 3"
figures:
{body}
""",
        encoding="utf-8",
    )
    return path


def _panel(product: str, section: str = "") -> str:
    suffix = f", section: {section}" if section else ""
    return f"""  - name: {product}
    panels:
      - source: A
        pack: hbond
        product: {product}
        select: {{donor: donor, hydrogen: hydrogen, acceptor: acceptor}}
        compute: {{d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}{suffix}
"""


def test_lifetime_products_each_emit_one_curve(tmp_path, monkeypatch):
    seen = []
    original = engine.chart.save

    def save(fig, target, dpi):
        seen.append(fig)
        return original(fig, target, dpi)

    monkeypatch.setattr(engine.chart, "save", save)
    body = _panel("hbond-lifetime-continuous") + _panel("hbond-lifetime-intermittent")
    render_project(read_project(_config(tmp_path, body)), tmp_path / "out")
    assert len(seen) == 2
    for fig in seen:
        ax = fig.axes[0]
        data = [line for line in ax.lines if len(line.get_xdata()) > 2]
        assert len(data) == 1
        assert len(data[0].get_xdata()) > 2


def test_lifetime_compare_labels_sources(tmp_path, monkeypatch):
    body = """  - name: cmp
    panels:
      - compare:
          pack: hbond
          product: hbond-lifetime-continuous
          sources:
            - {source: A, label: first, section: [0, 4], select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}
            - {source: A, label: second, section: [0, 8], select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}
"""
    seen = []
    original = engine.chart.save

    def save(fig, target, dpi):
        seen.append(fig)
        return original(fig, target, dpi)

    monkeypatch.setattr(engine.chart, "save", save)
    render_project(read_project(_config(tmp_path, body)), tmp_path / "out")
    labels = [text.get_text() for text in seen[0].axes[0].get_legend().get_texts()]
    assert "first" in labels
    assert "second" in labels


def _capture_render(tmp_path, monkeypatch, body):
    seen = []
    original = engine.chart.save

    def save(fig, target, dpi):
        seen.append(fig)
        return original(fig, target, dpi)

    monkeypatch.setattr(engine.chart, "save", save)
    render_project(read_project(_config(tmp_path, body)), tmp_path / "out")
    return seen[0].axes[0]


def test_lifetime_compare_x_uses_all_sources(tmp_path, monkeypatch):
    body = """  - name: cmp
    panels:
      - compare:
          pack: hbond
          product: hbond-lifetime-continuous
          sources:
            - {source: A, label: short, select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 10, intermittency: 1, window_step: 1}}
            - {source: A, label: long, select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}
"""
    ax = _capture_render(tmp_path, monkeypatch, body)
    assert ax.get_xlim()[1] >= 20.0


def test_lifetime_compare_internittent_colors_and_no_tau(tmp_path, monkeypatch):
    body = """  - name: cmp
    panels:
      - compare:
          pack: hbond
          product: hbond-lifetime-intermittent
          sources:
            - {source: A, label: first, select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 10, intermittency: 1, window_step: 1}}
            - {source: A, label: second, select: {donor: donor, hydrogen: hydrogen, acceptor: acceptor}, compute: {d_a_cutoff: 3.5, d_h_a_angle_cutoff: 150, tau_max_ps: 20, intermittency: 1, window_step: 1}}
"""
    ax = _capture_render(tmp_path, monkeypatch, body)
    data = [line for line in ax.lines if len(line.get_xdata()) > 2]
    assert len(data) == 2
    assert data[0].get_color() != data[1].get_color()
    assert not any(" ps" in text.get_text() for text in ax.texts)
    assert any(text.get_text() == "1/e" for text in ax.texts)
