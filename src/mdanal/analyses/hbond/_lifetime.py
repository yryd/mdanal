"""氢键寿命：连续型与间歇型两条存活曲线。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .._geometry import full_periodic_meta
from ...plot import annotations, chart, plotutil
from ...plot.panels import Panel
from ...plot.specs import Curve, PanelRequest, Series
from ...errors import ValidationError


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

COORDINATES = "in_box"

GEOMETRY = {"cell": "any", "periodicity": "full"}


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
    n_frames = max(int(ctx.stop) - int(ctx.start), 1)
    max_lag_ps = float(n_frames - 1) * frame_dt
    requested_tau_max_ps = tau_max_ps
    if tau_max > n_frames - 1:
        tau_max = max(n_frames - 1, 1)
        tau_max_ps = tau_max * frame_dt
        ctx.warn(
            f"tau_max_ps={requested_tau_max_ps:g} 超过当前窗口可用最大 lag≈{max_lag_ps:g} ps；"
            f"按 {tau_max_ps:g} ps 截断，尾部不会伪造或填零"
        )

    from .._hbond import analysis as _analysis

    analysis = _analysis(ctx)

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
    no_events = len(analysis.results.hbonds) == 0
    if no_events:
        ctx.warn(
            "分析窗口内没有任何氢键事件；寿命曲线没有可估计样本，"
            "tau_1e_ps 不是“尚未衰减”，而是未定义。"
        )

    def _status(tau: float) -> str:
        if no_events:
            return "no_events"
        return "reached" if np.isfinite(tau) else "not_reached"

    def _note(tau: float) -> str:
        if no_events:
            return "no hydrogen-bond events; lifetime undefined"
        return "" if np.isfinite(tau) else "not decayed to 1/e within tau_max"

    summary = pd.DataFrame(
        [
            {
                "criterion": "continuous",
                "tau_1e_ps": tau_cont,
                "status": _status(tau_cont),
                "tolerance_frames": 0,
                "note": _note(tau_cont),
            },
            {
                "criterion": "intermittent",
                "tau_1e_ps": tau_inter,
                "status": _status(tau_inter),
                "tolerance_frames": intermittency,
                "note": _note(tau_inter),
            },
        ]
    )

    ctx.extras["hbond_lifetime"] = {
        "tau_max_ps": tau_max_ps,
        "tau_max_ps_requested": requested_tau_max_ps,
        "tau_max_frames": tau_max,
        "frame_dt_ps": frame_dt,
        "tau_cont": tau_cont,
        "tau_inter": tau_inter,
        "intermittency": intermittency,
        "no_events": no_events,
    }
    return {"hbond_lifetime": table, "hbond_lifetime_summary": summary}


def meta(ctx, tables) -> dict:
    return {
        **dict(ctx.extras.get("hbond_lifetime", {})),
        **full_periodic_meta(ctx),
    }


def _criterion(value: str) -> tuple[str, str, str]:
    """返回 (列名, 标签键, 元数据 tau 键)。"""
    if value == "continuous":
        return "continuous", "cont", "tau_cont"
    if value == "intermittent":
        return "intermittent", "inter", "tau_inter"
    raise ValidationError(
        f"hbond lifetime criterion={value!r} 不是 continuous/intermittent"
    )


def build_curve(ctx, tables, criterion: str = "continuous") -> Curve:
    """一个 criterion 恰好一条单曲线。"""
    column, _, _ = _criterion(criterion)
    table = tables["hbond_lifetime"]
    info = ctx.extras.get("hbond_lifetime", {})
    intermittency = int(info.get("intermittency", 0))
    lag = table["lag_ps"].to_numpy(dtype=float)
    color = chart.COLORS["primary"] if criterion == "continuous" else chart.COLORS["secondary"]
    linestyle = "-" if criterion == "continuous" else "--"
    label = (
        ctx.label("cont")
        if criterion == "continuous"
        else ctx.label("inter", n=intermittency)
    )
    return Curve(
        x=lag,
        y=table[column].to_numpy(dtype=float),
        label=label,
        color=color,
        linestyle=linestyle,
        linewidth=1.3,
    )


def build_series(ctx, tables, criterion: str = "continuous") -> list[Series]:
    curve = build_curve(ctx, tables, criterion)
    return [Series(name=criterion, curves=[curve], label=curve.label)]


def panel_request(ctx, tables, criterion: str = "continuous") -> PanelRequest:
    return PanelRequest(
        recipe=f"hbond_lifetime_{criterion}",
        series=build_series(ctx, tables, criterion),
        title=ctx.label("title"),
        xlabel=ctx.label("x"),
        ylabel=ctx.label("y"),
        options={"legend": False, "native": True},
    )


def render_panel(ctx, request: PanelRequest) -> Panel:
    info = ctx.extras.get("hbond_lifetime", {})
    native = bool(request.options.get("native"))
    curves = [curve for series in request.series for curve in series.curves]
    criterion = request.series[0].name
    _, _, tau_key = _criterion(criterion)
    color = curves[0].color
    show_legend = bool(request.options.get("legend")) or len(curves) > 1
    is_compare = bool((request.metadata or {}).get("compare"))

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
        if native and len(curves[0].x):
            lag = curves[0].x
            chart.refline(
                ax,
                LEVEL,
                ls=":",
                lw=chart.ANNOTATION_LINEWIDTH,
                color=chart.COLORS["guide"],
            )
            chart.text(
                ax,
                lag[0] + 0.02 * (lag[-1] - lag[0]),
                LEVEL,
                "1/e",
                va="bottom",
                ha="left",
                fontsize=chart.ANNOTATION_FONTSIZE,
                color=chart.COLORS["label"],
            )
            value = info.get(tau_key) if not is_compare else None
            if value is not None and np.isfinite(value):
                chart.vline(
                    ax,
                    value,
                    ls=":",
                    lw=chart.ANNOTATION_LINEWIDTH,
                    color=color,
                )
                chart.point_label(
                    ax,
                    value,
                    0.66 if criterion == "continuous" else 0.46,
                    f"{value:.2f} ps",
                    offset=(3, 0),
                    fontsize=chart.ANNOTATION_FONTSIZE,
                    color=color,
                )
        if show_legend:
            chart.legend(ax, loc=plotutil.legend_loc(ctx))
        annotations.draw(ax, ctx)
        if ctx.annotate:
            chart.note(ax, ctx.annotation())
        return None

    xlim = None
    ylim = (0.0, 1.02) if native else None
    if native and curves:
        ends = [float(curve.x[-1]) for curve in curves if len(curve.x)]
        if ends:
            xlim = (0.0, max(ends) if is_compare else ends[0])
    if ctx.window("x") is not None:
        xlim = ctx.window("x")
    return Panel(
        name="hbond_lifetime",
        draw=draw,
        title=request.title,
        xlabel=request.xlabel or ctx.label("x"),
        ylabel=request.ylabel or ctx.label("y"),
        aspect="auto",
        xlim=xlim,
        ylim=ylim,
        panel_size=ctx.size("single"),
    )


def panels(ctx, tables, criterion: str = "continuous") -> list[Panel]:
    request = panel_request(ctx, tables, criterion)
    return [render_panel(ctx, request)]


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
