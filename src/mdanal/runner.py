"""执行计划：按视图加载体系、解析分组、调用各分析模块、落盘。
"""

from __future__ import annotations

import importlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import MDAnalysis as mda

from . import __version__, plotutil
from .errors import MdanalError, ValidationError
from .naming import NamingSummary, apply_naming, build_plan
from .registry import PlanItem
from .system import (
    NOJUMP_WARNING,
    Group,
    SystemConfig,
    frame_window,
    load_universe,
    rebuild_group,
    resolve_group,
    seek_frame,
)
from .writers import sha256, write_manifest, write_provenance, write_tables


@dataclass
class RunOptions:
    lang: str = "zh"
    dpi: int = 300
    annotate: bool = False
    force: bool = False
    figure_sizes: Mapping[str, tuple[float, float]] = field(
        default_factory=lambda: {"single": (3.5, 2.6), "wide": (7.0, 3.2), "map": (4.2, 3.0)}
    )


@dataclass
class Prepared:
    """一次运行所需的输入：体系、计划、各视图的 Universe、帧窗口与已解析的选择。"""

    cfg: SystemConfig
    plan: tuple[PlanItem, ...]
    views: Mapping[str, mda.Universe]
    groups: Mapping[int, Mapping[str, Group]]
    start: int
    stop: int
    selection_frame: int
    naming: NamingSummary | None = None

    def item_groups(self, item: PlanItem) -> dict[str, Group]:
        """在分析所用视图上按原子索引重建该分析的选择。"""
        universe = self.views[item.view]
        return {
            slot: rebuild_group(group, universe)
            for slot, group in self.groups[item.order].items()
        }


@dataclass
class RunContext:
    """传给分析模块的上下文。"""

    system: SystemConfig
    plan_item: PlanItem
    universe: mda.Universe
    groups: Mapping[str, Group]
    start: int
    stop: int
    lang: str
    dpi: int
    annotate: bool
    labels: plotutil.Labels
    figure_sizes: Mapping[str, tuple[float, float]]
    view: str
    selection_frame: int
    warnings: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def params(self) -> Mapping[str, Any]:
        return self.plan_item.params

    @property
    def frame_dt_ps(self) -> float:
        return self.system.dump_every * self.system.dt_ps

    def label(self, key: str, **fmt: Any) -> str:
        return self.labels(key, **fmt)

    def size(self, name: str = "single") -> tuple[float, float]:
        return self.figure_sizes.get(name, (3.5, 2.6))

    def window(self, axis: str) -> tuple[float, float] | None:
        """该轴的显示窗口；未设置时为 None。"""
        return self.system.view.window.get(axis)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def annotation(self) -> str:
        """帧窗口与关键参数，供 --annotate 使用。"""
        # 帧窗口左闭右开；标注里显示实际用到的最后一帧，时间换算为 ns
        t0 = self.start * self.frame_dt_ps / 1000.0
        t1 = max(self.stop - 1, 0) * self.frame_dt_ps / 1000.0
        window = self.label(
            "window", start=self.start, stop=self.stop - 1, t0=t0, t1=t1
        )
        params = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{window}\n{params}"


# --------------------------------------------------------------------------- #
# 准备与执行
# --------------------------------------------------------------------------- #


def prepare(cfg: SystemConfig, plan: Sequence[PlanItem]) -> Prepared:
    """构建计划所需的视图，并在帧窗口首帧一次性解析全部分析的选择。"""
    if not plan:
        raise ValidationError("没有要运行的分析", where=str(cfg.yaml_path))

    needed = ["in_box"]
    if any(item.view == "continuous" for item in plan):
        needed.append("continuous")
    velocity_views = {item.view for item in plan if item.needs_velocity}
    naming_plan = build_plan(cfg.naming)
    views: dict[str, mda.Universe] = {}
    naming_summary = None
    for key in needed:
        universe = load_universe(
            cfg, coordinates=key, scale_velocity=key in velocity_views
        )
        if naming_plan is not None:
            summary = apply_naming(universe, naming_plan)
            naming_summary = naming_summary or summary
        views[key] = universe

    in_box = views["in_box"]
    start, stop = frame_window(cfg, in_box)
    seek_frame(in_box, start)
    groups = {
        item.order: {
            slot: resolve_group(cfg, in_box, value)
            for slot, value in zip(item.definition.slots, item.selections)
        }
        for item in plan
    }
    return Prepared(
        cfg=cfg,
        plan=tuple(plan),
        views=views,
        groups=groups,
        start=start,
        stop=stop,
        selection_frame=start,
        naming=naming_summary,
    )


