"""框架测试用的假分析：只验证契约与流程，不含任何科学内容。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mdanal.plot import annotations, chart

SLOTS = ("group", "ref")

PARAMS = {
    "scale": {
        "type": float,
        "default": 2.0,
        "min": 0.0,
        "unit": "Å",
        "help": "x 列的缩放",
    },
    "label": {
        "type": str,
        "default": "fake",
        "choices": ("fake", "other"),
        "help": "测试用枚举",
    },
}

LABELS = {
    "zh": {"title": "假分析", "x": "x (Å)", "y": "y 值"},
    "en": {"title": "Fake analysis", "x": "x (Å)", "y": "y value"},
}

COORDINATES = "any"
REQUIRES = ()
PACKAGE = None
COLUMN_LABELS = {
    "zh": {"x_angstrom": "x (Å)", "y": "值", "y2": "第二列"},
    "en": {"x_angstrom": "x (Å)", "y": "value", "y2": "second"},
}
COMPARE = {"table": "fake", "x": "x_angstrom", "y": ["y"], "box_axis": True}
MUTATES_POSITIONS = False


def run(ctx) -> dict[str, pd.DataFrame]:
    frames = np.arange(ctx.start, ctx.stop, dtype=float)
    table = pd.DataFrame(
        {
            "x_angstrom": frames * float(ctx.params["scale"]),
            "y": frames,
            "y2": frames * 2.0,
            "start": np.full(len(frames), ctx.start, dtype=int),
            "stop": np.full(len(frames), ctx.stop, dtype=int),
        }
    )
    return {"fake": table}


def meta(ctx, tables) -> dict:
    return {"start": ctx.start, "stop": ctx.stop, "scale": ctx.params["scale"]}


def figures(ctx, tables):
    table = tables["fake"]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, table["x_angstrom"], table["y"], lw=1.0)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [("fake", fig)]
