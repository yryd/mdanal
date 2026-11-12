"""公共绘图接口与标注解析的测试：不依赖轨迹、不需要 system.yaml。"""

import pytest

from mdanal.plot import annotations, chart
from mdanal.errors import MdanalError, ValidationError


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
