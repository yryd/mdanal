"""均方位移：默认按分子/残基质心计算。"""

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
    },
    "en": {
        "title": "Mean squared displacement",
        "x": r"$\Delta t$ (ps)",
        "y": "MSD (Å$^{2}$)",
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
    table = pd.DataFrame({"dt_ps": lag, "msd_A2": msd})
    return {"msd": table}


def build_series(ctx, tables) -> list[Series]:
    table = tables["msd"]
    curve = Curve(
        x=table["dt_ps"].to_numpy(dtype=float),
        y=table["msd_A2"].to_numpy(dtype=float),
        label=ctx.label("y"),
    )
    return [Series(name="msd_A2", curves=[curve], label=ctx.label("y"))]


def panel_request(ctx, tables) -> PanelRequest:
    return PanelRequest(
        recipe="msd",
        series=build_series(ctx, tables),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    def draw(ax):
        for series in request.series:
            for curve in series.curves:
                chart.line(
                    ax,
                    curve.x,
                    curve.y,
                    lw=curve.linewidth,
                    color=curve.color,
                    ls=curve.linestyle,
                )
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
