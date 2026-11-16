"""从已有 run 结果重绘：只读 plot.json + CSV，不访问轨迹。"""

from __future__ import annotations

import importlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .. import __version__
from ..errors import MdanalError, ValidationError
from ..run.writers import sha256
from . import plotutil
from .annotations import parse as parse_annotations
from .render import render
from .settings import merge_plot, parse_plot
from .snapshot import (
    json_safe,
    load_snapshot,
    make_plot_context,
    read_tables,
    snapshot_defaults,
)

SCHEMA_VERSION = 1
DEFAULT_KEYS = {"lang", "dpi", "format", "show_run_info", "plot", "annotate"}
ANALYSIS_KEYS = {"plot", "annotate"}
FORMATS = ("png", "svg", "pdf")
LANGS = ("zh", "en")


def _read_config(path: str | Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if path is None:
        return {}, {}
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ValidationError(f"重绘配置不存在：{config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValidationError("重绘配置必须是映射", where=str(config_path))
    unknown = set(raw) - {"schema_version", "defaults", "analyses"}
    if unknown:
        raise ValidationError(
            f"重绘配置含未知顶层字段 {sorted(unknown)}", where=str(config_path)
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(
            f"重绘配置 schema_version 必须是 {SCHEMA_VERSION}",
            where=str(config_path),
        )
    defaults = raw.get("defaults") or {}
    analyses = raw.get("analyses") or {}
    if not isinstance(defaults, Mapping) or not isinstance(analyses, Mapping):
        raise ValidationError("defaults/analyses 必须是映射", where=str(config_path))

    parsed_defaults: dict[str, Any] = {}
    unknown = set(defaults) - DEFAULT_KEYS
    if unknown:
        raise ValidationError(
            f"defaults 含未知字段 {sorted(unknown)}；允许 {sorted(DEFAULT_KEYS)}",
            where=str(config_path),
        )
    if "lang" in defaults:
        if defaults["lang"] not in LANGS:
            raise ValidationError("defaults.lang 只能是 zh/en", where=str(config_path))
        parsed_defaults["lang"] = defaults["lang"]
    if "dpi" in defaults:
        if not isinstance(defaults["dpi"], int) or defaults["dpi"] <= 0:
            raise ValidationError("defaults.dpi 必须是正整数", where=str(config_path))
        parsed_defaults["dpi"] = defaults["dpi"]
    if "format" in defaults:
        if defaults["format"] not in FORMATS:
            raise ValidationError(
                f"defaults.format 只能是 {FORMATS}", where=str(config_path)
            )
        parsed_defaults["format"] = defaults["format"]
    if "show_run_info" in defaults:
        if not isinstance(defaults["show_run_info"], bool):
            raise ValidationError("defaults.show_run_info 必须是布尔值")
        parsed_defaults["show_run_info"] = defaults["show_run_info"]
    if "plot" in defaults:
        parsed_defaults["plot"] = parse_plot(defaults["plot"], "defaults.plot")
    if "annotate" in defaults:
        parsed_defaults["annotate"] = parse_annotations(
            defaults["annotate"], "defaults"
        )

    parsed_analyses: dict[str, Any] = {}
    for directory, entry in analyses.items():
        if not isinstance(entry, Mapping):
            raise ValidationError(f"analyses.{directory} 必须是映射")
        unknown = set(entry) - ANALYSIS_KEYS
        if unknown:
            raise ValidationError(
                f"analyses.{directory} 含未知字段 {sorted(unknown)}；允许 plot/annotate"
            )
        item: dict[str, Any] = {}
        if "plot" in entry:
            item["plot"] = parse_plot(entry["plot"], f"analyses.{directory}.plot")
        if "annotate" in entry:
            item["annotate"] = parse_annotations(
                entry["annotate"], f"analyses.{directory}"
            )
        parsed_analyses[str(directory)] = item
    return parsed_defaults, parsed_analyses


def _discover_analyses(source: Path) -> list[str]:
    directories = sorted(
        path.parent.name for path in source.glob("*/plot.json") if path.parent.is_dir()
    )
    if not directories:
        raise ValidationError(
            f"{source} 中没有可重绘的分析结果（缺少 */plot.json）；"
            "该结果未保存独立重绘信息，请重新 run"
        )
    return directories


def _safe_relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationError(f"重绘产物路径越界：{path}")
    return relative.as_posix()


def _validate_existing(out: Path) -> dict[str, Any]:
    record = out / "replot.json"
    if (out / "provenance.json").is_file():
        raise ValidationError(
            f"{out} 是 run 输出目录，不能作为 replot 的输出；请换一个独立目录"
        )
    if not record.is_file():
        raise ValidationError(
            f"输出目录非空且不是本程序的重绘结果：{out}；请换目录或加 --force"
        )
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"replot.json 无法读取：{record}（{exc}）") from exc
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"重绘记录版本不支持：{record}")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValidationError(f"重绘记录缺少 files：{record}")
    recorded = set()
    for name in files:
        relative = Path(str(name))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValidationError(f"重绘记录路径越界：{name}")
        recorded.add(relative.as_posix())
    actual = {
        path.relative_to(out).as_posix()
        for path in out.rglob("*")
        if path.is_file()
    }
    if actual != recorded:
        extra = sorted(actual - recorded)
        missing = sorted(recorded - actual)
        raise ValidationError(
            f"重绘目录含记录之外的文件或不完整（多 {extra}，少 {missing}）；拒绝覆盖"
        )
    return payload


def _merge_annotations(
    snapshot_annotations,
    config_defaults,
    config_item,
):
    if config_item is not None and "annotate" in config_item:
        return config_item["annotate"]
    if "annotate" in config_defaults:
        return config_defaults["annotate"]
    return snapshot_annotations


def run_replot(
    source: str | Path,
    out_dir: str | Path,
    *,
    analyses: Sequence[str] = (),
    config: str | Path | None = None,
    lang: str | None = None,
    dpi: int | None = None,
    fmt: str | None = None,
    annotate: bool | None = None,
    force: bool = False,
) -> Path:
    source = Path(source).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValidationError(f"--from 必须是 run 结果目录：{source}")
    if lang is not None and lang not in LANGS:
        raise ValidationError(f"--lang 只能是 zh/en，收到 {lang!r}")
    if dpi is not None and (not isinstance(dpi, int) or dpi <= 0):
        raise ValidationError(f"--dpi 必须是正整数，收到 {dpi!r}")
    if fmt is not None and fmt not in FORMATS:
        raise ValidationError(f"--format 只能是 {FORMATS}，收到 {fmt!r}")
    if out == source or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValidationError(
            f"重绘输出目录 {out} 与源结果目录 {source} 重叠；请换独立目录"
        )

    config_defaults, config_analyses = _read_config(config)
    available = _discover_analyses(source)
    requested = list(analyses or available)
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise ValidationError(
            f"结果中没有分析目录 {unknown}；可用 {available}"
        )
    for name in config_analyses:
        if name not in available:
            raise ValidationError(f"重绘配置里的分析目录不存在：{name}")

    if out.exists():
        if not out.is_dir():
            raise ValidationError(f"重绘输出路径不是目录：{out}")
        if any(out.iterdir()):
            _validate_existing(out)
            if not force:
                raise ValidationError(
                    f"重绘输出目录非空：{out}；加 --force 才会覆盖"
                )

    temp = out.parent / f".{out.name}.tmp-{uuid.uuid4().hex}"
    temp.mkdir(parents=True)
    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        for directory in requested:
            analysis_dir = source / directory
            snapshot = load_snapshot(analysis_dir)
            defaults = snapshot_defaults(snapshot)
            item_config = config_analyses.get(directory, {})
            plot = dict(defaults["plot"])
            plot = merge_plot(plot, config_defaults.get("plot", {}))
            plot = merge_plot(plot, item_config.get("plot", {}))

            chosen_lang = lang or config_defaults.get("lang") or defaults["lang"]
            chosen_dpi = dpi or config_defaults.get("dpi") or defaults["dpi"]
            chosen_fmt = fmt or config_defaults.get("format") or defaults["format"]
            show_run_info = (
                annotate
                if annotate is not None
                else config_defaults.get("show_run_info", defaults["show_run_info"])
            )
            annotations = _merge_annotations(
                snapshot["context"].get("annotations") or (),
                config_defaults,
                item_config,
            )

            module_name = snapshot["analysis"]["module"]
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                raise ValidationError(
                    f"{directory} 的绘图模块 {module_name} 不可用：{exc}"
                ) from exc
            current_hash = sha256(Path(module.__file__))
            if current_hash != snapshot["analysis"].get("implementation_sha256"):
                message = (
                    f"{directory} 的插件源码在生成快照后发生变化；"
                    "已按当前版本尝试重绘，结果不保证与原图一致"
                )
                warnings.append(message)

            plot_ctx = make_plot_context(
                snapshot,
                lang=chosen_lang,
                dpi=chosen_dpi,
                annotate=bool(show_run_info),
                annotations=annotations,
                plot=plot,
            )
            tables = read_tables(snapshot, analysis_dir)
            target = temp / directory
            figures = render(
                module,
                plot_ctx,
                tables,
                target,
                fmt=chosen_fmt,
                settings=plot,
            )
            warnings.extend(plot_ctx.warnings)
            records.append(
                {
                    "directory": directory,
                    "snapshot": {
                        "path": f"{directory}/plot.json",
                        "sha256": sha256(analysis_dir / "plot.json"),
                    },
                    "plugin_sha256": current_hash,
                    "plugin_changed": current_hash
                    != snapshot["analysis"].get("implementation_sha256"),
                    "figures": [_safe_relative(path, temp) for path in figures],
                    "warnings": list(plot_ctx.warnings),
                    "lang": chosen_lang,
                    "dpi": chosen_dpi,
                    "format": chosen_fmt,
                    "show_run_info": bool(show_run_info),
                    "plot": json_safe(plot),
                    "annotations": json_safe(annotations),
                    "status": "ok",
                }
            )

        files = [
            path.relative_to(temp).as_posix()
            for path in temp.rglob("*")
            if path.is_file()
        ]
        files.append("replot.json")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mdanal_version": __version__,
            "source": str(source),
            "config": str(Path(config).expanduser().resolve()) if config else None,
            "analyses": records,
            "settings": {
                "lang": records[0]["lang"] if records else None,
                "dpi": records[0]["dpi"] if records else None,
                "format": records[0]["format"] if records else None,
                "show_run_info": records[0]["show_run_info"] if records else None,
            },
            "warnings": warnings,
            "files": files,
            "status": "ok",
        }
        (temp / "replot.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if out.exists():
            shutil.rmtree(out)
        temp.replace(out)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return out
