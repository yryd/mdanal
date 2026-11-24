"""Source 运行态：加载视图、解析帧窗口和选择组，生成 ComputeContext。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Mapping

import MDAnalysis as mda

from ..config.geometry import FrameGeometry, GeometryWindow
from ..config.naming import NamingPlan, NamingSummary, apply_naming, build_plan
from ..config.system import (
    UNKNOWN_INPUT_WARNING,
    Group,
    SystemConfig,
    frame_window,
    load_universe,
    resolve_group,
    seek_frame,
)
from ..analyses._geometry import geometry_meta
from ..errors import ValidationError


@dataclass
class ComputeContext:
    system: SystemConfig
    universe: mda.Universe
    groups: Mapping[str, Group]
    start: int
    stop: int
    params: Mapping[str, Any]
    view: str
    source: str
    selection_frame: int
    geometry: FrameGeometry | None = None
    geometry_window: GeometryWindow | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    time_notes: tuple[str, ...] = ()
    seam_notes: tuple[str, ...] = ()
    geometry_meta: dict[str, Any] = field(default_factory=dict)
    requested_tables: frozenset[str] = frozenset()

    @property
    def frame_dt_ps(self) -> float:
        return self.system.dump_every * self.system.dt_ps

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class SourceRuntime:
    name: str
    cfg: SystemConfig
    views: dict[str, mda.Universe] = field(default_factory=dict)
    naming: NamingSummary | None = None
    start: int = 0
    stop: int = 0

    def __post_init__(self) -> None:
        self.start, self.stop = frame_window(self.cfg, self.universe("in_box"))

    def universe(self, view: str) -> mda.Universe:
        if view not in ("in_box", "continuous"):
            raise ValidationError(f"未知视图 {view!r}")
        if view in self.views:
            return self.views[view]
        universe = load_universe(self.cfg, coordinates=view)
        plan: NamingPlan | None = build_plan(self.cfg.naming)
        if plan is not None:
            summary = apply_naming(universe, plan)
            self.naming = self.naming or summary
        self.views[view] = universe
        return universe

    def window(self, section: tuple[int, int] | None) -> tuple[int, int]:
        if section is None:
            return self.start, self.stop
        offset_start, offset_stop = section
        start = self.start + offset_start
        stop = self.start + offset_stop
        if offset_stop > self.stop - self.start:
            raise ValidationError(
                f"section {list(section)} 超出 source 窗口 "
                f"[0, {self.stop - self.start})"
            )
        return start, stop


def normalize_compute(pack, compute: Mapping[str, Any] | None) -> dict[str, Any]:
    """先合并 PARAMS 默认值；key 和运行时必须用同一份有效参数。"""
    result = {
        key: spec.get("default")
        for key, spec in pack.params.items()
        if "default" in spec
    }
    result.update(dict(compute or {}))
    return result


def compute_context(
    runtime: SourceRuntime,
    pack,
    ref,
    requested_tables: frozenset[str] | None = None,
) -> ComputeContext:
    view = "continuous" if pack.coordinates == "continuous" else "in_box"
    universe = runtime.universe(view)
    start, stop = runtime.window(ref.section)
    if start >= stop:
        raise ValidationError(f"source {runtime.name!r} 的帧窗口为空")
    seek_frame(universe, start)
    groups: dict[str, Group] = {}
    for slot in pack.slots:
        value = ref.select.get(slot)
        if not isinstance(value, str) or not value:
            raise ValidationError(
                f"panel 缺少槽位 {slot!r}；该图包需要 {list(pack.slots)}"
            )
        groups[slot] = resolve_group(runtime.cfg, universe, value)
    if len(ref.select) != len(pack.slots) or set(ref.select) != set(pack.slots):
        raise ValidationError(
            f"select 的键必须正好是 {list(pack.slots)}，收到 {sorted(ref.select)}"
        )
    warnings: list[str] = []
    warnings.extend(str(note) for note in runtime.cfg.time_notes)
    warnings.extend(str(note) for note in runtime.cfg.seam_notes)
    if runtime.cfg.input_state == "unknown":
        warnings.append(UNKNOWN_INPUT_WARNING)
    input_geometry = (
        runtime.cfg.geometry.frame(start)
        if runtime.cfg.geometry is not None
        else None
    )
    geometry_window = (
        runtime.cfg.geometry.window(start, stop)
        if runtime.cfg.geometry is not None
        else None
    )
    input_pbc = tuple(
        bool(value)
        for value in (
            geometry_window.pbc_all
            if geometry_window is not None
            else (input_geometry.pbc if input_geometry else (True, True, True))
        )
    )
    periodicity = str((pack.geometry or {}).get("periodicity") or "any").lower()
    if periodicity == "full":
        status = "supported" if all(input_pbc) else "unsupported_geometry"
    elif periodicity == "xy":
        status = "supported" if (input_pbc[0] and input_pbc[1]) else "unsupported_geometry"
    else:
        status = "supported"
    if geometry_window is not None and geometry_window.pbc_changed:
        status = "unsupported_geometry"
        warnings.append(
            "分析窗口内边界类型发生变化；结果不能与固定 PBC 的同几何结果直接比较"
        )
    meta = geometry_meta(
        SimpleNamespace(geometry=input_geometry, geometry_window=geometry_window),
        kernel_pbc=getattr(pack, "kernel_pbc", "per_frame"),
        geometry_status=status,
    )
    if status != "supported":
        warnings.append(
            f"{pack.name} 的计算内核 kernel_pbc={pack.kernel_pbc!r}；"
            f"输入 PBC={list(input_pbc)}，结果不能与严格同几何结果直接比较"
        )
    return ComputeContext(
        system=runtime.cfg,
        universe=universe,
        groups=groups,
        start=start,
        stop=stop,
        params=normalize_compute(pack, ref.compute),
        view=view,
        source=runtime.name,
        selection_frame=start,
        geometry=input_geometry,
        geometry_window=geometry_window,
        warnings=warnings,
        time_notes=tuple(runtime.cfg.time_notes),
        seam_notes=tuple(runtime.cfg.seam_notes),
        geometry_meta=meta,
        requested_tables=frozenset(requested_tables or ()),
    )