def execute(
    prepared: Prepared,
    outdir: str | Path,
    options: RunOptions,
    common_labels: Mapping[str, Mapping[str, str]],
) -> Path:
    """执行全部计划条目，返回输出目录。"""
    outdir = Path(outdir).expanduser().resolve()
    _prepare_outdir(outdir, options.force)

    cfg = prepared.cfg
    plotutil.apply_style()

    manifest_rows: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for item in prepared.plan:
        groups = prepared.item_groups(item)
        labels = plotutil.Labels(
            item.definition.labels.get(options.lang),
            common_labels.get(options.lang),
        )
        ctx = RunContext(
            system=cfg,
            plan_item=item,
            universe=prepared.views[item.view],
            groups=groups,
            start=prepared.start,
            stop=prepared.stop,
            lang=options.lang,
            dpi=options.dpi,
            annotate=options.annotate,
            labels=labels,
            figure_sizes=options.figure_sizes,
            view=item.view,
            selection_frame=prepared.selection_frame,
            warnings=_view_warnings(cfg, item),
        )

        module = _import_module(item)
        tables = _run_module(module, ctx, item)
        target = outdir / item.directory
        table_paths = write_tables(target, tables)
        figure_paths = _draw_figures(module, ctx, item, tables, target, options.dpi)

        meta = _collect_meta(module, ctx, tables, item)
        atoms = [groups[slot].n_atoms for slot in item.definition.slots]
        manifest_rows.append(
            {
                "order": item.order,
                "name": item.name,
                "tag": item.tag or "",
                "directory": item.directory,
                "sels": " | ".join(groups[s].selection for s in item.definition.slots),
                "atoms": " | ".join(str(n) for n in atoms),
                "params": json.dumps(dict(item.params), ensure_ascii=False),
            }
        )
        details.append(
            {
                "order": item.order,
                "name": item.name,
                "tag": item.tag,
                "directory": item.directory,
                "slots": list(item.definition.slots),
                "selections": [groups[s].selection for s in item.definition.slots],
                "atoms": atoms,
                "params": dict(item.params),
                "coordinates": item.definition.coordinates,
                "view": item.view,
                "warnings": list(ctx.warnings),
                "tables": [p.name for p in table_paths.values()],
                "figures": [p.name for p in figure_paths],
                "meta": meta,
            }
        )

        print(f"[{item.order:02d}] {item.directory:<18} "
              f"表 {len(table_paths)} 张，图 {len(figure_paths)} 张")
        for message in ctx.warnings:
            print(f"     警告：{message}")

    write_manifest(outdir, manifest_rows)
    write_provenance(
        outdir,
        {
            "mdanal_version": __version__,
            "system": cfg.name,
            "config": str(cfg.yaml_path),
            "topology": {"path": str(cfg.topology), "sha256": sha256(cfg.topology)},
            "trajectory": {
                "path": str(cfg.trajectory),
                "sha256": sha256(cfg.trajectory),
            },
            "input": {
                "coordinates": cfg.input_state,
                "detected_from": cfg.input_evidence,
            },
            "view": {
                "origin": list(cfg.view.origin),
                "shift": list(cfg.view.shift),
                "window": {
                    axis: list(bounds) for axis, bounds in cfg.view.window.items()
                },
            },
            "selection": {"frame": prepared.selection_frame},
            "naming": _naming_payload(prepared.naming),
            "frames": {
                "start": prepared.start,
                "stop": prepared.stop,
                "n_frames": len(prepared.views["in_box"].trajectory),
                "frame_dt_ps": prepared.cfg.dump_every * prepared.cfg.dt_ps,
            },
            "render": {
                "language": options.lang,
                "dpi": options.dpi,
                "annotate": options.annotate,
            },
            "analyses": details,
            "libraries": _library_versions(),
        },
    )
    print(f"\n输出：{outdir}")
    return outdir


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #


