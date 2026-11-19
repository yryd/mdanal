"""Figure-first 的校验、执行、组合与落盘。"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


from .. import __version__
from ..errors import MdanalError, ValidationError
from ..plot import chart, plotutil
from ..plot.figure import Figure
from ..run.writers import sha256, write_tables
from .catalog import discover_packs
from .config import FigureProject
from .model import CompareSpec, FigureSpec, PanelRef, PanelSource
from .plotting import apply_panel_plot, make_context, plot_style
from .runtime import ComputeContext, SourceRuntime, compute_context


@dataclass
class _Job:
    key: str
    data_dir: Path
    ctx: ComputeContext
    tables: dict[str, Any]
    pack: Any
    runtime: SourceRuntime


@dataclass
class _Result:
    figures: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _json_key(values: Mapping[str, Any]) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _job_key(ref: PanelRef | CompareSpec, source: str) -> str:
    return _json_key(
        {
            "source": source,
            "pack": ref.pack,
            "select": ref.select,
            "compute": ref.compute,
            "section": list(ref.section) if ref.section else None,
        }
    )


def _figure_payload(spec: FigureSpec, panels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "figure",
        "name": spec.name,
        "ncols": spec.ncols,
        "title": spec.title,
        "items": panels,
    }


def _validate_fields(pack, product, select, compute, derive, where: str) -> list[str]:
    problems: list[str] = []
    if set(select) != set(pack.slots):
        problems.append(
            f"{where} 的 select 必须正好是 {list(pack.slots)}，收到 {sorted(select)}"
        )
    unknown_compute = set(compute) - set(pack.params)
    if unknown_compute:
        problems.append(
            f"{where} 的 compute 含未知参数 {sorted(unknown_compute)}；"
            f"可用 {sorted(pack.params)}"
        )
    for key in product.requires_derive:
        if key not in derive:
            problems.append(f"{where} 需要 derive.{key}；收到 {sorted(derive)}")
    if derive and pack.validate_derive is not None:
        try:
            pack.validate_derive(dict(derive))
        except (TypeError, ValueError) as exc:
            problems.append(f"{where} 的 derive 无效：{exc}")
    return problems


def _validate_item(item, packs, sources) -> list[str]:
    problems: list[str] = []
    pack = packs.get(item.pack)
    if pack is None:
        return [f"未知图包 {item.pack!r}；可用 {sorted(packs)}"]
    product = pack.products.get(item.product)
    if product is None:
        return [
            f"{item.pack} 没有产品 {item.product!r}；可用 {sorted(pack.products)}"
        ]
    if isinstance(item, PanelRef):
        problems.extend(
            _validate_fields(
                pack,
                product,
                item.select,
                item.compute,
                item.derive,
                f"{item.pack}/{item.product}",
            )
        )
        if (
            item.pack == "hbond"
            and item.product == "hbond-type"
            and item.source in sources
            and sources[item.source].naming.empty
        ):
            problems.append(
                "hbond/hbond-type 需要 source 配置 naming（分子名/元素）"
            )
        if item.source not in sources:
            problems.append(f"panel 引用了不存在的 source {item.source!r}")
        return problems

    if product.kind != "curve" or product.compare is None:
        problems.append(
            f"{item.pack}/{item.product} 不是可 compare 的曲线产品；"
            "请改用多个 Panel 并排"
        )
    for entry in item.sources:
        if entry.source not in sources:
            problems.append(f"compare 引用了不存在的 source {entry.source!r}")
            continue
        problems.extend(
            _validate_fields(
                pack,
                product,
                entry.select or item.select,
                entry.compute or item.compute,
                entry.derive or item.derive,
                f"compare[{entry.label}]",
            )
        )
    return problems


def check_project(project: FigureProject, packs=None) -> list[str]:
    packs = packs or discover_packs()
    problems: list[str] = []
    for figure in project.figures:
        if figure.ncols < 1:
            problems.append(f"figure {figure.name!r} 的 ncols 必须是正整数")
        for item in figure.items:
            problems.extend(_validate_item(item, packs, project.sources))
    return problems


def _guard_out(out: Path, project: FigureProject, force: bool) -> None:
    inputs = []
    for cfg in project.sources.values():
        inputs.extend([cfg.yaml_path, cfg.topology, *cfg.all_trajectories])
    resolved = [Path(path).resolve() for path in inputs]
    if out.exists():
        for path in resolved:
            if path.is_relative_to(out):
                raise ValidationError(
                    f"输入文件 {path} 位于输出目录 {out} 内；拒绝清空"
                )
    if not out.exists():
        out.mkdir(parents=True)
        return
    if not any(out.iterdir()):
        return
    marker = out / "project.json"
    if not force:
        raise ValidationError(f"输出目录已存在：{out}；加 --force 才会覆盖")
    if not marker.is_file():
        raise ValidationError(
            f"输出目录非空且不是本程序的图结果：{out}；请换目录"
        )
    for path in out.rglob("*"):
        if path.is_symlink() and path.resolve() in resolved:
            raise ValidationError(f"输出目录中的 {path} 指向输入文件；拒绝清空")
    shutil.rmtree(out)
    out.mkdir(parents=True)


def _table_dir(out: Path, source: str, pack: str, key: str) -> Path:
    return out / "data" / source / pack / key


def _write_context(path: Path, ctx: ComputeContext) -> None:
    payload = {
        "source": ctx.source,
        "view": ctx.view,
        "start": ctx.start,
        "stop": ctx.stop,
        "frame_dt_ps": ctx.frame_dt_ps,
        "selection_frame": ctx.selection_frame,
        "shift": list(ctx.system.view.shift),
        "params": dict(ctx.params),
        "warnings": list(ctx.warnings),
        "extras": ctx.extras,
        "geometry": (
            ctx.geometry_window.to_dict() if ctx.geometry_window is not None else None
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _derive_tables(pack, ctx, base, spec, cache):
    if not spec:
        return base
    key = _json_key(
        {
            "source": ctx.source,
            "pack": pack.name,
            "params": dict(ctx.params),
            "start": ctx.start,
            "stop": ctx.stop,
            "derive": spec,
        }
    )
    if key in cache:
        return cache[key]
    if pack.derive is None:
        raise ValidationError(f"{pack.name} 不支持 derive")
    derived = pack.derive(ctx, base, spec)
    tables = {**base, **derived}
    cache[key] = tables
    return tables


def _build_source(
    project: FigureProject,
    pack,
    ref: PanelRef | CompareSpec,
    source: str,
    jobs: dict[str, _Job],
    out: Path,
) -> _Job:
    key = _job_key(ref, source)
    if key in jobs:
        return jobs[key]
    runtime = SourceRuntime(source, project.sources[source])
    ctx = compute_context(runtime, pack, ref)
    tables = dict(pack.compute(ctx))
    data_dir = _table_dir(out, source, pack.name, key)
    write_tables(data_dir, tables)
    _write_context(data_dir / "context.json", ctx)
    job = _Job(key, data_dir, ctx, tables, pack, runtime)
    jobs[key] = job
    return job


def _source_for(job: _Job, label: str | None = None) -> PanelSource:
    return PanelSource(
        source=job.ctx.source,
        label=label or job.ctx.source,
        params=dict(job.ctx.params),
        meta={},
        tables=job.tables,
        start=job.ctx.start,
        stop=job.ctx.stop,
        frame_dt_ps=job.ctx.frame_dt_ps,
        selection_frame=job.ctx.selection_frame,
        shift=tuple(job.ctx.system.view.shift),
    )


def _compare_ref(item: CompareSpec, entry) -> PanelRef:
    return PanelRef(
        source=entry.source,
        pack=item.pack,
        product=item.product,
        select=dict(entry.select or item.select),
        compute=dict(entry.compute or item.compute),
        derive=dict(entry.derive or item.derive),
        section=entry.section if entry.section is not None else item.section,
        plot=dict(item.plot),
    )


def _build_item(
    project: FigureProject,
    item,
    packs,
    jobs: dict[str, _Job],
    out: Path,
    *,
    lang: str,
    dpi: int,
    derive_cache: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    if isinstance(item, PanelRef):
        pack = packs[item.pack]
        job = _build_source(project, pack, item, item.source, jobs, out)
        tables = _derive_tables(pack, job.ctx, job.tables, item.derive, derive_cache)
        write_tables(job.data_dir, tables)
        missing = [name for name in pack.products[item.product].requires if name not in tables]
        if missing:
            raise ValidationError(
                f"{item.pack}/{item.product} 缺少表 {missing}；"
                "请检查 derive 配置和 pack.json"
            )
        source = _source_for(job)
        source = PanelSource(
            source=source.source,
            label=source.label,
            params=source.params,
            meta=source.meta,
            tables=tables,
            start=source.start,
            stop=source.stop,
            frame_dt_ps=source.frame_dt_ps,
            selection_frame=source.selection_frame,
            shift=source.shift,
        )
        ctx = make_context(
            pack, job.ctx, item.plot, lang=lang, dpi=dpi,
            annotate=project.annotate,
        )
        panel = pack.products[item.product].build(ctx, source)
        apply_panel_plot(panel, item.plot, lang)
        return panel, {
            "kind": "panel",
            "source": item.source,
            "pack": item.pack,
            "product": item.product,
            "plot": dict(item.plot),
            "data": str(job.data_dir.relative_to(out)),
            "tables": {
                name: {
                    "path": f"{job.data_dir.relative_to(out)}/tables/{name}.csv",
                    "sha256": sha256(job.data_dir / "tables" / f"{name}.csv"),
                }
                for name in pack.products[item.product].requires
            },
        }

    assert isinstance(item, CompareSpec)
    pack = packs[item.pack]
    product = pack.products[item.product]
    if product.kind != "curve" or product.compare is None:
        raise ValidationError(
            f"{item.pack}/{item.product} 不能 compare；请用多个 Panel 并排"
        )
    source_objs: list[PanelSource] = []
    records = []
    first_ref = _compare_ref(item, item.sources[0])
    for entry in item.sources:
        ref = _compare_ref(item, entry)
        job = _build_source(project, pack, ref, entry.source, jobs, out)
        tables = _derive_tables(pack, job.ctx, job.tables, ref.derive, derive_cache)
        write_tables(job.data_dir, tables)
        source_objs.append(_source_for(job, entry.label))
        records.append(
            {
                "source": entry.source,
                "label": entry.label,
                "data": str(job.data_dir.relative_to(out)),
            }
        )
    ctx = make_context(
        pack,
        jobs[_job_key(first_ref, first_ref.source)].ctx,
        item.plot,
        lang=lang,
        dpi=dpi,
        annotate=project.annotate,
    )
    panel = product.compare(ctx, source_objs)
    apply_panel_plot(panel, item.plot, lang)
    return panel, {
        "kind": "compare",
        "pack": item.pack,
        "product": item.product,
        "plot": dict(item.plot),
        "sources": records,
    }


def render_project(
    project: FigureProject, out_dir: str | Path, *, force: bool = False
) -> Path:
    packs = discover_packs()
    problems = check_project(project, packs)
    if problems:
        raise ValidationError("\n".join(problems), where=str(project.yaml_path))
    out = Path(out_dir).expanduser().resolve()
    _guard_out(out, project, force)
    # 先落标记：失败的 render 也留下“本程序生成”的凭据，--force 才能安全清理。
    (out / "project.json").write_text(
        json.dumps({"schema_version": 1, "name": project.name}, ensure_ascii=False),
        encoding="utf-8",
    )
    jobs: dict[str, _Job] = {}
    derive_cache: dict[str, Any] = {}
    rendered: list[Path] = []
    figure_records: list[dict[str, Any]] = []
    for spec in project.figures:
        panels = []
        panel_records = []
        for item in spec.items:
            panel, record = _build_item(
                project,
                item,
                packs,
                jobs,
                out,
                lang=project.lang,
                dpi=project.dpi,
                derive_cache=derive_cache,
            )
            panels.append(panel)
            panel_records.append(record)
        title = (
            plotutil.resolve_text(spec.title, project.lang)
            if spec.title is not None
            else None
        )
        style = next(
            (
                item.plot
                for item in spec.items
                if item.plot.get("palette") or item.plot.get("rc")
            ),
            spec.items[0].plot if spec.items else {},
        )
        with plot_style(style):
            fig = Figure(panels, ncols=spec.ncols, title=title).build()
        path = out / "figures" / f"{spec.name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        chart.save(fig, path, project.dpi)
        rendered.append(path)
        payload = _figure_payload(spec, panel_records)
        payload["figure"] = {
            "path": path.relative_to(out).as_posix(),
            "sha256": sha256(path),
        }
        (out / "figures" / f"{spec.name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        figure_records.append(payload)
    (out / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mdanal_version": __version__,
                "config": str(project.yaml_path),
                "name": project.name,
                "figures": figure_records,
                "sources": {
                    name: {
                        "topology": str(cfg.topology),
                        "trajectory": str(cfg.trajectory),
                        "frames": list(cfg.frames) if cfg.frames else None,
                    }
                    for name, cfg in project.sources.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out
