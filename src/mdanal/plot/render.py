"""统一绘图入口：插件 figures → 呈现覆盖 → 保存/关闭。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import matplotlib
from cycler import cycler

from . import chart, plotutil
from ..errors import MdanalError, ValidationError

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or not SAFE_NAME.match(name):
        raise ValidationError(
            f"图名必须是安全文件名（字母、数字、_ . -），收到 {name!r}"
        )
    if name in (".", "..") or name != Path(name).name:
        raise ValidationError(f"图名不能包含路径：{name!r}")
    return name


def _data_axes(fig):
    return [axis for axis in fig.axes if axis.get_label() != "<colorbar>"]


def _apply_settings(fig, settings: Mapping[str, Any], lang: str) -> None:
    title = settings.get("title")
    xlabel = settings.get("xlabel")
    ylabel = settings.get("ylabel")
    for axis in _data_axes(fig):
        if title is not None:
            axis.set_title(plotutil.resolve_text(title, lang))
        if xlabel is not None:
            axis.set_xlabel(plotutil.resolve_text(xlabel, lang))
        if ylabel is not None:
            axis.set_ylabel(plotutil.resolve_text(ylabel, lang))
        for key in ("xlim", "ylim"):
            bounds = settings.get(key)
            if bounds is not None:
                getattr(axis, f"set_{key[0]}lim")(bounds[0], bounds[1])


def render(
    module: Any,
    ctx,
    tables: Mapping[str, Any],
    target: Path,
    *,
    fmt: str = "png",
    settings: Mapping[str, Any] | None = None,
) -> list[Path]:
    """调用 figures、施加呈现覆盖，并把每张图保存到 target/figures。"""
    if fmt not in ("png", "svg", "pdf"):
        raise ValidationError(f"图件格式只能是 png/svg/pdf，收到 {fmt!r}")
    if not hasattr(module, "figures"):
        return []
    plotutil.apply_style()
    settings = dict(settings or {})
    rc = dict(settings.get("rc") or {})
    if settings.get("palette"):
        rc["axes.prop_cycle"] = cycler(color=list(settings["palette"]))
    with matplotlib.rc_context(rc):
        try:
            produced = module.figures(ctx, dict(tables)) or []
        except MdanalError:
            raise
        except Exception as exc:
            raise MdanalError(f"绘图失败：{exc}") from exc

        if not isinstance(produced, (list, tuple)):
            raise ValidationError("figures() 必须返回 (名称, Figure) 列表")
        names = [name for name, _ in produced]
        if len(set(names)) != len(names):
            raise ValidationError(f"figures() 产生了重名图 {names}")
        paths: list[Path] = []
        for name, fig in produced:
            name = _safe_name(name)
            _apply_settings(fig, settings, ctx.lang)
            path = target / "figures" / f"{name}.{fmt}"
            path.parent.mkdir(parents=True, exist_ok=True)
            chart.save(fig, path, ctx.dpi)
            paths.append(path)
        return paths
