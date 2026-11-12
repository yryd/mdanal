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

from .. import __version__
from ..config.naming import NamingSummary, apply_naming, build_plan
from ..errors import MdanalError, ValidationError
from ..config.registry import PlanItem
from ..config.system import (
    NOJUMP_WARNING,
    Group,
    SystemConfig,
    frame_window,
    load_universe,
    rebuild_group,
    resolve_group,
    seek_frame,
)
from ..plot import plotutil
from .context import RunContext
from .writers import (
    sha256,
    write_aligned,
    write_manifest,
    write_provenance,
    write_tables,
)


@dataclass
class RunOptions:
    lang: str = "zh"
    dpi: int = 300
    annotate: bool = False
    force: bool = False
    aligned: bool = False
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
    materialized: Mapping[str, bool] = field(default_factory=dict)
    segment_frames: tuple[int, ...] = ()
    frames: Mapping[int, tuple[int, int]] = field(default_factory=dict)

    def item_frames(self, item: PlanItem) -> tuple[int, int]:
        """该分析实际使用的帧窗口（体系窗口 + section 偏移）。"""
        return self.frames.get(item.order, (self.start, self.stop))

    def item_groups(self, item: PlanItem) -> dict[str, Group]:
        """在分析所用视图上按原子索引重建该分析的选择。"""
        universe = self.views[item.view]
        return {
            slot: rebuild_group(group, universe)
            for slot, group in self.groups[item.order].items()
        }




# --------------------------------------------------------------------------- #
# 准备与执行
# --------------------------------------------------------------------------- #


MEMORY_LIMIT = 1 << 30  # 单次读入内存的上限（字节）
MEMORY_MIN_FRAMES = 5


def prepare(
    cfg: SystemConfig, plan: Sequence[PlanItem], *, memory: bool = True
) -> Prepared:
    """构建计划所需的视图，并在帧窗口首帧一次性解析全部分析的选择。

    `memory=True` 时若估算内存放得下，就把轨迹一次读入内存：各分析随后扫内存，
    不再各自重读一遍文件。
    """
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
    segment_frames = tuple(_segment_frames(in_box))
    # MAICoS 会就地改写坐标（unwrap/pack），内存读取下这些改写会留给同一次运行的下一条分析，
    # 故只要有 velocity 就不读入内存。
    # 读入要扫完整个文件，只有当"重复读的帧数"确实超过文件总帧数时才划算。
    total_frames = len(in_box.trajectory)
    window = stop - start
    reuse = (len(plan) - 1) * window
    allow_memory = (
        memory
        and len(plan) >= 2
        and window * 2 >= total_frames
        and reuse >= total_frames
        and not any(item.mutates_positions for item in plan)
    )
    materialized = {
        key: _materialize(universe) if allow_memory else False
        for key, universe in views.items()
    }
    frames: dict[int, tuple[int, int]] = {}
    frame_problems: list[str] = []
    for item in plan:
        if item.section is None:
            frames[item.order] = (start, stop)
            continue
        offset_start, offset_stop = item.section
        if offset_stop > stop - start:
            frame_problems.append(
                f"{item.directory}: section {list(item.section)} 超出体系窗口 "
                f"[0, {stop - start})"
            )
            continue
        frames[item.order] = (start + offset_start, start + offset_stop)
    if frame_problems:
        raise ValidationError(
            "\n".join(frame_problems), where=f"{cfg.yaml_path}:analyses"
        )

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
        materialized=materialized,
        segment_frames=segment_frames,
        frames=frames,
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
        item_start, item_stop = prepared.item_frames(item)
        ctx = RunContext(
            system=cfg,
            plan_item=item,
            universe=prepared.views[item.view],
            groups=groups,
            start=item_start,
            stop=item_stop,
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
        if options.aligned:
            write_aligned(target, tables, cfg.view.shift)
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
                "window": {axis: list(bounds) for axis, bounds in item.window.items()},
                "section": list(item.section) if item.section else None,
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
                "parts": [
                    {"path": str(path), "sha256": sha256(path)}
                    for path in cfg.all_trajectories
                ],
                "segments": {
                    "count": len(cfg.all_trajectories),
                    "frames": list(prepared.segment_frames),
                    "steps": [list(pair) for pair in cfg.segment_steps],
                    "seam_notes": list(cfg.seam_notes),
                },
            },
            "input": {
                "coordinates": cfg.input_state,
                "detected_from": cfg.input_evidence,
            },
            "box": {
                "length": _box_length(prepared),
                "at_frame": prepared.start,
            },
            "view": {
                "origin": list(cfg.view.origin),
                "shift": list(cfg.view.shift),
            },
            "selection": {"frame": prepared.selection_frame},
            "naming": _naming_payload(prepared.naming),
            "frames": {
                "start": prepared.start,
                "stop": prepared.stop,
                "n_frames": len(prepared.views["in_box"].trajectory),
                "frame_dt_ps": prepared.cfg.dump_every * prepared.cfg.dt_ps,
            },
            "memory": {
                "enabled": any(prepared.materialized.values()),
                "views": dict(prepared.materialized),
            },
            "render": {
                "language": options.lang,
                "dpi": options.dpi,
                "annotate": options.annotate,
                "aligned": options.aligned,
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
    module_path = item.definition.module
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


def _box_length(prepared: Prepared) -> list[float]:
    """记录帧窗口首帧的盒长，供对比层对齐使用。"""
    universe = prepared.views["in_box"]
    universe.trajectory[prepared.start]
    return [float(value) for value in universe.dimensions[:3]]


def _materialize(universe) -> bool:
    """估算内存后把轨迹一次读入；放不下则保持按需读盘。"""
    n_frames = len(universe.trajectory)
    n_atoms = universe.atoms.n_atoms
    has_velocity = bool(universe.trajectory.ts.has_velocities)
    estimate = n_frames * n_atoms * (6 if has_velocity else 3) * 4
    if n_frames < MEMORY_MIN_FRAMES or estimate > MEMORY_LIMIT:
        return False

    step = _frame_step(universe)
    universe.transfer_to_memory()
    # 内存读取器把 ts.time 记成 帧号 × dt，dt 默认是构造函数里的值；
    # MSD 之类按帧间隔换算时间的分析会因此算错，这里恢复成实际的相邻帧时间差。
    if step is not None:
        universe.trajectory.ts.dt = step
    return True


def _frame_step(universe) -> float | None:
    """相邻两帧的时间差（ps）；取不到时返回 None。"""
    trajectory = universe.trajectory
    if len(trajectory) < 2:
        return None
    trajectory[0]
    start = float(trajectory.ts.time)
    trajectory[1]
    step = float(trajectory.ts.time) - start
    return step if step > 0 else None


def _segment_frames(universe) -> list[int]:
    """各段轨迹的帧数；单段时就是一个元素。"""
    readers = getattr(universe.trajectory, "readers", None)
    if readers:
        return [int(reader.n_frames) for reader in readers]
    return [int(len(universe.trajectory))]


def _library_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    versions: dict[str, str] = {}
    for package in ("MDAnalysis", "numpy", "pandas", "matplotlib", "maicos"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions
