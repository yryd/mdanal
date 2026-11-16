"""绘图层：公共 API、标注解析、窗口裁剪、标签与字体。"""

from __future__ import annotations

import numpy as np
import pytest

from mdanal.errors import MdanalError, ValidationError
from mdanal.plot import annotations, chart, plotutil


def test_chart_draws_from_arrays(tmp_path):
    fig, ax = chart.figure("single")
    chart.line(ax, [0, 1, 2], [0, 1, 4], label="demo")
    chart.refline(ax, 1.0)
    chart.bars(ax, ["a", "b"], [1.0, 2.0], notes=["1", "2"])
    chart.note(ax, "api")
    path = chart.save(fig, tmp_path / "figure.png", dpi=72)
    assert path.is_file() and path.stat().st_size > 1000


def test_chart_rejects_unknown_span_axis():
    fig, ax = chart.figure("single")
    with pytest.raises(MdanalError, match="axis"):
        chart.span(ax, 0.0, 1.0, axis="z")


def test_annotations_parse():
    items = annotations.parse(
        [
            {"kind": "vline", "axis": "z", "at": 22.0, "text": "界面"},
            {"kind": "hline", "at": 1.0},
            {"kind": "span", "axis": "z", "at": [29, 17]},
            {"kind": "text", "at": [5, 0.8], "text": "bulk"},
        ],
        "probe",
    )
    assert len(items) == 4
    assert items[2]["at"] == (17.0, 29.0)   # span 排序为 (低, 高)
    assert items[3]["at"] == (5.0, 0.8)     # text 保持原顺序


def test_annotations_require_axis():
    with pytest.raises(ValidationError, match="axis"):
        annotations.parse([{"kind": "vline", "at": 1.0}], "probe")


def test_annotations_reject_unknown_field():
    with pytest.raises(ValidationError, match="未知字段"):
        annotations.parse([{"kind": "hline", "at": 1.0, "colour": "red"}], "probe")


def test_annotations_axis_mismatch_is_skipped():
    """横轴对不上的标注应被跳过，而不是画错位置。"""
    fig, ax = chart.figure("single")
    chart.line(ax, [0, 1], [0, 1])

    class Ctx:
        annotations = ({"kind": "vline", "axis": "x", "at": 0.5, "text": None},)
        lang = "zh"
        warnings = []

        def warn(self, message):
            self.warnings.append(message)

    annotations.draw(ax, Ctx(), x_axis="z")
    assert len(ax.lines) == 1  # 只有数据线，没有竖线


def test_window_limit_ignores_bounds_outside_data():
    fig, ax = chart.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])

    plotutil.limit(ax, "x", (-5.0, 1.5))
    plotutil.limit(ax, "y", (0.5, 1.5))

    assert ax.get_xlim() == pytest.approx((0.0, 1.5))
    assert ax.get_ylim() == pytest.approx((0.5, 1.5))

    fig, ax = chart.figure((3.0, 2.0))
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    plotutil.limit(ax, "x", (10.0, 20.0))
    assert ax.get_xlim() == pytest.approx((0.0, 2.0))


def test_missing_label_is_rejected():
    labels = plotutil.Labels({"zh": {"title": "t"}}, {})
    with pytest.raises(MdanalError, match="缺少标签"):
        labels("axis_x")


def test_font_is_available():
    assert chart.missing_fonts() == []


def test_bars_handles_zero_negative_and_nan():
    fig, ax = chart.figure((3.0, 2.0))
    chart.bars(ax, ["a", "b"], [0.0, 0.0])
    low, high = ax.get_xlim()
    assert low <= 0.0 < high

    fig, ax = chart.figure((3.0, 2.0))
    chart.bars(ax, ["a", "b"], [-2.0, -1.0])
    low, high = ax.get_xlim()
    assert low < -2.0 and high >= 0.0

    fig, ax = chart.figure((3.0, 2.0))
    chart.bars(ax, ["a", "b"], [float("nan")] * 2)
    low, high = ax.get_xlim()
    assert np.isfinite(low) and np.isfinite(high) and high > low

    fig, ax = chart.figure((3.0, 2.0))
    chart.bars(ax, ["a", "b"], [-2.0, 3.0])
    low, high = ax.get_xlim()
    assert low < -2.0 and high > 3.0


