"""流速剖面（MAICoS VelocityPlanar）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError

AXES = ("x", "y", "z")


SLOTS = ("group", "ref")

PARAMS = {
    "dim": {
        "type": (str, int),
        "default": "z",
        "choices": AXES + (0, 1, 2),
        "help": "剖面的法向轴：名称 x/y/z 或序号 0/1/2",
    },
    "vdim": {
        "type": (str, int),
        "default": "x",
        "choices": AXES + (0, 1, 2),
        "help": "速度分量：名称 x/y/z 或序号 0/1/2",
    },
    "bin_width": {
        "type": float,
        "default": 1.0,
        "unit": "Å",
        "min": 0.01,
        "help": "剖面 bin 宽",
    },
    "grouping": {
        "type": str,
        "default": "molecules",
        "choices": ("atoms", "residues", "segments", "molecules"),
        "help": "按什么分组统计速度",
    },
    "sym": {
        "type": bool,
        "default": False,
        "help": "是否对剖面做对称化",
    },
}

LABELS = {
    "zh": {
        "title": "流速剖面",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "v_x": "$v_x$ (Å ps$^{-1}$)",
        "v_y": "$v_y$ (Å ps$^{-1}$)",
        "v_z": "$v_z$ (Å ps$^{-1}$)",
    },
    "en": {
        "title": "Velocity profile",
        "axis_x": "$x$ (Å)",
        "axis_y": "$y$ (Å)",
        "axis_z": "$z$ (Å)",
        "v_x": "$v_x$ (Å ps$^{-1}$)",
        "v_y": "$v_y$ (Å ps$^{-1}$)",
        "v_z": "$v_z$ (Å ps$^{-1}$)",
    },
}

REQUIRES = ("velocities",)
PACKAGE = {"name": "maicos", "min_version": "0.12"}
MUTATES_POSITIONS = True


COLUMN_LABELS = {
    "zh": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "vx_A_per_ps": "$v_x$ (Å ps$^{-1}$)",
        "vy_A_per_ps": "$v_y$ (Å ps$^{-1}$)",
        "vz_A_per_ps": "$v_z$ (Å ps$^{-1}$)",
    },
    "en": {
        "x_angstrom": "$x$ (Å)", "y_angstrom": "$y$ (Å)", "z_angstrom": "$z$ (Å)",
        "vx_A_per_ps": "$v_x$ (Å ps$^{-1}$)",
        "vy_A_per_ps": "$v_y$ (Å ps$^{-1}$)",
        "vz_A_per_ps": "$v_z$ (Å ps$^{-1}$)",
    },
}

COMPARE = {
    "table": "velocity",
    "x": "{axis}_angstrom",
    "y": ["v{vdim}_A_per_ps"],
    "box_axis": True,
}


def run(ctx) -> dict[str, pd.DataFrame]:
    from maicos.modules.velocityplanar import VelocityPlanar

    dim, vdim, axis = _axes(ctx)

    # 剖面坐标以参考组质心为零点；把该质心加回去即盒坐标
    ctx.universe.trajectory[ctx.selection_frame]
    ref = float(ctx.groups["ref"].atoms.center_of_mass()[dim])
    ctx.extras["velocity_ref"] = ref

    # 单位：MAICoS 的 bin_pos 为 Å，profile 为 Å/ps，dprofile 是标准误（Å/ps）
    analysis = VelocityPlanar(
        ctx.groups["group"].atoms,
        dim=dim,
        vdim=vdim,
        bin_width=float(ctx.params["bin_width"]),
        grouping=str(ctx.params["grouping"]),
        refgroup=ctx.groups["ref"].atoms,
        sym=bool(ctx.params["sym"]),
        unwrap=True,
        pack=True,
        output=None,
    )
    analysis.run(start=ctx.start, stop=ctx.stop)

    table = pd.DataFrame(
        {
            f"{axis}_angstrom": np.asarray(analysis.results.bin_pos, dtype=float) + ref,
            f"v{AXES[vdim]}_A_per_ps": np.asarray(analysis.results.profile, dtype=float),
            "error_A_per_ps": np.asarray(analysis.results.dprofile, dtype=float),
        }
    )
    return {"velocity": table}


def meta(ctx, tables) -> dict:
    return {
        "axis": _axes(ctx)[2],
        "ref_com": ctx.extras.get("velocity_ref"),
        "ref_frame": ctx.selection_frame,
    }


def figures(ctx, tables):
    name, table = next(iter(tables.items()))
    dim, vdim, axis = _axes(ctx)
    coordinate = table[f"{axis}_angstrom"].to_numpy()
    velocity = table[f"v{AXES[vdim]}_A_per_ps"].to_numpy()

    # 没有样本的 bin 用 NaN 占位，让折线在该处断开而不是跨空档直连
    velocity_plot = np.where(np.isfinite(velocity), velocity, np.nan)

    shift = ctx.system.view.shift[dim]
    fig, ax = chart.figure(ctx.size("single"))
    chart.line(ax, coordinate + shift, velocity_plot, lw=1.2)
    ax.set_xlabel(ctx.label(f"axis_{axis}"))
    ax.set_ylabel(ctx.label(f"v_{AXES[vdim]}"))
    ax.set_title(ctx.label("title"))
    plotutil.limit(ax, "x", ctx.window(axis))
    annotations.draw(ax, ctx, axes={"x": axis})
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [(name, fig)]


def _axes(ctx) -> tuple[int, int, str]:
    dim = _axis_index(ctx.params["dim"], "dim")
    vdim = _axis_index(ctx.params["vdim"], "vdim")
    return dim, vdim, AXES[dim]


def _axis_index(value, key: str) -> int:
    """轴名（x/y/z）或序号（0/1/2）转成轴序号。"""
    if isinstance(value, str):
        name = value.strip().lower()
        if name in AXES:
            return AXES.index(name)
    elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2:
        return int(value)
    raise ValidationError(f"{key} 只能是 x、y、z 或 0、1、2，收到 {value!r}")
