"""径向分布函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.lib.distances import distance_array

from ._geometry import geometry_meta
from ..plot import annotations, chart, plotutil
from ..plot.panels import Panel
from ..plot.specs import Curve, PanelRequest, Series
from ..errors import ValidationError


SLOTS = ("a", "b")

PARAMS = {
    "range": {
        "type": list,
        "default": [0.5, 6.0],
        "unit": "Å",
        "help": "r 的范围 [最小值, 最大值]",
    },
    "nbins": {
        "type": int,
        "default": 60,
        "min": 2,
        "help": "直方图 bin 数",
    },
}

LABELS = {
    "zh": {
        "title": "径向分布函数",
        "x": "$r$ (Å)",
        "y": "$g(r)$",
    },
    "en": {
        "title": "Radial distribution function",
        "x": "$r$ (Å)",
        "y": "$g(r)$",
    },
}


COLUMN_LABELS = {
    "zh": {"r_angstrom": "$r$ (Å)", "g_r": "$g(r)$"},
    "en": {"r_angstrom": "$r$ (Å)", "g_r": "$g(r)$"},
}

COMPARE = {
    "table": "rdf",
    "x": "r_angstrom",
    "y": ["g_r"],
    "box_axis": False,
}


COORDINATES = "in_box"

GEOMETRY = {"cell": "orthorhombic", "periodicity": "full"}


def run(ctx) -> dict[str, pd.DataFrame]:
    group_a = ctx.groups["a"].atoms
    group_b = ctx.groups["b"].atoms
    rmin, rmax = (float(v) for v in ctx.params["range"])
    nbins = int(ctx.params["nbins"])
    if rmax <= rmin or nbins < 2:
        raise ValidationError("rdf 需要 rmax > rmin 且 nbins >= 2")

    dimensions = ctx.universe.dimensions
    if dimensions is None:
        raise ValidationError("轨迹缺少盒尺寸，无法计算 RDF")
    if not np.allclose(np.asarray(dimensions[3:]), 90.0, atol=1e-3):
        ctx.warn(
            f"检测到三斜盒角 {np.asarray(dimensions[3:]).tolist()}；"
            "RDF 的球壳范围/归一化尚未验证，结果仅供定性参考。"
        )
    window = getattr(ctx, "geometry_window", None)
    if window is not None:
        limit = 0.5 * float(window.min_length)
        source = f"分析窗口最短盒长 {window.min_length:g} Å 的一半"
    else:
        limit = 0.5 * float(min(dimensions[:3]))
        source = "当前帧最短盒长的一半"
    if limit and rmax > limit:
        ctx.warn(
            f"range 上限 {rmax:g} Å 超过{source}（{limit:g} Å）；"
            "距离超过该范围时球壳归一化不适用，结果仅供定性参考。"
        )

    geometry = getattr(ctx, "geometry", None)
    pbc = tuple(bool(value) for value in getattr(geometry, "pbc", (True, True, True)))
    box = np.asarray(dimensions, dtype=float).copy()
    if not all(pbc):
        # 非周期方向不能用真实盒长做最小镜像；放大到远大于 rmax 的长度。
        for axis, periodic in enumerate(pbc):
            if not periodic:
                box[axis] = max(float(box[axis]), 4.0 * rmax, 1.0)

    indices_a = set(int(value) for value in group_a.indices)
    indices_b = set(int(value) for value in group_b.indices)
    n_self = len(indices_a & indices_b)
    n_valid = group_a.n_atoms * group_b.n_atoms - n_self
    if n_valid <= 0:
        raise ValidationError("RDF 两组没有可用的交叉配对")

    edges = np.linspace(rmin, rmax, nbins + 1)
    counts = np.zeros(nbins, dtype=float)
    n_frames = 0
    chunk = max(1, int(2_000_000 / max(group_b.n_atoms, 1)))
    for frame in range(ctx.start, ctx.stop):
        ctx.universe.trajectory[frame]
        positions_a = np.asarray(group_a.positions, dtype=float)
        positions_b = np.asarray(group_b.positions, dtype=float)
        for start in range(0, len(positions_a), chunk):
            distances = distance_array(
                positions_a[start : start + chunk],
                positions_b,
                box=box,
            )
            counts += np.histogram(distances, bins=edges)[0]
        n_frames += 1

    if n_frames == 0:
        raise ValidationError("RDF 帧窗口为空")
    # 同组/部分重叠时，distance_array 会把 i=i 的零距离也算进第一个 bin。
    if rmin <= 0.0 and n_self:
        counts[0] -= n_self * n_frames

    volume = float(np.prod(np.asarray(dimensions[:3], dtype=float)))
    shell = 4.0 / 3.0 * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    ideal = n_valid * n_frames * shell / volume
    g_r = np.divide(counts, ideal, out=np.full_like(counts, np.nan), where=ideal > 0)
    centers = 0.5 * (edges[1:] + edges[:-1])
    return {"rdf": pd.DataFrame({"r_angstrom": centers, "g_r": g_r})}


def meta(ctx, tables) -> dict:
    return geometry_meta(ctx)


def build_series(ctx, tables) -> list[Series]:
    table = tables["rdf"]
    curve = Curve(
        x=table["r_angstrom"].to_numpy(dtype=float),
        y=table["g_r"].to_numpy(dtype=float),
        label=ctx.label("y"),
    )
    return [Series(name="g_r", curves=[curve], label=ctx.label("y"))]


def panel_request(ctx, tables) -> PanelRequest:
    return PanelRequest(
        recipe="rdf",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = len(curves) > 1
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
                    label=curve.label if show_legend else None,
                )
        chart.refline(ax, 1.0, ls="--", lw=0.6, color="0.6")
        if show_legend:
            chart.legend(ax)
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="rdf",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label("x"),
        ylabel=request.ylabel or ctx.label("y"),
        aspect="auto",
        xlim=ctx.window("x"),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )


def panels(ctx, tables) -> list[Panel]:
    request = panel_request(ctx, tables)
    return [render_panel(ctx, request)]


def figure_name(ctx, tables) -> str:
    return "rdf"
