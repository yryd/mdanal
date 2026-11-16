"""快照表解码、PlotContext 与呈现覆盖的基础测试。"""

from __future__ import annotations

import matplotlib
import numpy as np
import pandas as pd
import pytest

from mdanal.plot import chart
from mdanal.plot.context import PlotContext
from mdanal.plot.plotutil import Labels
from mdanal.plot.render import render
from mdanal.run.writers import column_kinds, read_table, write_tables


def test_table_roundtrip_preserves_types_and_na_string(tmp_path):
    frame = pd.DataFrame(
        {
            "f": [1.5, np.nan],
            "i": [1, 2],
            "b": [True, False],
            "s": ["NA", "x"],
        }
    )
    paths = write_tables(tmp_path, {"t": frame})
    read = read_table(paths["t"], column_kinds(frame))
    assert read["f"].iloc[0] == 1.5
    assert np.isnan(read["f"].iloc[1])
    assert read["i"].tolist() == [1, 2]
    assert read["b"].tolist() == [True, False]
    assert read["s"].tolist() == ["NA", "x"]


def test_plot_context_size_override_and_window():
    ctx = PlotContext(
        params={"p": 1},
        meta={},
        extras={},
        start=0,
        stop=5,
        frame_dt_ps=5.0,
        selection_frame=0,
        shift=(0.0, 0.0, 0.0),
        lang="zh",
        dpi=100,
        annotate=False,
        annotations=(),
        labels=Labels({"title": "t", "window": "{start}-{stop}"}),
        figure_sizes={"single": (3.5, 2.6)},
        windows={"x": (0.0, 1.0)},
        size_override=(4.0, 2.0),
    )
    assert ctx.size("single") == (4.0, 2.0)
    assert ctx.size_is_explicit is True
    assert ctx.window("x") == (0.0, 1.0)


def test_render_applies_rc_and_overrides(tmp_path):
    before = matplotlib.rcParams["font.size"]

    class Module:
        @staticmethod
        def figures(ctx, tables):
            fig, ax = chart.figure("single")
            ax.plot([0, 1], [0, 1])
            return [("t", fig)]

    class Ctx:
        lang = "zh"
        dpi = 72

    paths = render(
        Module,
        Ctx(),
        {},
        tmp_path,
        fmt="png",
        settings={
            "title": "标题",
            "xlim": (0.0, 0.5),
            "rc": {"font.size": 99},
        },
    )
    assert paths[0].is_file()
    assert matplotlib.rcParams["font.size"] == before
    image = matplotlib.image.imread(paths[0])
    assert image.ndim == 3
