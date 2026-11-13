"""氢键寿命：连续型与间歇型两条存活曲线。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..plot import annotations, chart, plotutil
from ..errors import ValidationError
from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis


SLOTS = ("donor", "hydrogen", "acceptor")

PARAMS = {
    "d_a_cutoff": {
        "type": float,
        "default": 3.5,
        "unit": "Å",
        "min": 0.1,
        "help": "供体-受体距离上限",
    },
    "d_h_a_angle_cutoff": {
        "type": float,
        "default": 150,
        "unit": "度",
        "min": 0.0,
        "max": 180.0,
        "help": "D-H-A 角度下限",
    },
    "tau_max_ps": {
        "type": float,
        "default": 20,
        "unit": "ps",
        "min": 0.001,
        "help": "最大滞后时间，按帧间隔换算成帧",
    },
    "intermittency": {
        "type": int,
        "default": 1,
        "min": 0,
        "help": "间歇判据容忍的断帧数",
    },
    "window_step": {
        "type": int,
        "default": 1,
        "min": 1,
        "help": "时间原点取样步长；调大可加速",
    },
}

LABELS = {
    "zh": {
        "title": "氢键寿命",
        "x": "滞后 (ps)",
        "y": r"$C(\tau)$",
        "cont": "连续",
        "inter": "间歇（容忍 {n} 帧）",
    },
    "en": {
        "title": "Hydrogen bond lifetime",
        "x": "lag (ps)",
        "y": r"$C(\tau)$",
        "cont": "continuous",
        "inter": "intermittent ({n} frame tolerance)",
    },
}

LEVEL = 1.0 / np.e
# 帧间隔超过这个值就提示：水的氢键寿命约 1 ps，再粗的采样分辨不出来
MAX_FRAME_PS = 1.0


COLUMN_LABELS = {
    "zh": {"lag_ps": "滞后 (ps)", "continuous": "连续", "intermittent": "间歇"},
    "en": {
        "lag_ps": "lag (ps)",
        "continuous": "continuous",
        "intermittent": "intermittent",
    },
}

COMPARE = {
    "table": "hbond_lifetime",
    "x": "lag_ps",
    "y": ["continuous", "intermittent"],
    "box_axis": False,
}


def _selection(group) -> str:
    """把已解析的原子组变成固定的 bynum 选择串，避免按库自己的坐标系重选。"""
    indices = np.asarray(group.atoms.indices, dtype=int) + 1
    return "bynum " + " ".join(str(index) for index in indices)


def _build(ctx) -> HydrogenBondAnalysis:
    """按三个槽位与两个判据构造分析。

    判据与 hbond.py / hbond_type.py 必须一致；改动需三处同步
    （由 tests/analyses 的一致性测试守护）。
    """
    return HydrogenBondAnalysis(
        ctx.universe,
        donors_sel=_selection(ctx.groups["donor"]),
        hydrogens_sel=_selection(ctx.groups["hydrogen"]),
        acceptors_sel=_selection(ctx.groups["acceptor"]),
        d_a_cutoff=float(ctx.params["d_a_cutoff"]),
        d_h_a_angle_cutoff=float(ctx.params["d_h_a_angle_cutoff"]),
        update_selections=False,
    )


def run(ctx) -> dict[str, pd.DataFrame]:
    tau_max_ps = float(ctx.params["tau_max_ps"])
    intermittency = int(ctx.params["intermittency"])
    window_step = int(ctx.params["window_step"])
    frame_dt = ctx.frame_dt_ps

    if tau_max_ps <= 0:
        raise ValidationError(f"tau_max_ps 必须为正数，收到 {tau_max_ps}")
    if intermittency < 0 or window_step < 1:
        raise ValidationError("intermittency 不能为负，window_step 不能小于 1")
    tau_max = int(round(tau_max_ps / frame_dt))
    if tau_max < 1:
        raise ValidationError(
            f"tau_max_ps={tau_max_ps:g} 小于一帧（{frame_dt:g} ps），无法计算"
        )
    if frame_dt >= MAX_FRAME_PS:
        ctx.warn(
            f"帧间隔 {frame_dt:g} ps 已不小于水的氢键寿命量级（约 1 ps），"
            "寿命结果不可信；请用更密的 dump"
        )

    analysis = _build(ctx)
    analysis.run(start=ctx.start, stop=ctx.stop)

    # 单位：lifetime() 返回 (tau, C(tau))，tau 以「帧」为单位，乘 frame_dt 才是 ps
    continuous = np.asarray(
        analysis.lifetime(tau_max=tau_max, window_step=window_step, intermittency=0)
    )
    intermittent = np.asarray(
        analysis.lifetime(
            tau_max=tau_max, window_step=window_step, intermittency=intermittency
        )
    )

    lag = continuous[0] * frame_dt
    table = pd.DataFrame(
        {
            "lag_ps": lag,
            "continuous": continuous[1],
            "intermittent": intermittent[1],
        }
    )

    tau_cont = _crossing(lag, continuous[1])
    tau_inter = _crossing(lag, intermittent[1])
    summary = pd.DataFrame(
        [
            {"criterion": "continuous", "tau_1e_ps": tau_cont, "tolerance_frames": 0,
             "note": "" if np.isfinite(tau_cont) else "not reached 1/e"},
            {"criterion": "intermittent", "tau_1e_ps": tau_inter, "tolerance_frames": intermittency,
             "note": "" if np.isfinite(tau_inter) else "not reached 1/e"},
        ]
    )

    ctx.extras["hbond_lifetime"] = {
        "tau_max_ps": tau_max_ps,
        "tau_max_frames": tau_max,
        "frame_dt_ps": frame_dt,
        "tau_cont": tau_cont,
        "tau_inter": tau_inter,
        "intermittency": intermittency,
    }
    return {"hbond_lifetime": table, "hbond_lifetime_summary": summary}


def meta(ctx, tables) -> dict:
    return dict(ctx.extras.get("hbond_lifetime", {}))


def figures(ctx, tables):
    table = tables["hbond_lifetime"]
    info = ctx.extras.get("hbond_lifetime", {})
    lag = table["lag_ps"].to_numpy()
    intermittency = int(info.get("intermittency", 0))

    fig, ax = chart.figure(ctx.size("single"))
    chart.line(
        ax, lag, table["continuous"], lw=1.3, color=chart.COLORS["primary"],
        label=ctx.label("cont"),
    )
    chart.line(
        ax, lag, table["intermittent"], lw=1.3, ls="--", color=chart.COLORS["secondary"],
        label=ctx.label("inter", n=intermittency),
    )
    chart.refline(ax, LEVEL, ls=":", lw=0.8, color=chart.COLORS["guide"])
    chart.text(
        ax,
        lag[0] + 0.02 * (lag[-1] - lag[0]),
        LEVEL,
        "1/e",
        va="bottom",
        ha="left",
        fontsize=6,
        color=chart.COLORS["label"],
    )

    for key, color, height in (
        ("tau_cont", chart.COLORS["primary"], 0.66),
        ("tau_inter", chart.COLORS["secondary"], 0.46),
    ):
        value = info.get(key)
        if value is None or not np.isfinite(value):
            continue
        chart.vline(ax, value, ls=":", lw=0.8, color=color)
        chart.point_label(
            ax, value, height, f"{value:.2f} ps", offset=(3, 0), fontsize=6, color=color
        )

    ax.set_xlim(0, lag[-1])
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    plotutil.limit(ax, "x", ctx.window("x"))
    plotutil.limit(ax, "y", ctx.window("y"))
    ax.set_title(ctx.label("title"))
    chart.legend(ax)
    annotations.draw(ax, ctx)
    if ctx.annotate:
        chart.note(ax, ctx.annotation())
    return [("hbond_lifetime", fig)]


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #


def _crossing(lag: np.ndarray, curve: np.ndarray, level: float = LEVEL) -> float:
    """曲线首次降到 level 的时间，线性插值；始终未降到则返回 nan。"""
    below = np.nonzero(curve <= level)[0]
    if below.size == 0:
        return float("nan")
    index = int(below[0])
    if index == 0:
        return float(lag[0])
    x0, x1 = float(lag[index - 1]), float(lag[index])
    y0, y1 = float(curve[index - 1]), float(curve[index])
    if y1 == y0:
        return x1
    return x0 + (level - y0) * (x1 - x0) / (y1 - y0)
