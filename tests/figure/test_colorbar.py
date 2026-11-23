from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from mdanal.figure.config import read_project
from mdanal.figure.engine import render_project
import mdanal.figure.engine as engine

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _config(tmp_path: Path, width: str, frame: bool) -> Path:
    path = tmp_path / f"fig-{width.replace('%', '')}-{frame}.yaml"
    path.write_text(
        f"""schema_version: 1
name: cbar
render: {{lang: en, dpi: 50}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 5]
    groups: {{all: all}}
figures:
  - name: density
    panels:
      - source: A
        pack: density
        product: density-2d
        select: {{group: all}}
        compute: {{delta: 2.0}}
        plot:
          plane: xy
          cbar_width: "{width}"
          cbar_frame: {str(frame).lower()}
""",
        encoding="utf-8",
    )
    return path


def test_density_colorbar_style_and_width(tmp_path, monkeypatch):
    captured = {}
    original = engine.chart.save

    def save(fig, path, dpi):
        captured["fig"] = fig
        return original(fig, path, dpi)

    monkeypatch.setattr(engine.chart, "save", save)
    render_project(read_project(_config(tmp_path, "9%", False)), tmp_path / "narrow-signal")

    fig = captured["fig"]
    cax = fig.axes[1]
    assert cax.get_ylabel() == "number density (Å$^{-3}$)"
    assert cax.spines["outline"].get_visible() is False
    assert all(tick.get_markersize() == pytest.approx(0.0) for tick in cax.get_yaxis().get_ticklines())
    assert cax.get_yticklabels()
    assert all(label.get_fontweight() == "bold" for label in cax.get_yticklabels())

    # 宽度必须真正参与布局；比较同一配置下 3.5% 与 9% 的输出像素宽度。
    narrow = tmp_path / "narrow.png"
    wide = tmp_path / "wide.png"
    render_project(read_project(_config(tmp_path, "3.5%", False)), tmp_path / "narrow", force=True)
    render_project(read_project(_config(tmp_path, "9%", False)), tmp_path / "wide", force=True)
    narrow = tmp_path / "narrow" / "figures" / "density.png"
    wide = tmp_path / "wide" / "figures" / "density.png"
    assert Image.open(wide).size[0] > Image.open(narrow).size[0]


def test_density_colorbar_frame_can_be_restored(tmp_path, monkeypatch):
    captured = {}
    original = engine.chart.save

    def save(fig, path, dpi):
        captured["fig"] = fig
        return original(fig, path, dpi)

    monkeypatch.setattr(engine.chart, "save", save)
    render_project(read_project(_config(tmp_path, "5%", True)), tmp_path / "out")
    assert captured["fig"].axes[1].spines["outline"].get_visible() is True
