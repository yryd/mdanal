"""绘图公共层：样式、画布、色标、标注、保存与标签。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

STYLE = ("science", "no-latex", "retro")
CJK_FONT = "Noto Serif CJK SC"

# 密度用白→深蓝的顺序色标
_DENSITY_COLORS = ["#ffffff", "#dcecf7", "#9ec9e4", "#4a90c2", "#1d5b8f", "#0b2d5c"]

_styled = False


def apply_style() -> None:
    """注册 SciencePlots 样式与中文字体。可重复调用。"""
    global _styled
    if _styled:
        return

    import scienceplots  # noqa: F401  仅用于注册样式

    plt.style.use(list(STYLE))
    # 中文字体必须直接作为 font.family；放进 font.serif 靠回退会渲染成方块
    matplotlib.rcParams["font.family"] = [CJK_FONT]
    matplotlib.rcParams["axes.unicode_minus"] = False
    _styled = True


def figure(size: tuple[float, float]) -> tuple[Figure, Any]:
    return plt.subplots(figsize=size)


def save(fig: Figure, path: str | Path, dpi: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def colorbar(fig: Figure, ax, mappable, label: str):
    bar = fig.colorbar(mappable, ax=ax, pad=0.02)
    bar.set_label(label)
    return bar


def annotate(ax, text: str) -> None:
    ax.text(
        0.015,
        0.985,
        text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=6,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white",
              "edgecolor": "0.7", "alpha": 0.85},
    )


def density_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("mdanal_density", _DENSITY_COLORS)


class Labels:
    """标签解析：分析级（analyses.yaml）→ 全局（labels.yaml）→ 键名本身。"""

    def __init__(
        self,
        analysis: Mapping[str, str] | None = None,
        common: Mapping[str, str] | None = None,
    ):
        self._analysis = dict(analysis or {})
        self._common = dict(common or {})

    def __call__(self, key: str, **fmt: Any) -> str:
        text = self._analysis.get(key) or self._common.get(key) or key
        return text.format(**fmt) if fmt else text
