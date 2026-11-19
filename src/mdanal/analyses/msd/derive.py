"""MSD 的科学派生：线性拟合、D 和 RDC。"""

from __future__ import annotations

import numpy as np
import pandas as pd

AXIS_DIM = {"xyz": 3, "xy": 2, "xz": 2, "yz": 2, "x": 1, "y": 1, "z": 1}


def _fit_stats(x: np.ndarray, y: np.ndarray, *, zero_intercept: bool) -> tuple[float, float, float]:
    if zero_intercept:
        slope = float(np.dot(x, y) / np.dot(x, x))
        intercept = 0.0
        residual = y - slope * x
        dof = max(len(x) - 1, 1)
    else:
        slope, intercept = np.polyfit(x, y, 1)
        slope, intercept = float(slope), float(intercept)
        residual = y - (slope * x + intercept)
        dof = max(len(x) - 2, 1)
    sse = float(np.sum(residual**2))
    sxx = float(np.sum((x - x.mean()) ** 2)) if not zero_intercept else float(np.dot(x, x))
    stderr = float(np.sqrt(sse / dof / sxx)) if sxx > 0 else float("nan")
    return slope, intercept, stderr


def _window(spec: dict, t_ns: np.ndarray) -> tuple[float, float]:
    value = spec.get("window_ns")
    if value is None:
        return float(t_ns[0]), float(t_ns[-1])
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise ValueError("derive.fit.window_ns 必须是 [起, 止] 两个数")
    low, high = float(value[0]), float(value[1])
    if high <= low:
        raise ValueError("derive.fit.window_ns 必须递增")
    if low < float(t_ns[0]) or high > float(t_ns[-1]):
        raise ValueError(f"derive.fit.window_ns 超出 [{t_ns[0]}, {t_ns[-1]}]")
    return low, high


def run(ctx, tables: dict[str, pd.DataFrame], spec: dict) -> dict[str, pd.DataFrame]:
    table = tables["msd"]
    t_ns = table["dt_ns"].to_numpy(dtype=float)
    msd = table["msd_A2"].to_numpy(dtype=float)
    out: dict[str, pd.DataFrame] = {}

    fit_spec = spec.get("fit")
    summary = None
    fit_values = np.full_like(msd, np.nan)
    if fit_spec is not None:
        if not isinstance(fit_spec, dict):
            raise ValueError("derive.fit 必须是映射")
        low, high = _window(fit_spec, t_ns)
        mask = (t_ns >= low) & (t_ns <= high)
        if int(mask.sum()) < 2:
            raise ValueError("derive.fit 窗口内少于两个点")
        intercept_mode = str(fit_spec.get("intercept", "free"))
        if intercept_mode not in ("free", "zero"):
            raise ValueError("derive.fit.intercept 只能是 free 或 zero")
        slope, intercept, stderr = _fit_stats(
            t_ns[mask], msd[mask], zero_intercept=intercept_mode == "zero"
        )
        dimension = AXIS_DIM[str(ctx.params.get("msd_type", "xyz"))]
        d_ns = slope / (2.0 * dimension)
        d_ps = d_ns / 1000.0
        fit_values[mask] = slope * t_ns[mask] + intercept
        summary = pd.DataFrame(
            [
                {
                    "D_A2_per_ps": d_ps,
                    "D_m2_per_s": d_ps * 1e-8,
                    "D_stderr_A2_per_ps": stderr / (2.0 * dimension) / 1000.0,
                    "slope_A2_per_ns": slope,
                    "intercept_A2": intercept,
                    "fit_start_ns": low,
                    "fit_end_ns": high,
                    "n_points": int(mask.sum()),
                    "intercept_mode": intercept_mode,
                }
            ]
        )
        out["msd_fit"] = pd.DataFrame(
            {"dt_ns": t_ns, "fit_msd_A2": fit_values}
        )
        out["msd_fit_summary"] = summary

    if "rdc" in spec:
        dim = AXIS_DIM[str(ctx.params.get("msd_type", "xyz"))]
        rdc = np.full_like(msd, np.nan)
        positive = t_ns > 0
        rdc[positive] = msd[positive] / (2.0 * dim * t_ns[positive]) / 1000.0
        out["msd_rdc"] = pd.DataFrame(
            {"dt_ns": t_ns, "rdc_A2_per_ps": rdc}
        )
    return out