def _naming_payload(summary: NamingSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "sources": list(summary.sources),
        "residues": dict(summary.residue_counts),
        "atoms": summary.atom_count,
        "overrides": list(summary.overrides),
    }


def _view_warnings(cfg: SystemConfig, item: PlanItem) -> list[str]:
    """框架级提示：该分析所用视图在构建时做过什么。"""
    if item.view == "continuous" and cfg.input_state == "wrapped":
        return [NOJUMP_WARNING]
    return []


def _prepare_outdir(outdir: Path, force: bool) -> None:
    """准备输出目录：--force 时清空上一次的结果，避免残留旧分析的子目录。"""
    if not outdir.exists():
        outdir.mkdir(parents=True)
        return
    if not force:
        raise ValidationError("输出目录已存在；加 --force 才会覆盖", where=str(outdir))
    if not any(outdir.iterdir()):
        return
    if not (outdir / "provenance.json").is_file():
        raise ValidationError(
            "输出目录非空且不含 provenance.json，不像是本程序的输出，拒绝清空；请换一个目录",
            where=str(outdir),
        )
    shutil.rmtree(outdir)
    outdir.mkdir(parents=True)


def _import_module(item: PlanItem):
    module_path = f"{__package__}.{item.definition.module}"
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        raise MdanalError(
            f"{item.name} 的实现模块 {module_path} 无法导入：{exc}",
            where=str(item.directory),
        ) from exc


def _run_module(module, ctx: RunContext, item: PlanItem) -> dict[str, Any]:
    if not hasattr(module, "run"):
        raise MdanalError(
            f"{item.name} 的实现模块缺少 run() 函数", where=str(item.directory)
        )
    try:
        tables = module.run(ctx)
    except MdanalError:
        raise
    except Exception as exc:
        raise MdanalError(
            f"{item.directory} 执行失败：{exc}", where=str(ctx.system.yaml_path)
        ) from exc

    if not isinstance(tables, dict) or not tables:
        raise MdanalError(
            f"{item.name} 的 run() 必须返回非空 {{表名: DataFrame}}",
            where=str(item.directory),
        )
    return tables


def _draw_figures(
    module,
    ctx: RunContext,
    item: PlanItem,
    tables: Mapping[str, Any],
    target: Path,
    dpi: int,
) -> list[Path]:
    if not hasattr(module, "figures"):
        return []
    try:
        produced = module.figures(ctx, dict(tables)) or []
    except MdanalError:
        raise
    except Exception as exc:
        raise MdanalError(
            f"{item.directory} 绘图失败：{exc}", where=str(ctx.system.yaml_path)
        ) from exc

    names = [name for name, _ in produced]
    if len(set(names)) != len(names):
        raise MdanalError(
            f"{item.name} 产生了重名图 {names}", where=str(item.directory)
        )
    return [
        plotutil.save(fig, target / "figures" / f"{name}.png", dpi)
        for name, fig in produced
    ]


def _collect_meta(module, ctx: RunContext, tables, item: PlanItem) -> dict:
    """分析可选地提供 meta(ctx, tables)，用于把校验所需的几何信息写进溯源。"""
    if not hasattr(module, "meta"):
        return {}
    try:
        return dict(module.meta(ctx, dict(tables)) or {})
    except Exception as exc:
        raise MdanalError(
            f"{item.directory} 生成元数据失败：{exc}", where=str(ctx.system.yaml_path)
        ) from exc


def _library_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for package in ("MDAnalysis", "numpy", "pandas", "matplotlib", "maicos"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions
