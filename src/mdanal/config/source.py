"""解析 figure-first 输入中的 `sources` 条目。

复用轨迹/几何/命名逻辑，把 `sources` 条目解析成来源配置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..errors import ValidationError
from .geometry import read_geometry
from .system import (
    SystemConfig,
    TOPOLOGY_SUFFIXES,
    _parse_frames,
    _parse_groups,
    _parse_view,
    _positive_float,
    _resolve_file,
    _resolve_trajectories,
    _scan_dump,
    _seam_notes,
    _time_axis_notes,
)
from .naming import parse_naming

SOURCE_KEYS = {
    "name",
    "topology",
    "trajectory",
    "timestep_fs",
    "dump_every",
    "frames",
    "groups",
    "view",
    "naming",
}


def parse_source(
    name: str,
    data: Mapping[str, Any],
    *,
    base_dir: Path,
    yaml_path: Path,
) -> SystemConfig:
    """把 `sources.<name>` 解析成来源配置。"""
    if not isinstance(data, Mapping):
        raise ValidationError(
            f"sources.{name} 必须是映射", where=f"{yaml_path}:sources.{name}"
        )
    unknown = set(data) - SOURCE_KEYS
    if unknown:
        raise ValidationError(
            f"sources.{name} 含未知字段 {sorted(unknown)}；"
            f"允许 {sorted(SOURCE_KEYS)}",
            where=f"{yaml_path}:sources.{name}",
        )
    if not isinstance(name, str) or not name:
        raise ValidationError("source 名称必须是非空字符串")
    where = str(yaml_path)
    timestep_fs = _positive_float(
        data.get("timestep_fs", 1.0), f"sources.{name}.timestep_fs", where
    )
    dump_every = data.get("dump_every", 1)
    if not isinstance(dump_every, int) or isinstance(dump_every, bool) or dump_every <= 0:
        raise ValidationError(
            f"sources.{name}.dump_every 必须是正整数",
            where=f"{where}:sources.{name}.dump_every",
        )
    frames = _parse_frames(data.get("frames"), f"{where}:sources.{name}")
    groups = _parse_groups(data.get("groups"), f"{where}:sources.{name}")
    topology = _resolve_file(
        data.get("topology"),
        base_dir,
        TOPOLOGY_SUFFIXES,
        "拓扑文件",
        f"{where}:sources.{name}",
    )
    trajectory = _resolve_trajectories(
        data.get("trajectory"), base_dir, f"{where}:sources.{name}"
    )
    scans = [_scan_dump(path) for path in trajectory]
    conventions = {scan.conventions for scan in scans}
    if len(conventions) > 1:
        detail = "、".join(
            f"{p.name}: {','.join(s.conventions) or '未知'}"
            for p, s in zip(trajectory, scans)
        )
        raise ValidationError(
            f"sources.{name} 各段轨迹的坐标列不一致（{detail}）",
            where=f"{where}:sources.{name}.trajectory",
        )
    geometry = read_geometry(trajectory)
    seam_notes = _seam_notes(trajectory, scans)
    time_notes = _time_axis_notes(geometry, dump_every, frames)
    view = _parse_view(
        data.get("view"), geometry.frames[0].origin, f"{where}:sources.{name}"
    )
    naming = parse_naming(
        data.get("naming"), base_dir, f"{where}:sources.{name}"
    )
    return SystemConfig(
        name=name,
        directory=base_dir,
        yaml_path=yaml_path,
        topology=topology,
        trajectory=trajectory[0],
        timestep_fs=timestep_fs,
        dump_every=dump_every,
        dt_ps=timestep_fs * 1e-3,
        frames=frames,
        groups=groups,
        naming=naming,
        box_low=geometry.frames[0].origin,
        view=view,
        input_state=scans[0].state,
        input_evidence=scans[0].evidence,
        coordinate_conventions=scans[0].conventions,
        trajectories=trajectory,
        seam_notes=seam_notes,
        time_notes=time_notes,
        segment_steps=tuple((scan.first_step, scan.last_step) for scan in scans),
        geometry=geometry,
    )


def read_sources(path: str | Path, data: Any) -> dict[str, SystemConfig]:
    """解析 `sources` 映射；路径相对 figures.yaml 所在目录。"""
    yaml_path = Path(path).expanduser().resolve()
    base_dir = yaml_path.parent
    if not isinstance(data, Mapping) or not data:
        raise ValidationError(
            "sources 必须是非空映射", where=f"{yaml_path}:sources"
        )
    result: dict[str, SystemConfig] = {}
    for name, entry in data.items():
        if (
            not isinstance(name, str)
            or not name
            or name in (".", "..")
            or "/" in name
            or "\\" in name
        ):
            raise ValidationError(
                "sources 的键必须是非空、不能含路径分隔符", where=f"{yaml_path}:sources"
            )
        result[name] = parse_source(
            name, entry, base_dir=base_dir, yaml_path=yaml_path
        )
    return result
