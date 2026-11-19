"""绘图快照与 replot：不读轨迹、哈希校验、覆盖保护与配置覆盖。"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path

import fake_analysis
import pytest

from mdanal import cli
from mdanal.errors import MdanalError, ValidationError
from mdanal.plot import replot as replot_module
from mdanal.plot.replot import run_replot
from mdanal.run.runner import execute

from helpers import (
    SYSTEM,
    load_fake,
    run_fake,
    write_system,
)
from mdanal.run.runner import RunOptions

FAKE = "  - {name: fake, sel: [all_atoms, all_atoms]}\n"


def _run(tmp_path, *, lang="zh", force=False):
    path = write_system(
        tmp_path, SYSTEM / "data.lmp", SYSTEM / "run.lammpstrj", FAKE, frames="[0, 5]"
    )
    out = tmp_path / "out"
    run_fake(path, out, lang=lang, force=force)
    return out


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_run_writes_complete_snapshot(tmp_path):
    out = _run(tmp_path)
    snapshot = json.loads((out / "fake/plot.json").read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == 1
    assert snapshot["analysis"]["plot_api_version"] == 1
    assert snapshot["analysis"]["implementation_sha256"]
    assert set(snapshot["context"]["labels"]) == {"zh", "en"}
    table = snapshot["tables"]["fake"]
    assert table["sha256"] == _digest(out / "fake" / table["path"])
    assert [column["name"] for column in table["columns"]] == [
        "x_angstrom",
        "y",
        "y2",
        "start",
        "stop",
    ]
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    detail = provenance["analyses"][0]
    assert detail["plot"]["sha256"] == _digest(out / detail["plot"]["path"])
    assert detail["status"] == "ok"


def test_replot_does_not_load_trajectory(tmp_path, monkeypatch):
    out = _run(tmp_path)
    import mdanal.config.system as system_module

    def boom(*args, **kwargs):
        raise AssertionError("replot 不应加载轨迹")

    monkeypatch.setattr(system_module, "load_universe", boom)
    target = tmp_path / "replot"
    run_replot(out, target)
    assert (target / "fake/figures/fake.png").is_file()
    assert (target / "replot.json").is_file()


def test_replot_figures_match_run(tmp_path):
    out = _run(tmp_path)
    target = tmp_path / "replot"
    run_replot(out, target)
    assert _digest(out / "fake/figures/fake.png") == _digest(
        target / "fake/figures/fake.png"
    )


def test_replot_rejects_table_hash_mismatch(tmp_path):
    out = _run(tmp_path)
    table = out / "fake/tables/fake.csv"
    table.write_text(table.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="哈希"):
        run_replot(out, tmp_path / "replot")


def test_replot_output_protection(tmp_path):
    out = _run(tmp_path)
    with pytest.raises(ValidationError, match="重叠"):
        run_replot(out, out)
    with pytest.raises(ValidationError, match="重叠"):
        run_replot(out, out / "nested")

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "note.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValidationError, match="不是本程序"):
        run_replot(out, plain)

    target = tmp_path / "target"
    run_replot(out, target)
    with pytest.raises(ValidationError, match="非空"):
        run_replot(out, target)
    run_replot(out, target, force=True)
    assert (target / "fake/figures/fake.png").is_file()


def test_replot_config_merges_and_annotates(tmp_path, monkeypatch):
    out = _run(tmp_path)
    config = tmp_path / "plot.yaml"
    config.write_text(
        """schema_version: 1
defaults:
  lang: en
  format: svg
  plot:
    size: [3.0, 2.0]
analyses:
  fake:
    plot:
      title: {zh: 假, en: Fake title}
    annotate:
      - {kind: vline, axis: horizontal, at: 2, text: Title}
