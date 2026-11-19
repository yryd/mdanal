"""绘图快照：把重绘所需的最小信息写入每条分析的 plot.json。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..errors import ValidationError
from ..run.writers import column_kinds, read_table, sha256
from .context import PLOT_API_VERSION, PlotContext
from .plotutil import Labels

SCHEMA_VERSION = 1


def json_safe(value: Any) -> Any:
    """转成标准 JSON；非有限数值转 null，拒绝运行对象和 DataFrame。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    raise ValidationError(
        f"绘图快照只接受 JSON 可序列化值，收到 {type(value).__name__}"
    )


def module_sha256(module: Any) -> str:
    path = Path(getattr(module, "__file__", "") or "")
    if not path.is_file():
        raise ValidationError(f"无法定位模块 {module!r} 的源文件")
    if path.name != "__init__.py":
        return sha256(path)
    # 包插件的源码不只 __init__.py；把包内 .py/.md 一起纳入指纹。
    digest = hashlib.sha256()
    files = sorted(list(path.parent.rglob("*.py")) + list(path.parent.rglob("*.md")))
    for item in files:
        digest.update(item.relative_to(path.parent).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


def build_snapshot(
    *,
    module: Any,
    item: Any,
    tables: Mapping[str, pd.DataFrame],
    table_paths: Mapping[str, Path],
    ctx: Any,
    meta: Mapping[str, Any],
    labels: Mapping[str, Mapping[str, str]],
    lang: str,
    dpi: int,
    annotate: bool,
    figure_sizes: Mapping[str, Sequence[float]],
    figures: Mapping[str, Any] | None = None,
    fmt: str = "png",
    target: Path,
) -> dict[str, Any]:
    table_payload: dict[str, Any] = {}
    for name, frame in tables.items():
        path = table_paths[name]
        table_payload[name] = {
            "path": path.relative_to(target).as_posix(),
            "sha256": sha256(path),
            "columns": column_kinds(frame),
        }

    plot = getattr(item, "plot", None) or {"window": dict(item.window)}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "analysis": {
            "name": item.name,
            "directory": item.directory,
            "module": item.definition.module,
            "plot_api_version": PLOT_API_VERSION,
            "implementation_sha256": module_sha256(module),
        },
        "tables": table_payload,
        "context": {
            "params": json_safe(dict(item.params)),
            "frames": {
                "start": int(ctx.start),
                "stop": int(ctx.stop),
                "frame_dt_ps": float(ctx.frame_dt_ps),
            },
            "selection_frame": int(ctx.selection_frame),
            "shift": [float(value) for value in ctx.system.view.shift],
            "labels": {
                key: {str(k): str(v) for k, v in value.items()}
                for key, value in labels.items()
            },
            "meta": json_safe(meta),
            "extras": json_safe(dict(ctx.extras)),
            "annotations": json_safe(list(item.annotations)),
            "figures": json_safe(
                dict(
                    figures
                    if figures is not None
                    else (getattr(item, "figures", {}) or {})
                )
            ),
            "derive": json_safe(dict(getattr(item, "derive", {}) or {})),
            "defaults": {
                "lang": str(lang),
                "dpi": int(dpi),
                "format": str(fmt),
                "show_run_info": bool(annotate),
                "figure_sizes": {
                    key: [float(v) for v in size]
                    for key, size in figure_sizes.items()
                },
                "plot": json_safe(dict(plot)),
            },
        },
    }
    return payload


def write_snapshot(directory: Path, payload: Mapping[str, Any]) -> Path:
    path = directory / "plot.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_snapshot(directory: Path) -> dict[str, Any]:
    path = directory / "plot.json"
    if not path.is_file():
        raise ValidationError(
            f"该结果未保存独立重绘信息：{path} 不存在；请重新 run 生成新结果"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"绘图快照无法读取：{path}（{exc}）") from exc
    validate_snapshot(payload, directory)
    return payload


