"""绘图层：公共 API、标注解析、窗口裁剪、标签与字体。"""

from __future__ import annotations

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
    assert items[2]["at"] == (17.0, 29.0)


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

    annotations.draw(ax, Ctx(), axes={"x": "z"})
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
