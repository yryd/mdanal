"""径向分布函数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.lib.distances import capped_distance

from .._geometry import geometry_meta
from ...plot import annotations, chart
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series
from ...errors import ValidationError


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


COORDINATES = "in_box"

GEOMETRY = {"cell": "orthorhombic", "periodicity": "full"}


def _box_for_frame(dimensions, pbc, positions, rmax):
    """该帧距离计算用的盒；非周期正交轴放大到不会产生最小镜像。

    `capped_distance` 只接受一个盒，无法逐轴关闭 PBC。把非周期轴放大到
    大于该方向全部坐标跨度 + 2 rmax，就能保证真实距离小于盒长的一半，
    最小镜像不会再折回。三斜盒的非周期方向没有简单做法，由调用方拒绝。
    """
    values = np.asarray(dimensions, dtype=float).copy()
    if all(pbc):
        return values
    for axis, periodic in enumerate(pbc):
        if periodic:
            continue
        coordinates = np.asarray(positions, dtype=float)[:, axis]
        if coordinates.size:
            extent = float(coordinates.max() - coordinates.min())
        else:
            extent = 0.0
        values[axis] = max(float(values[axis]), 2.0 * extent + 2.0 * rmax, 1.0)
    return values


def _count_frame(
    positions_a, positions_b, box, rmax, edges, chunk
) -> np.ndarray:
    """一帧的配对距离直方图；用截断邻居搜索避免 a×b 全距离。"""
    counts = np.zeros(len(edges) - 1, dtype=float)
    for start in range(0, len(positions_a), chunk):
        _, distances = capped_distance(
            positions_a[start : start + chunk],
            positions_b,
            max_cutoff=float(rmax),
            box=box,
            return_distances=True,
        )
        counts += np.histogram(distances, bins=edges)[0]
    return counts


def run(ctx) -> dict[str, pd.DataFrame]:
    group_a = ctx.groups["a"].atoms
    group_b = ctx.groups["b"].atoms
    rmin, rmax = (float(v) for v in ctx.params["range"])
    nbins = int(ctx.params["nbins"])
    if rmax <= rmin or nbins < 2:
        raise ValidationError("rdf 需要 rmax > rmin 且 nbins >= 2")

    window = getattr(ctx, "geometry_window", None)
    geometry = getattr(ctx, "geometry", None)
    pbc = tuple(bool(value) for value in getattr(geometry, "pbc", (True, True, True)))
    if window is not None:
        pbc = tuple(bool(value) for value in window.pbc_all)
        if window.pbc_changed:
            ctx.warn(
                "分析窗口内边界类型发生变化；RDF 按各方向“全窗口均周期”处理，"
                "变化方向的非周期结果仅供定性参考。"
            )

    # 先定位到分析起始帧，避免使用上一个分析停留帧的盒。
    ctx.universe.trajectory[ctx.start]
    dimensions = ctx.universe.dimensions
    if dimensions is None:
        raise ValidationError("轨迹缺少盒尺寸，无法计算 RDF")
    triclinic = not np.allclose(np.asarray(dimensions[3:]), 90.0, atol=1e-3)
    if window is not None and not window.orthorhombic:
        triclinic = True
    if triclinic:
        if not all(pbc):
            raise ValidationError(
                "非周期边界与三斜盒同时出现时 RDF 不支持；请使用正交盒或全周期边界",
                where="rdf",
            )
        ctx.warn(
            f"检测到三斜盒角 {np.asarray(dimensions[3:]).tolist()}；"
            "RDF 的球壳范围/归一化尚未验证，结果仅供定性参考。"
        )

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

    indices_a = set(int(value) for value in group_a.indices)
    indices_b = set(int(value) for value in group_b.indices)
    n_self = len(indices_a & indices_b)
    n_valid = group_a.n_atoms * group_b.n_atoms - n_self
    if n_valid <= 0:
        raise ValidationError("RDF 两组没有可用的交叉配对")

    edges = np.linspace(rmin, rmax, nbins + 1)
    shell = 4.0 / 3.0 * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    chunk = max(1, int(2_000_000 / max(group_b.n_atoms, 1)))
    g_sum = np.zeros(nbins, dtype=float)
    n_frames = 0
    for frame in range(ctx.start, ctx.stop):
        ctx.universe.trajectory[frame]
        frame_dimensions = ctx.universe.dimensions
        if frame_dimensions is None:
            raise ValidationError(f"第 {frame} 帧缺少盒尺寸，无法计算 RDF")
        positions_a = np.asarray(group_a.positions, dtype=float)
        positions_b = np.asarray(group_b.positions, dtype=float)
        all_positions = np.concatenate((positions_a, positions_b), axis=0)
        box = _box_for_frame(frame_dimensions, pbc, all_positions, rmax)
        counts = _count_frame(
            positions_a, positions_b, box, rmax, edges, chunk
        )
        # 同组/部分重叠时，距离 0 的自配对会进入第一个 bin。
        if rmin <= 0.0 and n_self:
            counts[0] -= n_self
        volume = float(np.prod(np.asarray(frame_dimensions[:3], dtype=float)))
        if volume <= 0:
            raise ValidationError(f"第 {frame} 帧盒体积非正，无法归一化 RDF")
        ideal = n_valid * shell / volume
        g_sum += np.divide(
            counts,
            ideal,
            out=np.full_like(counts, np.nan),
            where=ideal > 0,
        )
        n_frames += 1

    if n_frames == 0:
        raise ValidationError("RDF 帧窗口为空")
    g_r = g_sum / n_frames
    centers = 0.5 * (edges[1:] + edges[:-1])
    if not all(pbc):
        ctx.warn(
            "非周期方向的 RDF 用直接距离计算，但 g(r) 的体积归一化对非周期体系"
            "没有唯一物理定义；结果仅供定性参考。"
        )
    elif triclinic:
        ctx.warn("三斜盒逐帧归一化按盒体积处理；球壳在倾斜盒中的定义仍需谨慎解释。")
    extras = getattr(ctx, "extras", None)
    if isinstance(extras, dict):
        extras["rdf_geometry"] = {
            "kernel_pbc": list(pbc),
            "status": "qualitative" if (not all(pbc) or triclinic) else "supported",
        }
    return {"rdf": pd.DataFrame({"r_angstrom": centers, "g_r": g_r})}


def meta(ctx, tables) -> dict:
    info = dict(getattr(ctx, "extras", {}).get("rdf_geometry") or {})
    kernel = tuple(info["kernel_pbc"]) if info.get("kernel_pbc") is not None else None
    return geometry_meta(
        ctx,
        kernel_pbc=kernel,
        geometry_status=info.get("status"),
    )


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
