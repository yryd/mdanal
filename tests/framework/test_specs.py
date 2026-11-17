"""绘图规格：Curve/Field/Series/PanelRequest 的最小契约。"""

from __future__ import annotations

import numpy as np
import pytest

from mdanal.plot.specs import Curve, Field, PanelRequest, Series


def test_curve_validates_shapes_and_is_numpy():
    curve = Curve(x=[0, 1, 2], y=[1, 2, 3], label="Water")
    assert curve.x.dtype == float
    assert curve.y.dtype == float
    with pytest.raises(ValueError, match="形状"):
        Curve(x=[0, 1], y=[1])


def test_series_requires_one_layer_kind():
    curve = Curve(x=[0, 1], y=[1, 2])
    series = Series(name="mass", curves=[curve])
    assert series.curves == (curve,)
    field = Field(x=[0, 1], y=[0, 1], values=[[1, 2], [3, 4]])
    with pytest.raises(ValueError, match="只能含一种"):
        Series(name="mixed", curves=[curve], fields=[field])


def test_panel_request_requires_series():
    series = Series(name="mass", curves=[Curve(x=[0, 1], y=[1, 2])])
    request = PanelRequest(recipe="lineardensity", series=[series])
    assert request.recipe == "lineardensity"
    assert request.series == (series,)
    with pytest.raises(ValueError, match="至少"):
        PanelRequest(recipe="lineardensity", series=[])


def test_all_builtin_plugins_have_panel_renderer():
    """所有内置插件都必须走 render_panel，包括不支持 compare 的 density/hbond_type。"""
    import importlib

    from mdanal.config.registry import discover

    for name, definition in discover().definitions.items():
        module = importlib.import_module(definition.module)
        assert callable(getattr(module, "render_panel", None)), name
        assert callable(getattr(module, "panels", None)), name


def test_figure_owns_ncols_and_hides_empty_cells():
    from mdanal.plot.figure import Figure
    from mdanal.plot.panels import Panel

    panels = [
        Panel(name=str(index), draw=lambda ax: ax.plot([0, 1], [index, index]))
        for index in range(3)
    ]
    fig = Figure(panels, ncols=2).build()
    assert sum(axis.get_visible() for axis in fig.axes) == 3
