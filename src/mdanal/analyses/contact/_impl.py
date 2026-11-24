"""contact 图包的科学内核：分子级接触与配位数。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from MDAnalysis.lib.distances import distance_array, minimize_vectors

from ...errors import ValidationError
from ...plot import annotations, chart, plotutil
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series

SLOTS = ("first", "second")

PARAMS = {
    "mode": {
        "type": str,
        "default": "com",
        "choices": ("com",),
        "help": "接触距离判据；第一版只支持质心距离 com",
    },
    "cutoff": {
        "type": float,
        "default": 10.0,
        "unit": "Å",
        "min": 0.1,
        "help": "分子质心接触距离阈值",
    },
    "block_ps": {
        "type": float,
        "default": 0.0,
        "unit": "ps",
        "min": 0.0,
        "help": "分块平均块宽；0 表示逐帧不平滑",
    },
    "time_origin": {
        "type": str,
        "default": "window",
        "choices": ("window", "absolute"),
        "help": "时间轴原点；window 从当前帧窗口起点开始，absolute 用绝对帧时间",
    },
}

LABELS = {
    "zh": {
        "title": "接触统计",
        "time": "时间 (ns)",
        "count": "接触数",
        "coordination": "配位数",
    },
    "en": {
        "title": "Contact statistics",
        "time": "time (ns)",
        "count": "contact count",
        "coordination": "coordination number",
    },
}

COORDINATES = "in_box"
KERNEL_PBC = (True, True, True)
GEOMETRY = {"cell": "any", "periodicity": "full"}


def _residues(group) -> list:
    atoms = group.atoms
    if atoms.n_atoms == 0:
        raise ValidationError(f"contact 组 {group.key or group.selection!r} 为空")
    selected = set(int(index) for index in atoms.indices)
    residues = []
    for residue in atoms.residues:
        indices = set(int(index) for index in residue.atoms.indices)
        if not indices.issubset(selected):
            raise ValidationError(
                f"contact 组 {group.key or group.selection!r} 只包含 "
                f"resid {int(residue.resid)} 的部分原子；需要完整分子"
            )
        residues.append(residue)
    return sorted(residues, key=lambda residue: int(residue.resid))


def _pbc_com(residues, box) -> np.ndarray:
    if box is None:
        raise ValidationError("contact 需要盒子信息；当前轨迹没有 dimensions")
    positions = []
    for residue in residues:
        pos = np.asarray(residue.atoms.positions, dtype=float)
        mass = np.asarray(residue.atoms.masses, dtype=float)
        if not np.isfinite(pos).all():
            raise ValidationError(f"resid {int(residue.resid)} 含非有限坐标")
        ref = pos[0]
        delta = minimize_vectors(pos - ref, box)
        positions.append(ref + (mass[:, None] * delta).sum(axis=0) / mass.sum())
    return np.asarray(positions, dtype=float)


def _count(first, second, cutoff: float, box) -> tuple[int, bool]:
    first_ids = {int(residue.resid) for residue in first}
    second_ids = {int(residue.resid) for residue in second}
    overlap = first_ids & second_ids
    if overlap and first_ids != second_ids:
        raise ValidationError(
            "contact 的 first/second 组只能完全相同或完全不相交；"
            f"当前共享 resid {sorted(overlap)[:5]}"
        )
    same = first_ids == second_ids
    ca = _pbc_com(first, box)
    cb = _pbc_com(second, box)
    distances = distance_array(ca, cb, box=box)
    inside = distances <= float(cutoff)
    if same:
        np.fill_diagonal(inside, False)
        count = int(inside[np.triu_indices(len(first), 1)].sum())
    else:
        count = int(inside.sum())
    return count, same


def _blocked(
    frames: np.ndarray,
    time_ps: np.ndarray,
    count: np.ndarray,
    coordination: np.ndarray,
    block_ps: float,
    frame_dt_ps: float,
) -> pd.DataFrame:
    n = len(frames)
    if n == 0:
        raise ValidationError("contact 帧窗口为空")
    if block_ps <= 0:
        return pd.DataFrame(
            {
                "frame": frames,
                "time_ps": time_ps,
                "count": count,
                "coordination": coordination,
                "block_start_ps": time_ps,
                "block_stop_ps": time_ps,
                "block_frames": np.ones(n, dtype=int),
            }
        )
    block_frames = max(1, int(round(float(block_ps) / frame_dt_ps)))
    blocks = []
    for start in range(0, n, block_frames):
        stop = min(n, start + block_frames)
        blocks.append((start, stop))
    centers = []
    means = []
    for start, stop in blocks:
        centers.append(float(time_ps[start:stop].mean()))
        means.append(
            (
                float(count[start:stop].mean()),
                float(coordination[start:stop].mean()),
            )
        )
    rows = []
    for (start, stop), center, (c, q) in zip(blocks, centers, means):
        rows.append(
            (
                int(frames[start]),
                center,
                c,
                q,
                float(time_ps[start]),
                float(time_ps[stop - 1]),
                int(stop - start),
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "frame",
            "time_ps",
            "count",
            "coordination",
            "block_start_ps",
            "block_stop_ps",
            "block_frames",
        ],
    )


def run(ctx) -> dict[str, pd.DataFrame]:
    needed = set(getattr(ctx, "requested_tables", frozenset()))
    if needed and "contact" not in needed:
        return {}
    first = _residues(ctx.groups["first"])
    second = _residues(ctx.groups["second"])
    mode = str(ctx.params.get("mode", "com"))
    if mode != "com":
        raise ValidationError(f"contact.mode={mode!r} 尚未实现；当前只支持 com")
    cutoff = float(ctx.params.get("cutoff", 10.0))
    if cutoff <= 0:
        raise ValidationError(f"contact.cutoff 必须为正数，收到 {cutoff}")
    block_ps = float(ctx.params.get("block_ps", 0.0))
    if block_ps < 0:
        raise ValidationError(f"contact.block_ps 不能为负，收到 {block_ps}")
    if 0 < block_ps < float(ctx.frame_dt_ps):
        ctx.warnings.append(
            f"contact.block_ps={block_ps:g} 小于帧间隔 "
            f"{float(ctx.frame_dt_ps):g} ps；按逐帧一块处理"
        )

    frames = np.arange(ctx.start, ctx.stop, dtype=int)
    origin = str(ctx.params.get("time_origin", "window"))
    if origin not in ("window", "absolute"):
        raise ValidationError(f"contact.time_origin={origin!r} 不是 window/absolute")
    time_origin = ctx.start if origin == "window" else 0
    time_ps = (frames - time_origin).astype(float) * float(ctx.frame_dt_ps)
    counts = []
    coords = []
    for frame in frames:
        ctx.universe.trajectory[int(frame)]
        count, same = _count(first, second, cutoff, ctx.universe.dimensions)
        counts.append(count)
        if same:
            coords.append(2.0 * count / len(first) if len(first) > 1 else 0.0)
        else:
            coords.append(count / len(first))
    table = _blocked(
        frames,
        time_ps,
        np.asarray(counts, dtype=float),
        np.asarray(coords, dtype=float),
        block_ps,
        float(ctx.frame_dt_ps),
    )
    return {"contact": table}


def _series(ctx, table, metric: str) -> Series:
    x = table["time_ps"].to_numpy(dtype=float) / 1000.0
    y = table[metric].to_numpy(dtype=float)
    if len(x):
        origin = str(ctx.params.get("time_origin", "window"))
        frame_dt = float(ctx.frame_dt_ps)
        if origin == "window":
            start_ns = 0.0
            end_ns = float(ctx.stop - ctx.start) * frame_dt / 1000.0
        else:
            start_ns = float(ctx.start) * frame_dt / 1000.0
            end_ns = float(ctx.stop) * frame_dt / 1000.0
        if x[0] > start_ns:
            x = np.concatenate(([start_ns], x))
            y = np.concatenate(([y[0]], y))
        if x[-1] < end_ns:
            x = np.concatenate((x, [end_ns]))
            y = np.concatenate((y, [y[-1]]))
    return Series(
        name=metric,
        curves=[
            Curve(
                x=x,
                y=y,
                label=ctx.label(metric),
            )
        ],
        label=ctx.label(metric),
    )


def panel_request(ctx, tables, metric: str = "count") -> PanelRequest:
    table = tables["contact"]
    if metric not in ("count", "coordination"):
        raise ValidationError(f"contact.metric={metric!r} 不是 count/coordination")
    return PanelRequest(
        recipe=f"contact-{metric}",
        series=[_series(ctx, table, metric)],
        title=ctx.label("title"),
        xlabel=ctx.label("time"),
        ylabel=ctx.label(metric),
        options={},
    )


def _curve_xlim(ctx, request: PanelRequest):
    xs = [curve.x for series in request.series for curve in series.curves]
    if not xs:
        return None
    values = np.concatenate(xs)
    if (request.metadata or {}).get("compare"):
        # compare 的各来源长度/采样可以不同；默认范围必须覆盖全部曲线。
        return (float(values.min()), float(values.max()))
    if str(ctx.params.get("time_origin", "window")) == "window":
        return (0.0, float(ctx.stop - ctx.start) * float(ctx.frame_dt_ps) / 1000.0)
    return (float(values.min()), float(values.max()))


def render_panel(ctx, request: PanelRequest) -> Panel:
    curves = [curve for series in request.series for curve in series.curves]
    show_legend = bool(request.options.get("legend")) or len(curves) > 1

    def draw(ax):
        for curve in curves:
            chart.line(
                ax,
                curve.x,
                curve.y,
                lw=curve.linewidth,
                color=curve.color,
                ls=curve.linestyle,
                label=curve.label if show_legend else None,
            )
        if show_legend:
            chart.legend(ax, loc=plotutil.legend_loc(ctx))
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name=request.recipe,
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label("time"),
        ylabel=request.ylabel or ctx.label("count"),
        aspect="auto",
        xlim=ctx.window("x") or _curve_xlim(ctx, request),
        ylim=ctx.window("y"),
        panel_size=ctx.size("single"),
    )
