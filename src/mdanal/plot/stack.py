"""堆叠曲线：纯数组 → 累积面积，不依赖运行上下文。"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ..errors import ValidationError


def stack(
    ax,
    x: Sequence[float],
    curves: Sequence[Sequence[float]],
    *,
    labels: Sequence[str] | None = None,
    colors: Sequence[str] | None = None,
    alpha: float = 0.8,
):
    """把同 x 的非负曲线按输入顺序累积绘制。"""
    x = np.asarray(x, dtype=float)
    if x.ndim != 1 or x.size == 0:
        raise ValidationError("stack 的 x 必须是非空一维序列")
    arrays = [np.asarray(curve, dtype=float) for curve in curves]
    if len(arrays) < 2:
        raise ValidationError("stack 至少需要两条曲线")
    if any(array.shape != x.shape for array in arrays):
        raise ValidationError("stack 的所有曲线必须与 x 等长")
    if any(not np.all(np.isfinite(array)) for array in arrays):
        raise ValidationError("stack 的曲线包含非有限值")
    if any(np.any(array < 0) for array in arrays):
        raise ValidationError("stack 的曲线不允许负值")
    if labels is not None and len(labels) != len(arrays):
        raise ValidationError("stack 的 labels 数量与曲线不一致")
    if colors is not None and not colors:
        raise ValidationError("stack 的 colors 不能为空")

    from . import chart

    colors = list(colors) if colors is not None else list(chart.THEME_COLORS)
    colors = [colors[index % len(colors)] for index in range(len(arrays))]
    labels = list(labels) if labels is not None else [""] * len(arrays)
    bottom = np.zeros_like(x)
    for values, label, color in zip(arrays, labels, colors):
        top = bottom + values
        ax.fill_between(
            x, bottom, top, color=color, alpha=alpha, label=label, linewidth=0
        )
        bottom = top
    return bottom
