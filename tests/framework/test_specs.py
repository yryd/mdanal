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
    with pytest.raises(ValueError, match="不能同时"):
        Series(name="mixed", curves=[curve], fields=[field])


def test_panel_request_requires_series():
    series = Series(name="mass", curves=[Curve(x=[0, 1], y=[1, 2])])
    request = PanelRequest(recipe="lineardensity", series=[series])
    assert request.recipe == "lineardensity"
    assert request.series == (series,)
    with pytest.raises(ValueError, match="至少"):
        PanelRequest(recipe="lineardensity", series=[])
