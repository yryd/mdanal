"""公共绘图层：纯数据 → 图，不依赖运行上下文。

分析模块经 `plotutil` 适配层调用这里；用户也可以直接 `from mdanal import chart`，
把自己的数据画成与程序内一致的图。本模块不读轨迹、不认识 `ctx`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from .errors import MdanalError  # noqa: E402

STYLE = ("science", "no-latex", "retro")
CJK_FONT = "Noto Serif CJK SC"

# 标准画布（英寸）
SIZES: dict[str, tuple[float, float]] = {
    "single": (3.5, 2.6),
    "wide": (7.0, 3.2),
    "map": (4.2, 3.0),
}

# 程序统一色板：主色用于数据，次色用于对照，其余用于参考线
COLORS: dict[str, str] = {
    "primary": "#4165c0",
    "secondary": "#c05040",
    "reference": "0.5",
    "guide": "0.45",
    "label": "0.35",
}

# 密度用白→深蓝的顺序色标
_DENSITY_COLORS = ["#ffffff", "#dcecf7", "#9ec9e4", "#4a90c2", "#1d5b8f", "#0b2d5c"]

_styled = False


# --------------------------------------------------------------------------- #
# 底座：样式、画布、保存
# --------------------------------------------------------------------------- #


def apply_style() -> None:
    """注册 SciencePlots 样式与中文字体；字体缺失直接报错。可重复调用。"""
    global _styled
    if _styled:
        return

    import scienceplots  # noqa: F401  仅用于注册样式

    plt.style.use(list(STYLE))
    # 中文字体必须直接作为 font.family；放进 font.serif 靠回退会渲染成方块
    matplotlib.rcParams["font.family"] = [CJK_FONT]
    matplotlib.rcParams["axes.unicode_minus"] = False

    missing = missing_fonts()
    if missing:
        raise MdanalError(
            f"缺少字体 {missing}；图中文字会渲染成方块。请安装该字体，"
            f"或改 chart.CJK_FONT 指向本机已有的中文字体"
        )
    _styled = True


def missing_fonts(names: Sequence[str] = (CJK_FONT,)) -> list[str]:
    """返回本机找不到的字体名；matplotlib 渲染时只 warning，故这里显式校验。"""
    from matplotlib import font_manager

    missing: list[str] = []
    for name in names:
        try:
            font_manager.findfont(name, fallback_to_default=False)
        except ValueError:
            missing.append(name)
    return missing


def figure(size: str | tuple[float, float] = "single") -> tuple[Figure, Any]:
    """建一张图；size 取档位名（single/wide/map）或 (宽, 高)。"""
    if not _styled:
        apply_style()
    if isinstance(size, str):
        size = SIZES[size]
    return plt.subplots(figsize=size)


def save(fig: Figure, path: str | Path, dpi: int = 300) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def density_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("mdanal_density", _DENSITY_COLORS)


# --------------------------------------------------------------------------- #
# 语汇：曲线、条形、场、参考线、标注
# --------------------------------------------------------------------------- #


def line(
    ax,
    x,
    y,
    *,
    label: str | None = None,
    color: str | None = None,
    lw: float = 1.2,
    ls: str = "-",
    marker: str | None = None,
    ms: float | None = None,
    **kwargs: Any,
):
    """一条折线。颜色缺省时交给 matplotlib 的循环色，便于多曲线自动区分。"""
    options: dict[str, Any] = {"lw": lw, "ls": ls}
    if label is not None:
        options["label"] = label
    if color is not None:
        options["color"] = color
    if marker is not None:
        options["marker"] = marker
    if ms is not None:
        options["ms"] = ms
    options.update(kwargs)
    return ax.plot(x, y, **options)


def bars(
    ax,
    labels: Sequence[str],
    values: Sequence[float],
    *,
    notes: Sequence[str] | None = None,
    height: float = 0.7,
    color: str | None = None,
    note_fontsize: float = 6,
    headroom: float = 1.35,
):
    """横向条形图：位置 0..n-1，值在 x 轴，标签在 y 轴。"""
    values = np.asarray(values, dtype=float)
    positions = np.arange(len(labels))
    drawn = ax.barh(positions, values, height=height, color=color or COLORS["primary"])
    ax.set_yticks(positions, list(labels))
    ax.invert_yaxis()
    if notes is not None:
        ax.bar_label(drawn, labels=list(notes), padding=2, fontsize=note_fontsize)
    ax.set_xlim(0, float(values.max()) * headroom if values.size else 1.0)
    return drawn


def heatmap(ax, x, y, values, *, cmap=None, shading: str = "auto"):
    """平面场（pcolormesh）；x、y 为格心。"""
    return ax.pcolormesh(x, y, values, shading=shading, cmap=cmap or density_cmap())


def colorbar(fig: Figure, ax, mappable, label: str):
    bar = fig.colorbar(mappable, ax=ax, pad=0.02)
    bar.set_label(label)
    return bar


def refline(
    ax,
    y: float,
    *,
    ls: str = "--",
    lw: float = 0.6,
    color: str | None = None,
    label: str | None = None,
):
    """水平参考线。"""
    return ax.axhline(y, ls=ls, lw=lw, color=color or COLORS["reference"], label=label)


def vline(
    ax,
    x: float,
    *,
    ls: str = ":",
    lw: float = 0.8,
    color: str | None = None,
    label: str | None = None,
):
    """竖直参考线。"""
    return ax.axvline(x, ls=ls, lw=lw, color=color or COLORS["guide"], label=label)


def span(
    ax,
    low: float,
    high: float,
    *,
    axis: str = "y",
    color: str | None = None,
    alpha: float = 0.12,
):
    """区间阴影。"""
    color = color or COLORS["primary"]
    if axis == "y":
        return ax.axhspan(low, high, color=color, alpha=alpha, lw=0)
    if axis == "x":
        return ax.axvspan(low, high, color=color, alpha=alpha, lw=0)
    raise MdanalError(f"span 的 axis 只能是 x 或 y，收到 {axis!r}")


def note(
    ax,
    text: str,
    *,
    at: tuple[float, float] = (0.015, 0.985),
    fontsize: float = 6,
):
    """左上角的说明框（图内标注，坐标按轴比例）。"""
    ax.text(
        at[0],
        at[1],
        text,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=fontsize,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white",
              "edgecolor": "0.7", "alpha": 0.85},
    )


def text(
    ax,
    x: float,
    y: float,
    label: str,
    *,
    fontsize: float = 6,
    color: str | None = None,
    ha: str = "left",
    va: str = "bottom",
):
    """数据坐标下的一行文字。"""
    return ax.text(
        x, y, label, fontsize=fontsize, color=color or COLORS["label"], ha=ha, va=va
    )


def point_label(
    ax,
    x: float,
    y: float,
    label: str,
    *,
    offset: tuple[float, float] = (3, 0),
    fontsize: float = 6,
    color: str | None = None,
):
    """数据点旁的偏移文字（像素偏移）。"""
    return ax.annotate(
        label,
        xy=(x, y),
        xytext=offset,
        textcoords="offset points",
        fontsize=fontsize,
        color=color or COLORS["label"],
    )


def legend(ax, **kwargs: Any):
    options = {"loc": "upper right", "fontsize": 6, "frameon": False}
    options.update(kwargs)
    return ax.legend(**options)

