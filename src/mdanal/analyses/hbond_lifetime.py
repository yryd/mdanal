"""氢键寿命：连续型与间歇型两条存活曲线。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import plotutil
from ..errors import ValidationError
from .hbond import build_analysis

LEVEL = 1.0 / np.e
# 帧间隔超过这个值就提示：水的氢键寿命约 1 ps，再粗的采样分辨不出来
MAX_FRAME_PS = 1.0


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

    analysis = build_analysis(ctx)
    analysis.run(start=ctx.start, stop=ctx.stop)

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
            "滞后 (ps)": lag,
            "连续": continuous[1],
            "间歇": intermittent[1],
        }
    )

    tau_cont = _crossing(lag, continuous[1])
    tau_inter = _crossing(lag, intermittent[1])
    summary = pd.DataFrame(
        [
            {"判据": "连续", "氢键寿命 (ps)": tau_cont, "断帧容忍 (帧)": 0,
             "备注": "" if np.isfinite(tau_cont) else "未降到 1/e"},
            {"判据": "间歇", "氢键寿命 (ps)": tau_inter, "断帧容忍 (帧)": intermittency,
             "备注": "" if np.isfinite(tau_inter) else "未降到 1/e"},
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
    lag = table["滞后 (ps)"].to_numpy()
    intermittency = int(info.get("intermittency", 0))

    fig, ax = plotutil.figure(ctx.size("single"))
    ax.plot(lag, table["连续"], lw=1.3, color="#4165c0", label=ctx.label("cont"))
    ax.plot(
        lag, table["间歇"], lw=1.3, ls="--", color="#c05040",
        label=ctx.label("inter", n=intermittency),
    )
    ax.axhline(LEVEL, ls=":", lw=0.8, color="0.45")
    ax.text(
        lag[0] + 0.02 * (lag[-1] - lag[0]), LEVEL, "1/e",
        va="bottom", ha="left", fontsize=6, color="0.35",
    )

    for key, curve, color in (
        ("tau_cont", table["连续"].to_numpy(), "#4165c0"),
        ("tau_inter", table["间歇"].to_numpy(), "#c05040"),
    ):
        value = info.get(key)
        if value is None or not np.isfinite(value):
            continue
        ax.axvline(value, ls=":", lw=0.8, color=color)
        ax.annotate(
            f"{value:.2f} ps",
            xy=(value, 0.55),
            xytext=(3, 0),
            textcoords="offset points",
            fontsize=6,
            color=color,
        )

    ax.set_xlim(0, lag[-1])
    ax.set_ylim(0, 1.02)
    ax.set_xlabel(ctx.label("x"))
    ax.set_ylabel(ctx.label("y"))
    ax.set_title(ctx.label("title"))
    ax.legend(loc="upper right", fontsize=6, frameon=False)
    if ctx.annotate:
        plotutil.annotate(ax, ctx.annotation())
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