""",
        encoding="utf-8",
    )
    captured = {}

    def fake_render(module, ctx, tables, target, *, fmt, settings, **kwargs):
        captured["ctx"] = ctx
        captured["fmt"] = fmt
        captured["settings"] = settings
        path = target / "figures" / "fake.svg"
        path.parent.mkdir(parents=True)
        path.write_text("<svg/>", encoding="utf-8")
        return [path]

    monkeypatch.setattr(replot_module, "render", fake_render)
    run_replot(out, tmp_path / "custom", config=config)
    ctx = captured["ctx"]
    assert ctx.lang == "en"
    assert ctx.size("single") == (3.0, 2.0)
    assert ctx.windows == {}
    assert ctx.annotations[0]["kind"] == "vline"
    assert captured["fmt"] == "svg"


def test_replot_warns_when_plugin_hash_changed(tmp_path):
    out = _run(tmp_path)
    snapshot_path = out / "fake/plot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["analysis"]["implementation_sha256"] = "0" * 64
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    target = tmp_path / "replot"
    run_replot(out, target)
    record = json.loads((target / "replot.json").read_text(encoding="utf-8"))
    assert any("插件源码" in warning for warning in record["warnings"])


def test_missing_snapshot_is_rejected(tmp_path):
    out = _run(tmp_path)
    (out / "fake/plot.json").unlink()
    with pytest.raises(ValidationError, match="未保存独立重绘信息"):
        run_replot(out, tmp_path / "replot")


def test_render_failure_keeps_tables_and_snapshot(tmp_path, monkeypatch):
    path = write_system(
        tmp_path, SYSTEM / "data.lmp", SYSTEM / "run.lammpstrj", FAKE, frames="[0, 5]"
    )
    prepared = load_fake(path)

    def boom(ctx, tables):
        raise RuntimeError("figure failed")

    monkeypatch.setattr(fake_analysis, "figures", boom)
    out = tmp_path / "out"
    with pytest.raises(MdanalError, match="绘图失败"):
        execute(prepared, out, RunOptions(), {})

    assert (out / "fake/tables/fake.csv").is_file()
    assert (out / "fake/plot.json").is_file()
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"]["status"] == "failed"
    assert provenance["analyses"][0]["status"] == "render_failed"


def test_replot_failure_keeps_previous_output(tmp_path, monkeypatch):
    out = _run(tmp_path)
    target = tmp_path / "target"
    run_replot(out, target)
    before = _digest(target / "fake/figures/fake.png")

    def boom(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(replot_module, "render", boom)
    with pytest.raises(RuntimeError, match="render failed"):
        run_replot(out, target, force=True)
    assert _digest(target / "fake/figures/fake.png") == before
    assert (target / "replot.json").is_file()


def test_replot_force_replaces_selected_output(tmp_path):
    out = _run(tmp_path)
    target = tmp_path / "target"
    run_replot(out, target)
    assert (target / "fake/figures/fake.png").is_file()
    config = tmp_path / "plot.yaml"
    config.write_text(
        "schema_version: 1\ndefaults:\n  format: svg\n", encoding="utf-8"
    )
    run_replot(out, target, config=config, force=True)
    assert not (target / "fake/figures/fake.png").exists()
    assert (target / "fake/figures/fake.svg").is_file()


def test_replot_rejects_unknown_analysis_and_config_key(tmp_path):
    out = _run(tmp_path)
    with pytest.raises(ValidationError, match="没有分析目录"):
        run_replot(out, tmp_path / "x", analyses=["missing"])
    config = tmp_path / "plot.yaml"
    config.write_text(
        "schema_version: 1\nanalyses:\n  missing:\n    plot: {}\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="不存在"):
        run_replot(out, tmp_path / "y", config=config)


def test_replot_svg_and_pdf_magic(tmp_path):
    out = _run(tmp_path)
    for fmt, head in (("svg", b"<?xml"), ("pdf", b"%PDF")):
        target = tmp_path / f"re{fmt}"
        run_replot(out, target, fmt=fmt)
        data = (target / f"fake/figures/fake.{fmt}").read_bytes()
        assert data.startswith(head)


def test_replot_after_moving_source(tmp_path):
    out = _run(tmp_path)
    moved = tmp_path / "moved"
    shutil.move(str(out), str(moved))
    target = tmp_path / "replot"
    run_replot(moved, target)
    assert (target / "fake/figures/fake.png").is_file()


def test_plot_palette_roundtrips_through_snapshot(tmp_path):
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        "  - name: fake\n"
        "    sel: [all_atoms, all_atoms]\n"
        "    plot: {palette: bright}\n",
        frames="[0, 5]",
    )
    out = tmp_path / "out"
    run_fake(path, out)
    snapshot = json.loads((out / "fake/plot.json").read_text(encoding="utf-8"))
    assert snapshot["context"]["defaults"]["plot"]["palette"][0] == "#4477AA"
    target = tmp_path / "replot"
    run_replot(out, target)
    assert (target / "fake/figures/fake.png").is_file()


def _run_msd(tmp_path, analyses, *, tag="msd"):
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        analyses,
        frames="[0, 5]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    return out


def test_per_figure_plot_reaches_actual_figure(tmp_path, monkeypatch):
    from mdanal.plot import chart
    from mdanal.plot.render import render
    from mdanal.plot.snapshot import load_snapshot, make_plot_context, read_tables

    out = _run_msd(
        tmp_path,
        "  - name: msd\n"
        "    sel: [all_atoms]\n"
        "    figures:\n"
        "      raw:\n"
        "        plot:\n"
        "          title: OLD\n"
        "          palette: [green]\n"
        "          rc: {lines.linewidth: 7}\n"
        "          size: [8, 4]\n"
        "          window: {x: [0, 0.01]}\n",
    )
    snapshot = load_snapshot(out / "msd")
    ctx = make_plot_context(snapshot)
    tables = read_tables(snapshot, out / "msd")
    module = importlib.import_module(snapshot["analysis"]["module"])
    captured = {}

    def save(fig, path, dpi):
        axis = fig.axes[0]
        captured.update(
            title=axis.get_title(),
            xlim=axis.get_xlim(),
            color=axis.lines[0].get_color(),
            linewidth=axis.lines[0].get_linewidth(),
            size=fig.get_size_inches(),
        )
        return path

    monkeypatch.setattr(chart, "save", save)
    render(
        module,
        ctx,
        tables,
        tmp_path / "inspect",
        settings=snapshot["context"]["defaults"].get("plot") or {},
        figures=snapshot["context"]["figures"],
    )
    assert captured["title"] == "OLD"
    assert captured["xlim"] == pytest.approx((0.0, 0.01))
    assert captured["color"] == "green"
    assert captured["linewidth"] == pytest.approx(7.0)
    assert captured["size"][0] == pytest.approx(8.0)


def test_default_raw_is_recorded_and_replottable(tmp_path):
    out = _run_msd(tmp_path, "  - {name: msd, sel: [all_atoms]}\n")
    snapshot = json.loads((out / "msd/plot.json").read_text(encoding="utf-8"))
    assert "raw" in snapshot["context"]["figures"]
    target = tmp_path / "replot"
    run_replot(out, target, figures=["raw"])
    assert (target / "msd/figures/msd.png").is_file()


def test_replot_settings_beat_snapshot_figure_title(tmp_path, monkeypatch):
    from mdanal.plot import chart

    out = _run_msd(
        tmp_path,
        "  - name: msd\n"
        "    sel: [all_atoms]\n"
        "    figures:\n"
        "      raw: {plot: {title: OLD}}\n",
    )
    config = tmp_path / "plot.yaml"
    config.write_text(
        "schema_version: 1\ndefaults:\n  plot:\n    title: NEW\n",
        encoding="utf-8",
    )
    captured = {}

    def save(fig, path, dpi):
        captured["title"] = fig.axes[0].get_title()
        return path

    monkeypatch.setattr(chart, "save", save)
    run_replot(out, tmp_path / "replot", config=config)
    assert captured["title"] == "NEW"


def test_package_plugin_hash_does_not_false_positive(tmp_path):
    from mdanal.plot.snapshot import module_sha256

    out = _run_msd(tmp_path, "  - {name: msd, sel: [all_atoms]}\n")
    target = tmp_path / "replot"
    run_replot(out, target)
    record = json.loads((target / "replot.json").read_text(encoding="utf-8"))
    assert record["analyses"][0]["plugin_changed"] is False
    assert record["warnings"] == []

    # 旧快照只哈希 __init__.py；仍应判定为未变化。
    snapshot_path = out / "msd/plot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    module = importlib.import_module(snapshot["analysis"]["module"])
    snapshot["analysis"]["implementation_sha256"] = hashlib.sha256(
        Path(module.__file__).read_bytes()
    ).hexdigest()
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    legacy_target = tmp_path / "legacy"
    run_replot(out, legacy_target)
    record = json.loads((legacy_target / "replot.json").read_text(encoding="utf-8"))
    assert record["analyses"][0]["plugin_changed"] is False


def test_old_snapshot_without_figures_can_select_default_recipe(tmp_path):
    out = _run_msd(tmp_path, "  - {name: msd, sel: [all_atoms]}\n")
    snapshot_path = out / "msd/plot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["context"]["figures"] = {}
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    target = tmp_path / "replot"
    run_replot(out, target, figures=["raw"])
    assert (target / "msd/figures/msd.png").is_file()


def test_fit_recipe_keeps_user_annotations(tmp_path, monkeypatch):
    from mdanal.plot import chart

    out = _run_msd(
        tmp_path,
        "  - name: msd\n"
        "    sel: [all_atoms]\n"
        "    derive: {fit: {window_ns: [0.0, 0.02]}}\n"
        "    figures: {raw: {}, fit: {}}\n",
    )
    config = tmp_path / "plot.yaml"
    config.write_text(
        "schema_version: 1\n"
        "analyses:\n"
        "  msd:\n"
        "    annotate:\n"
        "      - {kind: text, at: [0.01, 0.1], text: USER}\n",
        encoding="utf-8",
    )
    captured = {}

    def save(fig, path, dpi):
        captured["texts"] = [text.get_text() for text in fig.axes[0].texts]
        return path

    monkeypatch.setattr(chart, "save", save)
    run_replot(out, tmp_path / "replot", figures=["fit"], config=config)
    assert "USER" in captured["texts"]
