"""Figure-first 的校验、执行、组合与落盘。"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


from .. import __version__
from ..errors import MdanalError, ValidationError
from ..plot import chart, plotutil
from ..plot.figure import Figure
from ..run.writers import sha256, write_tables
from .catalog import load_pack
from .config import FigureProject
from .model import CompareSpec, FigureSpec, PanelRef, PanelSource, StackSpec
from .plotting import apply_panel_plot, make_context, plot_style, select_style
from .stack import stack_curves
from .runtime import ComputeContext, SourceRuntime, compute_context, normalize_compute


@dataclass
class _Job:
    key: str
    data_dir: Path
    ctx: ComputeContext
    tables: dict[str, Any]
    pack: Any
    runtime: SourceRuntime



def _json_key(values: Mapping[str, Any]) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _job_key(ref: PanelRef | CompareSpec, source: str, pack) -> str:
    return _json_key(
        {
            "source": source,
            "pack": ref.pack,
            "select": dict(ref.select),
            "compute": normalize_compute(pack, ref.compute),
            "section": list(ref.section) if ref.section else None,
        }
    )


def _derive_key(job_key: str, spec: Mapping[str, Any]) -> str:
    return _json_key({"base": job_key, "derive": dict(spec)})


def _display_path(path: Path, base: Path) -> str:
    """结果文件不写绝对路径；配置目录下能相对表示就相对表示。"""
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def _table_record(path: Path, root: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256(path),
    }


def _table_records(
    tables: dict[str, Any],
    job: _Job,
    derived: dict[str, Any],
    derive_dir: Path | None,
    out: Path,
) -> dict[str, dict[str, str]]:
    """记录实际传给视图的全部表；requires 只是最低计算需求。"""
    records: dict[str, dict[str, str]] = {}
    for name in tables:
        directory = derive_dir if name in derived and derive_dir is not None else job.data_dir
        path = directory / "tables" / f"{name}.csv"
        if path.is_file():
            records[str(name)] = _table_record(path, out)
    return records


def _figure_payload(spec: FigureSpec, panels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "figure",
        "name": spec.name,
        "ncols": spec.ncols,
        "title": spec.title,
        "items": panels,
    }


def _valid_param_value(spec: Mapping[str, Any], value: Any) -> bool:
    expected = spec.get("type")
    if expected is bool:
        if not isinstance(value, bool):
            return False
    elif expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            return False
    elif expected is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    elif expected is str:
        if not isinstance(value, str):
            return False
    elif expected is list:
        if not isinstance(value, (list, tuple)):
            return False
    elif isinstance(expected, tuple):
        if not isinstance(value, expected) or isinstance(value, bool):
            return False
    if "choices" in spec and value not in spec["choices"]:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if spec.get("min") is not None and float(value) < float(spec["min"]):
            return False
        if spec.get("max") is not None and float(value) > float(spec["max"]):
            return False
    return True


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
    for key, value in compute.items():
        if key in pack.params and not _valid_param_value(pack.params[key], value):
            problems.append(
                f"{where}.compute.{key}={value!r} 不合法；"
                f"应为 {pack.params[key].get('type')}，"
                f"choices={pack.params[key].get('choices')}"
            )
    if derive and pack.derive is None:
        problems.append(f"{where} 的图包不支持 derive，收到 {sorted(derive)}")
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

    is_stack = isinstance(item, StackSpec)
    if is_stack:
        if product.kind != "curve" or product.curve_request is None:
            problems.append(
                f"{item.pack}/{item.product} 不是可 stack 的曲线产品；"
                "请改用提供 curve_request 的曲线产品（例如 contact-count/contact-coordination）"
            )
    elif product.kind != "curve" or product.compare is None:
        problems.append(
            f"{item.pack}/{item.product} 不是可 compare 的曲线产品；"
            "请改用多个 Panel 并排"
        )
    for entry in item.sources:
        if entry.source not in sources:
            kind = "stack" if is_stack else "compare"
            problems.append(f"{kind} 引用了不存在的 source {entry.source!r}")
            continue
        problems.extend(
            _validate_fields(
                pack,
                product,
                entry.select or item.select,
                entry.compute or item.compute,
                entry.derive or item.derive,
                f"{'stack' if is_stack else 'compare'}[{entry.label}]",
            )
        )
    return problems


def _iter_source_refs(project: FigureProject):
    for figure in project.figures:
        for item in figure.items:
            if isinstance(item, PanelRef):
                yield item.source, item
            else:
                for entry in item.sources:
                    yield entry.source, _curve_ref(item, entry)


def check_warnings(project: FigureProject, packs=None) -> list[str]:
    """check 阶段不计算，但可提前报告输入几何与产品内核的明显冲突。"""
    packs = packs or load_requested_packs(project)[0]
    warnings: list[str] = []
    for source, ref in _iter_source_refs(project):
        cfg = project.sources.get(source)
        pack = packs.get(ref.pack)
        if cfg is None or pack is None or cfg.geometry is None:
            continue
        periodicity = str((pack.geometry or {}).get("periodicity") or "any").lower()
        base_start = cfg.frames[0] if cfg.frames else 0
        base_stop = cfg.frames[1] if cfg.frames else len(cfg.geometry)
        start = base_start + (ref.section[0] if ref.section else 0)
        stop = (
            base_start + ref.section[1]
            if ref.section
            else base_stop
        )
        try:
            window = cfg.geometry.window(start, stop)
        except Exception:
            continue
        pbc = tuple(bool(value) for value in window.pbc_all)
        incompatible = (
            (periodicity == "full" and not all(pbc))
            or (periodicity == "xy" and not (pbc[0] and pbc[1]))
            or window.pbc_changed
        )
        if incompatible:
            warnings.append(
                f"{source}/{ref.pack}/{ref.product}: 窗口 PBC={list(pbc)}，"
                f"kernel={pack.kernel_pbc!r}，periodicity={periodicity}；"
                "结果只作定性参考"
            )
    return warnings


def source_warnings(project: FigureProject) -> list[str]:
    warnings: list[str] = []
    for name, cfg in project.sources.items():
        for note in (*cfg.time_notes, *cfg.seam_notes):
            warnings.append(f"{name}: {note}")
        if cfg.input_state == "unknown":
            warnings.append(f"{name}: 无法从轨迹表头判断坐标是否包裹")
    return warnings


def requested_pack_names(project: FigureProject) -> list[str]:
    names = []
    for figure in project.figures:
        for item in figure.items:
            pack = item.pack
            if pack not in names:
                names.append(pack)
    return names


def load_requested_packs(project: FigureProject) -> tuple[dict, list[str]]:
    packs = {}
    problems = []
    for name in requested_pack_names(project):
        try:
            packs[name] = load_pack(name)
        except Exception as exc:
            problems.append(f"无法加载图包 {name!r}：{exc}")
    return packs, problems


def check_project(project: FigureProject, packs=None) -> list[str]:
    load_problems: list[str] = []
    if packs is None:
        packs, load_problems = load_requested_packs(project)
    problems: list[str] = list(load_problems)
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
        if cfg.naming.from_data is not None:
            inputs.append(cfg.naming.from_data)
    resolved = [Path(path).expanduser().resolve() for path in inputs]
    out = out.expanduser().resolve()
    if out.is_symlink():
        raise ValidationError(f"输出目录不能是符号链接：{out}")
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
        "selection": {
            slot: group.selection for slot, group in ctx.groups.items()
        },
        "section": [ctx.start, ctx.stop],
        "warnings": list(ctx.warnings),
        "time_notes": list(ctx.time_notes),
        "seam_notes": list(ctx.seam_notes),
        "geometry_meta": dict(ctx.geometry_meta),
        "requested_tables": sorted(ctx.requested_tables),
        "extras": ctx.extras,
        "geometry": (
            ctx.geometry_window.to_dict() if ctx.geometry_window is not None else None
        ),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _derive_tables(pack, job: _Job, spec: Mapping[str, Any], cache: dict[str, Any]):
    """返回 (派生表, 派生目录, 派生 key)；基础表永不在这里改写。"""
    if not spec:
        return {}, None, ""
    key = _derive_key(job.key, spec)
    cache_key = f"{job.key}:{key}"
    if cache_key in cache:
        derived, directory = cache[cache_key]
        return dict(derived), directory, key
    if pack.derive is None:
        raise ValidationError(f"{pack.name} 不支持 derive")
    derived = dict(pack.derive(job.ctx, job.tables, dict(spec)))
    directory = job.data_dir / "derive" / key
    write_tables(directory, derived)
    (directory / "derive.json").write_text(
        json.dumps(
            {
                "base": job.key,
                "derive_key": key,
                "spec": dict(spec),
                "tables": {
                    name: _table_record(directory / "tables" / f"{name}.csv", directory)
                    for name in derived
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    cache[cache_key] = (derived, directory)
    return derived, directory, key


def _build_source(
    project: FigureProject,
    pack,
    ref: PanelRef | CompareSpec,
    source: str,
    jobs: dict[str, _Job],
    out: Path,
    requested_tables: frozenset[str] | None = None,
) -> _Job:
    key = _job_key(ref, source, pack)
    if key in jobs:
        return jobs[key]
    runtime = SourceRuntime(source, project.sources[source])
    ctx = compute_context(runtime, pack, ref, requested_tables=requested_tables)
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
        meta={
            "extras": dict(job.ctx.extras),
            "warnings": list(job.ctx.warnings),
            "geometry_meta": dict(job.ctx.geometry_meta),
            "time_notes": list(job.ctx.time_notes),
            "seam_notes": list(job.ctx.seam_notes),
        },
        tables=job.tables,
        start=job.ctx.start,
        stop=job.ctx.stop,
        frame_dt_ps=job.ctx.frame_dt_ps,
        selection_frame=job.ctx.selection_frame,
        shift=tuple(job.ctx.system.view.shift),
    )


def _curve_ref(item, entry) -> PanelRef:
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


def _plan_requests(project: FigureProject, packs):
    """先收集所有 job 的产品表需求，再按需求 compute；避免多请求时漏算。"""
    planned: dict[str, dict[str, Any]] = {}
    for figure in project.figures:
        for item in figure.items:
            if isinstance(item, PanelRef):
                pairs = [(item.source, item)]
            else:
                pairs = [
                    (entry.source, _curve_ref(item, entry))
                    for entry in item.sources
                ]
            for source, ref in pairs:
                pack = packs.get(ref.pack)
                if pack is None or ref.product not in pack.products:
                    continue
                key = _job_key(ref, source, pack)
                row = planned.setdefault(
                    key,
                    {"ref": ref, "source": source, "pack": pack, "tables": set()},
                )
                row["tables"].update(pack.products[ref.product].requires)
    return planned


def _build_curve_sources(
    project: FigureProject,
    item,
    packs,
    jobs: dict[str, _Job],
    out: Path,
    derive_cache: dict[str, Any],
):
    pack = packs[item.pack]
    product = pack.products[item.product]
    source_objs: list[PanelSource] = []
    records = []
    first_ref = _curve_ref(item, item.sources[0])
    for entry in item.sources:
        ref = _curve_ref(item, entry)
        job = _build_source(project, pack, ref, entry.source, jobs, out)
        derived, derive_dir, derive_key = _derive_tables(
            pack, job, ref.derive, derive_cache
        )
        tables = {**job.tables, **derived}
        source_obj = _source_for(job, entry.label)
        source_obj = PanelSource(
            source=source_obj.source,
            label=source_obj.label,
            params=source_obj.params,
            meta=source_obj.meta,
            tables=tables,
            start=source_obj.start,
            stop=source_obj.stop,
            frame_dt_ps=source_obj.frame_dt_ps,
            selection_frame=source_obj.selection_frame,
            shift=source_obj.shift,
        )
        source_objs.append(source_obj)
        table_records = _table_records(tables, job, derived, derive_dir, out)
        records.append(
            {
                "source": entry.source,
                "label": entry.label,
                "base": str(job.data_dir.relative_to(out)),
                "derive": str(derive_dir.relative_to(out)) if derive_dir else None,
                "derive_key": derive_key or None,
                "tables": table_records,
                "request": {
                    "select": dict(ref.select),
                    "compute": normalize_compute(pack, ref.compute),
                    "derive": dict(ref.derive),
                    "section": list(ref.section) if ref.section else None,
                },
            }
        )
    first_ctx = jobs[_job_key(first_ref, first_ref.source, pack)].ctx
    return source_objs, records, first_ctx


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
        derived, derive_dir, derive_key = _derive_tables(
            pack, job, item.derive, derive_cache
        )
        tables = {**job.tables, **derived}
        product = pack.products[item.product]
        missing = [name for name in product.requires if name not in tables]
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
        panel = product.build(ctx, source)
        apply_panel_plot(panel, item.plot, lang)
        table_records = _table_records(tables, job, derived, derive_dir, out)
        return panel, {
            "kind": "panel",
            "source": item.source,
            "pack": item.pack,
            "product": item.product,
            "plot": dict(item.plot),
            "base": str(job.data_dir.relative_to(out)),
            "derive": str(derive_dir.relative_to(out)) if derive_dir else None,
            "derive_key": derive_key or None,
            "tables": table_records,
            "request": {
                "select": dict(item.select),
                "compute": normalize_compute(pack, item.compute),
                "derive": dict(item.derive),
                "section": list(item.section) if item.section else None,
            },
        }

    if isinstance(item, StackSpec):
        pack = packs[item.pack]
        product = pack.products[item.product]
        if product.kind != "curve" or product.curve_request is None:
            raise ValidationError(
                f"{item.pack}/{item.product} 不能 stack；请使用提供 curve_request 的曲线产品"
            )
        source_objs, records, first_ctx = _build_curve_sources(
            project, item, packs, jobs, out, derive_cache
        )
        ctx = make_context(
            pack,
            first_ctx,
            item.plot,
            lang=lang,
            dpi=dpi,
            annotate=project.annotate,
        )
        panel = stack_curves(ctx, source_objs, product.curve_request)
        apply_panel_plot(panel, item.plot, lang)
        return panel, {
            "kind": "stack",
            "pack": item.pack,
            "product": item.product,
            "plot": dict(item.plot),
            "sources": records,
        }

    assert isinstance(item, CompareSpec)
    pack = packs[item.pack]
    product = pack.products[item.product]
    if product.kind != "curve" or product.compare is None:
        raise ValidationError(
            f"{item.pack}/{item.product} 不能 compare；请用多个 Panel 并排"
        )
    source_objs, records, first_ctx = _build_curve_sources(
        project, item, packs, jobs, out, derive_cache
    )
    ctx = make_context(
        pack,
        first_ctx,
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
    packs, load_problems = load_requested_packs(project)
    problems = list(load_problems)
    problems.extend(check_project(project, packs))
    if problems:
        raise ValidationError("\n".join(problems), where=str(project.yaml_path))
    raw_out = Path(out_dir).expanduser()
    if raw_out.is_symlink():
        raise ValidationError(f"输出目录不能是符号链接：{raw_out}")
    out = raw_out.resolve()
    _guard_out(out, project, force)
    # 先落标记：失败的 render 也留下“本程序生成”的凭据，--force 才能安全清理。
    (out / "project.json").write_text(
        json.dumps({"schema_version": 1, "name": project.name}, ensure_ascii=False),
        encoding="utf-8",
    )
    jobs: dict[str, _Job] = {}
    derive_cache: dict[str, Any] = {}
    rendered: list[Path] = []
    warnings: list[str] = list(source_warnings(project))
    for planned in _plan_requests(project, packs).values():
        try:
            job = _build_source(
                project,
                planned["pack"],
                planned["ref"],
                planned["source"],
                jobs,
                out,
                requested_tables=frozenset(planned["tables"]),
            )
        except ValidationError as exc:
            raise ValidationError(
                f"source {planned['source']!r} / pack {planned['pack'].name!r}：{exc}"
            ) from exc
        except Exception as exc:
            raise ValidationError(
                f"source {planned['source']!r} / pack {planned['pack'].name!r} "
                f"计算失败：{exc}"
            ) from exc
        warnings.extend(job.ctx.warnings)
    figure_records: list[dict[str, Any]] = []
    for spec in project.figures:
        panels = []
        panel_records = []
        for index, item in enumerate(spec.items):
            try:
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
            except ValidationError as exc:
                raise ValidationError(
                    f"figure {spec.name!r} panel[{index}]：{exc}"
                ) from exc
            except Exception as exc:
                raise ValidationError(
                    f"figure {spec.name!r} panel[{index}] 构建失败：{exc}"
                ) from exc
            panels.append(panel)
            panel_records.append(record)
        for job in jobs.values():
            warnings.extend(job.ctx.warnings)
        title = (
            plotutil.resolve_text(spec.title, project.lang)
            if spec.title is not None
            else None
        )
        style = select_style(spec.items)
        with plot_style(style):
            fig = Figure(panels, ncols=spec.ncols, title=title).build()
        path = out / "figures" / f"{spec.name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        chart.save(fig, path, project.dpi)
        rendered.append(path)
        payload = _figure_payload(spec, panel_records)
        payload["render"] = {
            "lang": project.lang,
            "dpi": project.dpi,
            "annotate": project.annotate,
            "style": dict(style),
        }
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
                "config": {
                    "name": project.yaml_path.name,
                    "sha256": sha256(project.yaml_path),
                },
                "name": project.name,
                "warnings": sorted(set(warnings)),
                "figures": figure_records,
                "sources": {
                    name: {
                        "topology": _display_path(
                            cfg.topology, project.yaml_path.parent
                        ),
                        "trajectory": _display_path(
                            cfg.trajectory, project.yaml_path.parent
                        ),
                        "trajectories": [
                            _display_path(path, project.yaml_path.parent)
                            for path in cfg.all_trajectories
                        ],
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
