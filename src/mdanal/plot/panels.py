"""通用单图画布：每个 Panel 只负责自己，compose 只负责按 ncols 排版。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable


@dataclass
class Panel:
    """一个独立单图；draw 返回可挂 colorbar 的 mappable（没有则返回 None）。"""

    name: str
    draw: Callable[[Any], Any]
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    aspect: str | float | None = "auto"
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    colorbar_label: str | None = None
    panel_size: tuple[float, float] = (4.2, 3.0)
