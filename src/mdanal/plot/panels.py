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


def compose_panels(
    panels: Sequence[Panel],
    *,
    ncols: int = 1,
    title: str | None = None,
    wspace: float = 0.20,
    hspace: float = 0.38,
    top: float = 0.92,
) -> plt.Figure:
    """把所有 Panel 按 ncols 排成网格；空位隐藏，每个 Panel 各自带色标。"""
    if not panels:
        raise ValueError("至少需要一个 Panel")
    if not isinstance(ncols, int) or isinstance(ncols, bool) or ncols < 1:
        raise ValueError(f"ncols 必须是正整数，收到 {ncols!r}")

    nrows = (len(panels) + ncols - 1) // ncols
    base_w = max(panel.panel_size[0] for panel in panels)
    base_h = max(panel.panel_size[1] for panel in panels)
    # 多列时按面板高度定宽，避免 subplot 单元比正方形面板宽太多，
    # 在列间留下大块空白；单列仍按原 map 宽度。
    figure_width = base_w if ncols == 1 else base_h * ncols + 0.4
    fig, axes_array = plt.subplots(
        nrows,
        ncols,
        figsize=(figure_width, base_h * nrows + 0.4),
        squeeze=False,
    )
    axes = axes_array.ravel()

    for ax, panel in zip(axes, panels):
        mappable = panel.draw(ax)
        if panel.title:
            ax.set_title(panel.title)
        if panel.xlabel:
            ax.set_xlabel(panel.xlabel)
        if panel.ylabel:
            ax.set_ylabel(panel.ylabel)
        if panel.aspect is not None:
            ax.set_aspect(panel.aspect)
        if panel.xlim is not None:
            ax.set_xlim(panel.xlim)
        if panel.ylim is not None:
            ax.set_ylim(panel.ylim)

        if mappable is not None and panel.colorbar_label is not None:
            cax = make_axes_locatable(ax).append_axes(
                "right", size="3.5%", pad=0.06
            )
            bar = fig.colorbar(mappable, cax=cax)
            if panel.colorbar_label:
                bar.set_label(panel.colorbar_label)

    for ax in axes[len(panels):]:
        ax.set_visible(False)

    if title:
        fig.suptitle(title)
    fig.subplots_adjust(
        left=0.06,
        right=0.97,
        bottom=0.10,
        top=top,
        wspace=wspace,
        hspace=hspace,
    )
    return fig
