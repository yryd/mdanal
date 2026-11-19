"""从 figures/<name>.json + data 表重绘；不读轨迹，不重算。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from ..errors import ValidationError
from ..plot import chart, plotutil
from ..plot.figure import Figure
from .catalog import load_pack
from .model import PanelSource
from .plotting import apply_panel_plot, make_context, plot_style


@dataclass
class _Replay:
    params: dict[str, Any]
    extras: dict[str, Any]
    start: int
    stop: int
    frame_dt_ps: float
    selection_frame: int
    system: Any
    warnings: list[str]


def _tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    directory = data_dir / "tables"
    if not directory.is_dir():
        raise ValidationError(f"重绘缺少表目录：{directory}")
    return {
        path.stem: pd.read_csv(path, encoding="utf-8-sig")
        for path in sorted(directory.glob("*.csv"))
    }


def _source(data_dir: Path, label: str) -> tuple[PanelSource, _Replay]:
    context = json.loads((data_dir / "context.json").read_text(encoding="utf-8"))
    shift = tuple(float(x) for x in context.get("shift") or (0.0, 0.0, 0.0))
    replay = _Replay(
        params=dict(context.get("params") or {}),
        extras=dict(context.get("extras") or {}),
        start=int(context.get("start", 0)),
        stop=int(context.get("stop", 0)),
        frame_dt_ps=float(context.get("frame_dt_ps", 1.0)),
        selection_frame=int(context.get("selection_frame", 0)),
        system=SimpleNamespace(view=SimpleNamespace(shift=shift)),
        warnings=list(context.get("warnings") or []),
    )
    tables = _tables(data_dir)
    source = PanelSource(
        source=context.get("source", label),
        label=label,
        params=dict(replay.params),
        meta={},
        tables=tables,
        start=replay.start,
        stop=replay.stop,
        frame_dt_ps=replay.frame_dt_ps,
        selection_frame=replay.selection_frame,
        shift=shift,
    )
    return source, replay


def _build_item(root: Path, record: dict[str, Any], *, lang: str, dpi: int):
    pack = load_pack(str(record["pack"]))
    product = pack.products[str(record["product"])]
    plot = dict(record.get("plot") or {})
    if record["kind"] == "panel":
        source, replay = _source(root / record["data"], str(record.get("source", "")))
        ctx = make_context(pack, replay, plot, lang=lang, dpi=dpi)
        panel = product.build(ctx, source)
        apply_panel_plot(panel, plot, lang)
        return panel
    sources = []
    replay = None
    for entry in record.get("sources") or []:
        source, current = _source(root / entry["data"], str(entry["label"]))
        sources.append(source)
        replay = replay or current
    if replay is None:
        raise ValidationError("compare 快照没有 source")
    if product.compare is None:
        raise ValidationError(f"{record['pack']}/{record['product']} 不支持 compare")
    ctx = make_context(pack, replay, plot, lang=lang, dpi=dpi)
    panel = product.compare(ctx, sources)
    apply_panel_plot(panel, plot, lang)
    return panel


def _resolve_name(value: Any, lang: str) -> str | None:
    return plotutil.resolve_text(value, lang) if value is not None else None


def replot_from(from_dir: str | Path, out_dir: str | Path, *, name: str | None = None,
                lang: str = "zh", dpi: int = 300) -> list[Path]:
    root = Path(from_dir).expanduser().resolve()
    figures_dir = root / "figures"
    if not figures_dir.is_dir():
        raise ValidationError(f"{root} 没有 figures/，不是 figure-first 输出")
    selected = sorted(figures_dir.glob("*.json"))
    if name:
        selected = [path for path in selected if path.stem == name]
        if not selected:
            raise ValidationError(f"找不到图快照 {name!r}")
    out = Path(out_dir).expanduser().resolve()
    written: list[Path] = []
    for path in selected:
        payload = json.loads(path.read_text(encoding="utf-8"))
        panels = [
            _build_item(root, record, lang=lang, dpi=dpi)
            for record in payload.get("items") or []
        ]
        if not panels:
            continue
        style = (payload.get("items") or [{}])[0].get("plot") or {}
        with plot_style(style):
            fig = Figure(
                panels,
                ncols=int(payload.get("ncols", 1)),
                title=_resolve_name(payload.get("title"), lang),
            ).build()
        target = out / "figures" / f"{path.stem}.png"
        chart.save(fig, target, dpi)
        written.append(target)
    return written