def validate_snapshot(payload: Mapping[str, Any], directory: Path) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(
            f"不支持的绘图快照版本 {payload.get('schema_version')!r}；"
            f"当前只支持 {SCHEMA_VERSION}"
        )
    analysis = payload.get("analysis")
    context = payload.get("context")
    tables = payload.get("tables")
    if not isinstance(analysis, Mapping) or not isinstance(context, Mapping):
        raise ValidationError("绘图快照缺 analysis/context")
    if analysis.get("plot_api_version") != PLOT_API_VERSION:
        raise ValidationError(
            f"绘图接口版本 {analysis.get('plot_api_version')!r} 不受当前渲染器支持"
        )
    if not isinstance(tables, Mapping) or not tables:
        raise ValidationError("绘图快照没有数据表")
    labels = context.get("labels")
    if not isinstance(labels, Mapping) or not {"zh", "en"} <= set(labels):
        raise ValidationError("绘图快照缺少完整的中英文标签")
    defaults = context.get("defaults")
    if not isinstance(defaults, Mapping):
        raise ValidationError("绘图快照缺少 defaults")
    for key in ("lang", "dpi", "format", "show_run_info", "figure_sizes", "plot"):
        if key not in defaults:
            raise ValidationError(f"绘图快照 defaults 缺字段 {key!r}")

    root = Path(directory).resolve()
    for name, entry in tables.items():
        if not isinstance(entry, Mapping):
            raise ValidationError(f"绘图快照表 {name!r} 结构错误")
        relative = Path(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(f"绘图快照表 {name!r} 路径越界：{relative}")
        path = (root / relative).resolve()
        if root not in path.parents and path != root:
            raise ValidationError(f"绘图快照表 {name!r} 指向结果目录之外")
        if not path.is_file():
            raise ValidationError(f"绘图快照引用的表不存在：{path}")
        if sha256(path) != entry.get("sha256"):
            raise ValidationError(
                f"表 {path} 与绘图快照记录的哈希不一致；拒绝用旧快照重绘"
            )
        columns = entry.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ValidationError(f"绘图快照表 {name!r} 缺少列信息")


def read_tables(payload: Mapping[str, Any], directory: Path) -> dict[str, pd.DataFrame]:
    root = Path(directory)
    result: dict[str, pd.DataFrame] = {}
    for name, entry in payload["tables"].items():
        result[str(name)] = read_table(root / entry["path"], entry["columns"])
    return result


def snapshot_defaults(payload: Mapping[str, Any]) -> dict[str, Any]:
    defaults = payload["context"]["defaults"]
    return {
        "lang": str(defaults["lang"]),
        "dpi": int(defaults["dpi"]),
        "format": str(defaults["format"]),
        "show_run_info": bool(defaults["show_run_info"]),
        "figure_sizes": {
            key: tuple(float(v) for v in size)
            for key, size in defaults["figure_sizes"].items()
        },
        "plot": dict(defaults.get("plot") or {}),
    }


def make_plot_context(
    payload: Mapping[str, Any],
    *,
    lang: str | None = None,
    dpi: int | None = None,
    annotate: bool | None = None,
    annotations: Sequence[Mapping[str, Any]] | None = None,
    plot: Mapping[str, Any] | None = None,
    figure_sizes: Mapping[str, Sequence[float]] | None = None,
) -> PlotContext:
    defaults = snapshot_defaults(payload)
    context = payload["context"]
    chosen_lang = lang or defaults["lang"]
    labels = context["labels"].get(chosen_lang)
    if labels is None:
        raise ValidationError(f"绘图快照缺少语言 {chosen_lang!r} 的标签")
    plot_settings = dict(defaults["plot"])
    if plot:
        for key, value in plot.items():
            if key in ("window", "rc") and isinstance(value, Mapping):
                merged = dict(plot_settings.get(key) or {})
                merged.update(value)
                plot_settings[key] = merged
            else:
                plot_settings[key] = value
    windows = {
        str(axis): (float(bounds[0]), float(bounds[1]))
        for axis, bounds in (plot_settings.get("window") or {}).items()
    }
    size = plot_settings.get("size")
    size_override = (
        (float(size[0]), float(size[1])) if size is not None else None
    )
    sizes = figure_sizes or defaults["figure_sizes"]
    frames = context["frames"]
    return PlotContext(
        params=dict(context.get("params") or {}),
        meta=dict(context.get("meta") or {}),
        extras=dict(context.get("extras") or {}),
        start=int(frames["start"]),
        stop=int(frames["stop"]),
        frame_dt_ps=float(frames["frame_dt_ps"]),
        selection_frame=int(context.get("selection_frame", 0)),
        shift=tuple(float(v) for v in context.get("shift", (0.0, 0.0, 0.0))),
        lang=chosen_lang,
        dpi=int(dpi if dpi is not None else defaults["dpi"]),
        annotate=bool(
            annotate if annotate is not None else defaults["show_run_info"]
        ),
        annotations=tuple(
            annotations
            if annotations is not None
            else context.get("annotations") or ()
        ),
        labels=Labels(labels),
        figure_sizes={
            key: (float(size[0]), float(size[1])) for key, size in sizes.items()
        },
        windows=windows,
        size_override=size_override,
    )
