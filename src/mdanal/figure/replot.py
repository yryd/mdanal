"""从 figures/<name>.json + 精确表清单重绘；不读轨迹，不重算。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pandas as pd

from ..errors import ValidationError
from ..plot import chart, plotutil
from ..plot.figure import Figure
from ..run.writers import sha256
from .catalog import load_pack
from .model import PanelSource
from .overrides import PlotOverrides
from .plotting import apply_panel_plot, make_context, plot_style, select_style


@dataclass
class _Replay:
    params: dict[str, Any]
    extras: dict[str, Any]
    start: int
    stop: int
    frame_dt_ps: float
    selection_frame: int
    shift: tuple[float, float, float]
    warnings: list[str]


def _load_tables(root: Path, records: Mapping[str, Any]) -> dict[str, pd.DataFrame]:
    if not records:
        raise ValidationError("图快照没有表清单；请用当前版本重新生成")
    result: dict[str, pd.DataFrame] = {}
    for name, record in records.items():
        path = root / str(record["path"])
        if not path.is_file():
            raise ValidationError(f"重绘缺少表 {name}：{path}")
        expected = str(record.get("sha256") or "")
        actual = sha256(path)
        if expected and actual != expected:
            raise ValidationError(
                f"表 {name} 已变化（快照 {expected[:12]}…，现为 {actual[:12]}…）：{path}"
            )
        result[str(name)] = pd.read_csv(path, encoding="utf-8-sig")
    return result


def _source(root: Path, record: Mapping[str, Any], label: str) -> tuple[PanelSource, _Replay]:
    base = root / str(record.get("base") or "")
    context_path = base / "context.json"
    if not context_path.is_file():
        raise ValidationError(f"重绘缺少计算上下文：{context_path}")
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"计算上下文损坏：{context_path}") from exc
    shift = tuple(float(x) for x in context.get("shift") or (0.0, 0.0, 0.0))
    request = record.get("request") or {}
    params = dict(request.get("compute") or context.get("params") or {})
    replay = _Replay(
        params=params,
        extras=dict(context.get("extras") or {}),
        start=int(context.get("start", 0)),
        stop=int(context.get("stop", 0)),
        frame_dt_ps=float(context.get("frame_dt_ps", 1.0)),
        selection_frame=int(context.get("selection_frame", 0)),
        shift=shift,
        warnings=list(context.get("warnings") or []),
    )
    tables = _load_tables(root, record.get("tables") or {})
    source = PanelSource(
        source=str(record.get("source") or label),
        label=label,
        params=params,
        meta={"extras": replay.extras, "warnings": replay.warnings},
        tables=tables,
        start=replay.start,
        stop=replay.stop,
        frame_dt_ps=replay.frame_dt_ps,
        selection_frame=replay.selection_frame,
        shift=shift,
    )
    return source, replay


def _build_item(
    root: Path,
    record: Mapping[str, Any],
    *,
    lang: str,
    dpi: int,
    annotate: bool,
):
    pack = load_pack(str(record["pack"]))
    product = pack.products[str(record["product"])]
    plot = dict(record.get("plot") or {})
    if record["kind"] == "panel":
        source, replay = _source(root, record, str(record.get("source", "")))
        ctx = make_context(
            pack, replay, plot, lang=lang, dpi=dpi, annotate=annotate
        )
        panel = product.build(ctx, source)
        apply_panel_plot(panel, plot, lang)
        return panel
    sources = []
    replay = None
    for entry in record.get("sources") or []:
        source, current = _source(root, entry, str(entry.get("label", "")))
        sources.append(source)
        replay = replay or current
    if replay is None:
        raise ValidationError("compare 快照没有 source")
    if product.compare is None:
        raise ValidationError(f"{record['pack']}/{record['product']} 不支持 compare")
    ctx = make_context(
        pack, replay, plot, lang=lang, dpi=dpi, annotate=annotate
    )
    panel = product.compare(ctx, sources)
    apply_panel_plot(panel, plot, lang)
    return panel


def _record_style(records: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    items = [SimpleNamespace(plot=dict(record.get("plot") or {})) for record in records]
    return select_style(items)


def _resolve_name(value: Any, lang: str) -> str | None:
    return plotutil.resolve_text(value, lang) if value is not None else None


def replot_from(
    from_dir: str | Path,
    out_dir: str | Path,
    *,
    name: str | None = None,
    lang: str | None = None,
    dpi: int | None = None,
    force: bool = False,
    overrides: PlotOverrides | None = None,
) -> list[Path]:
    root = Path(from_dir).expanduser().resolve()
    figures_dir = root / "figures"
    if not figures_dir.is_dir():
        raise ValidationError(f"{root} 没有 figures/，不是 figure-first 输出")
    all_names = {path.stem for path in figures_dir.glob("*.json")}
    if overrides is not None:
        unknown = set(overrides.figures) - all_names
        if unknown:
            raise ValidationError(
                f"plot 覆盖配置引用了不存在的图：{sorted(unknown)}"
            )
    selected = sorted(figures_dir.glob("*.json"))
    if name:
        selected = [path for path in selected if path.stem == name]
        if not selected:
            raise ValidationError(f"找不到图快照 {name!r}")
    if not selected:
        raise ValidationError(f"{root} 没有可重绘的图快照")
    out = Path(out_dir).expanduser().resolve()
    if out == root:
        raise ValidationError("重绘输出目录不能等于输入结果目录")
    out.mkdir(parents=True, exist_ok=True)
    targets = {path: out / "figures" / f"{path.stem}.png" for path in selected}
    for target in targets.values():
        if target.exists() and not force:
            raise ValidationError(
                f"重绘目标已存在：{target}；加 --force 才会覆盖"
            )
    written: list[Path] = []
    for path in selected:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"图快照损坏：{path}") from exc
        records = list(payload.get("items") or [])
        if not records:
            raise ValidationError(f"图快照没有 Panel：{path}")
        override = overrides.figures.get(path.stem) if overrides else None
        if override is not None:
            if max(override.panels, default=-1) >= len(records):
                raise ValidationError(
                    f"{path.stem}: plot.panels 索引超出 {len(records)} 个 Panel"
                )
            records = [
                {
                    **record,
                    "plot": {
                        **dict(record.get("plot") or {}),
                        **dict(override.panels.get(index) or {}),
                    },
                }
                for index, record in enumerate(records)
            ]
        render = payload.get("render") or {}
        effective_lang = (
            lang
            or (override.lang if override and override.lang else None)
            or str(render.get("lang") or "zh")
        )
        effective_dpi = int(
            dpi
            or (override.dpi if override and override.dpi else None)
            or render.get("dpi")
            or 300
        )
        annotate = bool(
            override.annotate
            if override and override.annotate is not None
            else render.get("annotate", False)
        )
        panels = [
            _build_item(
                root,
                record,
                lang=effective_lang,
                dpi=effective_dpi,
                annotate=annotate,
            )
            for record in records
        ]
        style = (
            override.style
            if override and override.style
            else (render.get("style") or _record_style(records))
        )
        title_value = (
            override.title
            if override and override.title is not None
            else payload.get("title")
        )
        ncols = (
            override.ncols
            if override and override.ncols is not None
            else int(payload.get("ncols", 1))
        )
        with plot_style(style):
            fig = Figure(
                panels,
                ncols=int(ncols),
                title=_resolve_name(title_value, effective_lang),
            ).build()
        target = targets[path]
        chart.save(fig, target, effective_dpi)
        written.append(target)
    return written