def test_bars_rejects_length_mismatch():
    fig, ax = chart.figure((3.0, 2.0))
    with pytest.raises(MdanalError, match="长度不一致"):
        chart.bars(ax, ["a"], [1.0, 2.0])


def test_annotations_text_keeps_position():
    items = annotations.parse(
        [
            {"kind": "text", "at": [5, 0.8], "text": "bulk"},
            {"kind": "text", "at": [1, 1], "text": "corner"},
        ],
        "probe",
    )
    assert items[0]["at"] == (5.0, 0.8)
    assert items[1]["at"] == (1.0, 1.0)

    with pytest.raises(ValidationError, match="不能相等"):
        annotations.parse([{"kind": "span", "axis": "z", "at": [1, 1]}], "probe")


def test_annotations_support_plot_axes_and_bilingual_text():
    items = annotations.parse(
        [
            {"kind": "vline", "axis": "horizontal", "at": 10, "text": {"zh": "参考", "en": "ref"}},
            {"kind": "vline", "axis": "x", "at": 15},
            {"kind": "span", "axis": "vertical", "at": [0, 2]},
            {"kind": "hline", "axis": "vertical", "at": 1},
        ],
        "probe",
    )
    assert items[0]["axis"] == "horizontal"
    assert items[0]["text"] == {"zh": "参考", "en": "ref"}
    assert items[1]["axis"] == "x"
    assert items[2]["axis"] == "vertical"

    fig, ax = chart.figure("single")
    chart.line(ax, [0, 20], [0, 1])

    class Ctx:
        annotations = items
        lang = "en"
        warnings = []

        def warn(self, message):
            self.warnings.append(message)

    annotations.draw(ax, Ctx(), x_axis="z")
    assert any(line.get_linestyle() == ":" for line in ax.lines)
    assert len(ax.patches) >= 1  # vertical span
    assert any(text.get_text() == "ref" for text in ax.texts)


def test_annotations_reject_vline_vertical_and_text_axis():
    with pytest.raises(ValidationError, match="vline"):
        annotations.parse(
            [{"kind": "vline", "axis": "vertical", "at": 1}], "probe"
        )
    with pytest.raises(ValidationError, match="text 不接受"):
        annotations.parse(
            [{"kind": "text", "axis": "horizontal", "at": [1, 2]}], "probe"
        )


def test_annotations_mismatch_warns_once():
    fig, ax = chart.figure("single")
    chart.line(ax, [0, 1], [0, 1])

    class Ctx:
        annotations = (
            {"kind": "vline", "axis": "x", "at": 0.5, "text": None},
            {"kind": "vline", "axis": "x", "at": 0.6, "text": None},
        )
        lang = "zh"
        warnings = []

        def warn(self, message):
            self.warnings.append(message)

    ctx = Ctx()
    annotations.draw(ax, ctx, x_axis="z")
    assert len(ax.lines) == 1
    assert len(ctx.warnings) == 1


def test_palette_parser_accepts_names_and_custom_lists():
    from mdanal.plot.settings import parse_plot, resolve_palette

    bright = resolve_palette("bright", "test")
    assert bright[0] == "#4477AA"
    assert parse_plot({"palette": "bright"}, "test")["palette"][0] == "#4477AA"
    custom = parse_plot({"palette": ["#112233", "steelblue"]}, "test")["palette"]
    assert custom == ["#112233", "steelblue"]
    with pytest.raises(ValidationError, match="色板名"):
        parse_plot({"palette": "no-such-palette"}, "test")


def test_render_applies_palette_to_cycle(tmp_path, monkeypatch):
    from mdanal.plot import render as render_module

    captured = {}

    class Module:
        @staticmethod
        def figures(ctx, tables):
            fig, ax = chart.figure("single")
            chart.line(ax, [0, 1], [0, 1])
            chart.line(ax, [0, 1], [1, 0])
            return [("t", fig)]

    class Ctx:
        lang = "zh"
        dpi = 72

    def fake_save(fig, path, dpi):
        captured["colors"] = [line.get_color() for line in fig.axes[0].lines]
        return path

    monkeypatch.setattr(render_module.chart, "save", fake_save)
    render_module.render(
        Module,
        Ctx(),
        {},
        tmp_path,
        settings={"palette": ["#112233", "#445566"]},
    )
    assert captured["colors"] == ["#112233", "#445566"]
