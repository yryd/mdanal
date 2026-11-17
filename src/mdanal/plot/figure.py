"""平台 Figure 层：只接收 Panel，按 ncols 排版并生成 Matplotlib Figure。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable

from .panels import Panel


@dataclass
class Figure:
    """一组 Panel 的平台排版结果；插件不负责创建它。"""

    panels: Sequence[Panel]
    ncols: int = 1
    title: str | None = None
    wspace: float = 0.20
    hspace: float = 0.38
    top: float = 0.92

    def build(self) -> plt.Figure:
        panels = list(self.panels)
        if not panels:
            raise ValueError("至少需要一个 Panel")
        if (
            not isinstance(self.ncols, int)
            or isinstance(self.ncols, bool)
            or self.ncols < 1
        ):
            raise ValueError(f"ncols 必须是正整数，收到 {self.ncols!r}")

        nrows = (len(panels) + self.ncols - 1) // self.ncols
        base_w = max(panel.panel_size[0] for panel in panels)
        base_h = max(panel.panel_size[1] for panel in panels)
        # 多列时按面板高度定宽，避免 subplot 单元比正方形面板宽太多。
        figure_width = base_w if self.ncols == 1 else base_h * self.ncols + 0.4
        fig, axes_array = plt.subplots(
            nrows,
            self.ncols,
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
                    "right", size="3.5%", pad=0.03
                )
                bar = fig.colorbar(mappable, cax=cax)
                if panel.colorbar_label:
                    bar.set_label(panel.colorbar_label)

        for ax in axes[len(panels):]:
            ax.set_visible(False)

        if self.title:
            fig.suptitle(self.title)
        fig.subplots_adjust(
            left=0.06,
            right=0.97,
            bottom=0.10,
            top=self.top,
            wspace=self.wspace,
            hspace=self.hspace,
        )
        return fig


def compose_panels(
    panels: Sequence[Panel],
    *,
    ncols: int = 1,
    title: str | None = None,
    wspace: float = 0.20,
    hspace: float = 0.38,
    top: float = 0.92,
) -> plt.Figure:
    """兼容入口；新代码用 Figure(...).build()。"""
    return Figure(
        panels=panels,
        ncols=ncols,
        title=title,
        wspace=wspace,
        hspace=hspace,
        top=top,
    ).build()
