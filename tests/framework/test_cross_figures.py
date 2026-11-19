"""顶层 figures：跨分析 Panel 组合、快照和 replot。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import SYSTEM, write_system
from mdanal.config.registry import build_plan, load_registry
from mdanal.config.system import read_system
from mdanal.errors import ValidationError
from mdanal.plot.replot import run_replot


def _config(tmp_path: Path, *, derive: bool = True) -> Path:
    derive_block = (
        "    derive: {fit: {window_ns: [0.0, 0.02]}}\n" if derive else ""
    )
    analyses = "".join(
        f"  - name: msd\n"
        f"    tag: {tag}\n"
        f"    sel: [all_atoms]\n"
        f"    section: [0, 8]\n"
        f"{derive_block}"
        for tag in ("a", "b", "c")
    )
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        analyses,
        frames="[0, 8]",
    )
    path.write_text(
        path.read_text(encoding="utf-8")
        + """
figures:
  - name: msd-three
    layout: {ncols: 3}
    plot: {title: 三组分测试}
    panels:
      - {analysis: msd-a, recipe: fit, plot: {title: A}}
      - {analysis: msd-b, recipe: fit, plot: {title: B}}
      - {analysis: msd-c, recipe: fit, plot: {title: C}}
""",
        encoding="utf-8",
    )
    return path


def test_cross_figure_run_and_replot(tmp_path):
    from mdanal import cli

    path = _config(tmp_path)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    figure = out / "figures" / "msd-three.png"
    snapshot = out / "figures" / "msd-three.json"
    assert figure.is_file() and snapshot.is_file()
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["kind"] == "composite_figure"
    assert [panel["analysis"] for panel in payload["panels"]] == [
        "msd-a",
        "msd-b",
        "msd-c",
    ]
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["composite_figures"][0]["name"] == "msd-three"
    assert provenance["composite_figure_errors"] == []

    target = tmp_path / "replot"
    run_replot(out, target, composite=["msd-three"], lang="zh")
    assert (target / "figures" / "msd-three.png").is_file()
    replot = json.loads((target / "replot.json").read_text(encoding="utf-8"))
    assert replot["composite_figures"][0]["name"] == "msd-three"


def test_cross_figure_missing_derive_fails_after_tables(tmp_path):
    from mdanal import cli

    path = _config(tmp_path, derive=False)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) != 0
    assert (out / "msd-a" / "tables" / "msd.csv").is_file()
    assert not (out / "figures" / "msd-three.png").exists()


def test_cross_figure_rejects_unknown_analysis_and_recipe(tmp_path):
    path = _config(tmp_path)
    data = path.read_text(encoding="utf-8")
    path.write_text(
        data.replace("analysis: msd-a", "analysis: missing"),
        encoding="utf-8",
    )
    cfg = read_system(path)
    with pytest.raises(ValidationError, match="不在本次计划"):
        build_plan(cfg, load_registry())

    path = _config(tmp_path / "recipe")
    path.write_text(
        path.read_text(encoding="utf-8").replace("recipe: fit", "recipe: nope"),
        encoding="utf-8",
    )
    cfg = read_system(path)
    with pytest.raises(ValidationError, match="没有 figure recipe"):
        build_plan(cfg, load_registry())


def test_composite_replot_applies_title_and_palette(tmp_path, monkeypatch):
    from mdanal import cli
    from mdanal.plot import chart

    path = _config(tmp_path, derive=True)
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    config = tmp_path / "plot.yaml"
    config.write_text(
        "schema_version: 1\n"
        "defaults:\n"
        "  plot:\n"
        "    title: NEW\n"
        "    palette: ['#112233']\n",
        encoding="utf-8",
    )
    captured = {}

    real_save = chart.save

    def save(fig, path, dpi):
        captured["title"] = fig._suptitle.get_text() if fig._suptitle else None
        captured["colors"] = [
            line.get_color() for ax in fig.axes for line in ax.lines
        ]
        return real_save(fig, path, dpi)

    monkeypatch.setattr(chart, "save", save)
    run_replot(
        out,
        tmp_path / "replot",
        composite=["msd-three"],
        config=config,
        lang="zh",
    )
    assert captured["title"] == "NEW"
    assert captured["colors"] and captured["colors"][0] == "#112233"
