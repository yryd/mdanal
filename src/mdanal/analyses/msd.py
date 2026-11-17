"""均方位移：默认按分子/残基质心计算，并给出线性拟合扩散系数。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..plot import annotations, chart, plotutil
from ..plot.panels import Panel
from ..plot.specs import Curve, PanelRequest, Series


SLOTS = ("group",)

PARAMS = {
    "msd_type": {
        "type": str,
        "default": "xyz",
        "choices": ("xyz", "xy", "xz", "yz", "x", "y", "z"),
        "help": "MSD 的维度组合",
    },
    "grouping": {
        "type": str,
        "default": "residues",
        "choices": ("residues", "atoms"),
        "help": "residues 按残基/分子质心；atoms 为原子 MSD",
    },
    "fit_range": {
        "type": list,
        "default": [],
        "help": "线性拟合的 [起, 止] ps；为空表示使用全部滞后点",
    },
    "fft": {
        "type": bool,
        "default": True,
        "help": "兼容旧参数；质心路径使用直接时间平均",
    },
}

LABELS = {
    "zh": {
        "title": "均方位移",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
        "fit": "线性拟合",
        "d": "D",
    },
    "en": {
        "title": "Mean squared displacement",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
        "fit": "linear fit",
        "d": "D",
    },
}

COORDINATES = "continuous"


COLUMN_LABELS = {
    "zh": {"dt_ps": r"$\Delta t$ (ps)", "msd_A2": "MSD (Å$^{2}$)"},
    "en": {"dt_ps": r"$\Delta t$ (ps)", "msd_A2": "MSD (Å$^{2}$)"},
}

COMPARE = {
    "table": "msd",
    "x": "dt_ps",
    "y": ["msd_A2"],
    "box_axis": False,
}


GEOMETRY = {"cell": "any", "periodicity": "any"}

AXIS_SETS = {
    "xyz": (0, 1, 2),
    "xy": (0, 1),
    "xz": (0, 2),
    "yz": (1, 2),
    "x": (0,),
    "y": (1,),
    "z": (2,),
}


def _com_trajectory(atoms, grouping: str, start: int, stop: int) -> np.ndarray:
    """按 atoms 或 residue 求每帧质心；返回 (frames, units, 3)。"""
    if grouping == "atoms":
        inverse = np.arange(atoms.n_atoms, dtype=int)
    elif grouping == "residues":
        try:
            residues = np.asarray(atoms.resindices)
        except Exception:
            residues = np.arange(atoms.n_atoms, dtype=int)
        _, inverse = np.unique(residues, return_inverse=True)
    else:
        raise ValueError(f"未知的 msd grouping：{grouping!r}")

    try:
        masses = np.asarray(atoms.masses, dtype=float)
    except Exception:
        masses = np.ones(atoms.n_atoms, dtype=float)
    if masses.size != atoms.n_atoms or not np.all(np.isfinite(masses)):
        masses = np.ones(atoms.n_atoms, dtype=float)
    mass_by_unit = np.bincount(inverse, weights=masses)
    if np.any(mass_by_unit <= 0):
        raise ValueError("存在总质量为 0 的 MSD 统计单元")

    n_units = len(mass_by_unit)
    com = np.empty((stop - start, n_units, 3), dtype=float)
    universe = atoms.universe
    for offset, frame in enumerate(range(start, stop)):
        universe.trajectory[frame]
        positions = np.asarray(atoms.positions, dtype=float)
        for axis in range(3):
            numerator = np.bincount(
                inverse, weights=masses * positions[:, axis]
            )
            com[offset, :, axis] = numerator / mass_by_unit
    return com


def _msd_from_com(com: np.ndarray, msd_type: str) -> np.ndarray:
    axes = AXIS_SETS[msd_type]
    n_frames = len(com)
    msd = np.empty(n_frames, dtype=float)
    for lag in range(n_frames):
        delta = com[lag:] - com[: n_frames - lag]
        msd[lag] = float(np.mean(np.sum(delta[..., axes] ** 2, axis=-1)))
    return msd


def _parse_fit_range(value, lag: np.ndarray) -> tuple[float, float]:
    if value in (None, [], ()):
        return float(lag[0]), float(lag[-1])
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
    ):
        raise ValueError("fit_range 必须是 [起, 止] 两个数值")
    low, high = float(value[0]), float(value[1])
    if high <= low:
        raise ValueError("fit_range 必须递增")
    if low < float(lag[0]) or high > float(lag[-1]):
        raise ValueError(f"fit_range 超出可用滞后范围 [{lag[0]}, {lag[-1]}]")
    return low, high


def run(ctx) -> dict[str, pd.DataFrame]:
    grouping = str(ctx.params.get("grouping", "residues"))
    atoms = ctx.groups["group"].atoms
    if atoms.n_atoms == 0:
        raise ValueError("MSD 分组为空")
    com = _com_trajectory(atoms, grouping, ctx.start, ctx.stop)
    msd_type = str(ctx.params["msd_type"])
    msd = _msd_from_com(com, msd_type)

    universe = atoms.universe
    dt = float(getattr(ctx, "frame_dt_ps", universe.trajectory.ts.dt))
    lag = np.arange(len(msd), dtype=float) * dt
    low, high = _parse_fit_range(ctx.params.get("fit_range"), lag)
    mask = (lag >= low) & (lag <= high)
    if int(mask.sum()) < 2:
        raise ValueError("fit_range 内不足两个点，无法拟合")

    slope, intercept = np.polyfit(lag[mask], msd[mask], 1)
    dimension = len(AXIS_SETS[msd_type])
    d_a2_ps = float(slope / (2.0 * dimension))
    d_m2_s = d_a2_ps * 1e-8
    fitted = np.full_like(msd, np.nan)
    fitted[mask] = slope * lag[mask] + intercept
    table = pd.DataFrame(
        {
            "dt_ps": lag,
            "msd_A2": msd,
            "fit_msd_A2": fitted,
        }
    )
    fit = {
        "grouping": grouping,
        "fit_range": [low, high],
        "dimension": dimension,
        "slope_A2_per_ps": float(slope),
        "intercept_A2": float(intercept),
        "D_A2_per_ps": d_a2_ps,
        "D_m2_per_s": d_m2_s,
    }
    if hasattr(ctx, "extras"):
        ctx.extras["msd_fit"] = fit
    return {"msd": table}


def meta(ctx, tables) -> dict:
    return dict(ctx.extras.get("msd_fit", {}))


def build_series(ctx, tables) -> list[Series]:
    table = tables["msd"]
    raw = Curve(
        x=table["dt_ps"].to_numpy(dtype=float),
        y=table["msd_A2"].to_numpy(dtype=float),
        label=ctx.label("y"),
        metadata={"marker": "o"},
    )
    series = [Series(name="msd_A2", curves=[raw], label=ctx.label("y"))]
    if table["fit_msd_A2"].notna().any():
        fit = Curve(
            x=table["dt_ps"].to_numpy(dtype=float),
            y=table["fit_msd_A2"].to_numpy(dtype=float),
            label=ctx.label("fit"),
            color=chart.COLORS["secondary"],
            linestyle="--",
        )
        series.append(Series(name="fit_msd_A2", curves=[fit], label=ctx.label("fit")))
    return series


def panel_request(ctx, tables) -> PanelRequest:
    return PanelRequest(
        recipe="msd",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": True},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        curves = [curve for series in request.series for curve in series.curves]
        show_legend = bool(request.options.get("legend")) or len(curves) > 1
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
                    marker=curve.metadata.get("marker"),
                    label=curve.label if show_legend else None,
                )
        fit = ctx.meta.get("msd_fit", ctx.meta) if ctx.meta else {}
        d_value = fit.get("D_m2_per_s")
        if d_value is not None:
            d_text = (
                f"{ctx.label('d')} = {d_value / 1e-9:.3f} "
                r"$\times 10^{-9}$ m$^2$ s$^{-1}$"
            )
            chart.note(ax, d_text, at=(0.015, 0.88), fontsize=7)
        if show_legend:
            chart.legend(ax)
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    return Panel(
        name="msd",
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
    return "msd"
