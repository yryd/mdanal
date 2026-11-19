"""离线派生：从已有表重算 fit/rdc 并重绘，不读取轨迹。"""

from __future__ import annotations

import importlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import __version__
from .errors import MdanalError, ValidationError
from .plot.render import render
from .plot.settings import parse_plot
from .plot.snapshot import json_safe, load_snapshot, make_plot_context, read_tables
from .run.writers import column_kinds, sha256, write_tables

SCHEMA_VERSION = 1
CONFIG_KEYS = {"schema_version", "analyses"}
ANALYSIS_KEYS = {"derive", "figures"}
FORMATS = ("png", "svg", "pdf")
LANGS = ("zh", "en")


def _read_config(path: str | Path) -> dict[str, dict[str, Any]]:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ValidationError(f"派生配置不存在：{config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValidationError("派生配置必须是映射", where=str(config_path))
    unknown = set(raw) - CONFIG_KEYS
    if unknown:
        raise ValidationError(
            f"派生配置含未知顶层字段 {sorted(unknown)}；允许 {sorted(CONFIG_KEYS)}",
            where=str(config_path),
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(
            f"派生配置 schema_version 必须是 {SCHEMA_VERSION}",
            where=str(config_path),
        )
    analyses = raw.get("analyses") or {}
    if not isinstance(analyses, Mapping) or not analyses:
        raise ValidationError(
            "派生配置的 analyses 必须是非空映射", where=str(config_path)
        )
    result: dict[str, dict[str, Any]] = {}
    for directory, entry in analyses.items():
        if not isinstance(directory, str) or not directory:
            raise ValidationError("analyses 的键必须是非空目录名")
        if not isinstance(entry, Mapping):
            raise ValidationError(f"analyses.{directory} 必须是映射")
        unknown = set(entry) - ANALYSIS_KEYS
        if unknown:
            raise ValidationError(
                f"analyses.{directory} 含未知字段 {sorted(unknown)}；"
                f"允许 {sorted(ANALYSIS_KEYS)}",
                where=str(config_path),
            )
        derive = entry.get("derive")
        if not isinstance(derive, Mapping) or not derive:
            raise ValidationError(
                f"analyses.{directory}.derive 必须是非空映射",
                where=str(config_path),
            )
        figures_raw = entry.get("figures")
        figures: dict[str, Any] = {}
        if figures_raw is not None:
            if isinstance(figures_raw, (list, tuple)):
                for name in figures_raw:
                    if not isinstance(name, str) or not name:
                        raise ValidationError(
                            f"analyses.{directory}.figures 必须是 recipe 名字符串列表"
                        )
                    figures[name] = {"plot": {}}
            elif isinstance(figures_raw, Mapping):
                for name, spec in figures_raw.items():
                    if not isinstance(name, str) or not name:
                        raise ValidationError(
                            f"analyses.{directory}.figures 的键必须是 recipe 名"
                        )
                    if spec is None:
                        spec = {}
                    if not isinstance(spec, Mapping) or set(spec) - {"plot"}:
                        raise ValidationError(
                            f"analyses.{directory}.figures.{name} 只接受 plot 字段"
                        )
                    figures[name] = {
                        "plot": parse_plot(
                            spec.get("plot"),
                            f"analyses.{directory}.figures.{name}.plot",
                        )
                    }
            else:
                raise ValidationError(
                    f"analyses.{directory}.figures 必须是列表或映射"
                )
        result[directory] = {
            "derive": dict(derive),
            "figures": figures,
        }
    return result


def _discover(source: Path) -> list[str]:
    directories = sorted(
        path.parent.name for path in source.glob("*/plot.json") if path.parent.is_dir()
    )
    if not directories:
        raise ValidationError(
            f"{source} 中没有可派生的分析结果（缺少 */plot.json）"
        )
    return directories


def _validate_out(source: Path, out: Path, force: bool) -> None:
    if out == source or out.is_relative_to(source) or source.is_relative_to(out):
        raise ValidationError(
            f"派生输出目录 {out} 与源结果目录 {source} 重叠；请换独立目录"
        )
    if not out.exists():
        return
    if not out.is_dir():
        raise ValidationError(f"派生输出路径不是目录：{out}")
    if not any(out.iterdir()):
        return
    if not force:
        raise ValidationError(
            f"派生输出目录非空：{out}；加 --force 才会覆盖"
        )
    record = out / "derive.json"
    if not record.is_file():
        raise ValidationError(
            f"输出目录非空且不是本程序的派生结果：{out}；请换目录或先清空"
        )


def _derive_one(
    source: Path,
    target: Path,
    directory: str,
    config: Mapping[str, Any],
    *,
    lang: str | None,
    dpi: int | None,
    fmt: str,
) -> dict[str, Any]:
    analysis_dir = source / directory
    snapshot = load_snapshot(analysis_dir)
    module_name = snapshot["analysis"]["module"]
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValidationError(
            f"{directory} 的派生模块 {module_name} 不可用：{exc}"
        ) from exc
    derive_fn = getattr(module, "derive_tables", None)
    if not callable(derive_fn):
        raise ValidationError(
            f"{directory} 的插件没有声明离线派生入口 derive_tables"
        )
    plot_ctx = make_plot_context(
        snapshot,
        lang=lang,
        dpi=dpi,
        plot={},
    )
    tables = read_tables(snapshot, analysis_dir)
    base_tables = {name: frame.copy() for name, frame in tables.items()}
    try:
        derived = derive_fn(plot_ctx, base_tables, config["derive"])
    except (ValueError, MdanalError) as exc:
        raise ValidationError(f"{directory} 派生失败：{exc}") from exc
    if not isinstance(derived, Mapping):
        raise ValidationError(f"{directory} 的 derive_tables 必须返回表映射")
    tables.update({str(name): frame for name, frame in derived.items()})

    written = write_tables(target, tables)
    payload = json.loads(json.dumps(snapshot, ensure_ascii=False))
    payload["tables"] = {
        name: {
            "path": written[name].relative_to(target).as_posix(),
            "sha256": sha256(written[name]),
            "columns": column_kinds(frame),
        }
        for name, frame in tables.items()
    }
    payload["context"]["derive"] = json_safe(dict(config["derive"]))
    figures = dict(config.get("figures") or {})
    if not figures:
        figures = dict(payload["context"].get("figures") or {})
    if not figures:
        recipes = getattr(module, "FIGURES", None)
        if isinstance(recipes, Mapping) and recipes:
            preferred = "raw" if "raw" in recipes else next(iter(recipes))
            figures = {preferred: {"plot": {}}}
    payload["context"]["figures"] = json_safe(figures)

    figure_paths = render(
        module,
        plot_ctx,
        tables,
        target,
        fmt=fmt,
        settings=payload["context"]["defaults"].get("plot") or {},
        figures=figures,
        override_priority="figure",
    )
    (target / "plot.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "directory": directory,
        "source": str(analysis_dir),
        "derive": json_safe(dict(config["derive"])),
        "tables": sorted(tables),
        "figures": [path.relative_to(target).as_posix() for path in figure_paths],
    }


def run_derive(
    source: str | Path,
    out_dir: str | Path,
    *,
    config: str | Path,
    analyses: Sequence[str] = (),
    lang: str | None = None,
    dpi: int | None = None,
    fmt: str = "png",
    force: bool = False,
) -> Path:
    source = Path(source).expanduser().resolve()
    out = Path(out_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValidationError(f"--from 必须是 run 结果目录：{source}")
    if lang is not None and lang not in LANGS:
        raise ValidationError(f"派生语言只能是 zh/en，收到 {lang!r}")
    if dpi is not None and (not isinstance(dpi, int) or dpi <= 0):
        raise ValidationError(f"派生 dpi 必须是正整数，收到 {dpi!r}")
    if fmt not in FORMATS:
        raise ValidationError(f"派生格式只能是 {FORMATS}，收到 {fmt!r}")
    configs = _read_config(config)
    available = _discover(source)
    selected = list(analyses or configs)
    unknown = [name for name in selected if name not in available]
    if unknown:
        raise ValidationError(f"结果中没有分析目录 {unknown}；可用 {available}")
    unknown = [name for name in selected if name not in configs]
    if unknown:
        raise ValidationError(f"派生配置里没有分析目录 {unknown}；可用 {sorted(configs)}")
    _validate_out(source, out, force)

    temp = out.parent / f".{out.name}.tmp-{uuid.uuid4().hex}"
    temp.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    try:
        for directory in selected:
            records.append(
                _derive_one(
                    source,
                    temp / directory,
                    directory,
                    configs[directory],
                    lang=lang,
                    dpi=dpi,
                    fmt=fmt,
                )
            )
        files = [
            path.relative_to(temp).as_posix()
            for path in temp.rglob("*")
            if path.is_file()
        ]
        files.append("derive.json")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mdanal_version": __version__,
            "source": str(source),
            "config": str(Path(config).expanduser().resolve()),
            "analyses": records,
            "files": files,
            "status": "ok",
        }
        (temp / "derive.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if out.exists():
            shutil.rmtree(out)
        shutil.move(str(temp), str(out))
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return out
