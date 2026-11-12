"""体系加载：定位并解析 system.yaml，构建各视图的 Universe，解析原子选择。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import MDAnalysis as mda
import MDAnalysis.transformations as tr
import numpy as np
import yaml

from ..errors import ValidationError
from .naming import NamingConfig, parse_naming

SYSTEM_FILENAME = "system.yaml"
TOPOLOGY_SUFFIXES = (".lmp", ".data")
TRAJECTORY_SUFFIXES = (".lammpstrj",)
AXES = ("x", "y", "z")
VIEWS = ("in_box", "continuous")

UNKNOWN_INPUT_WARNING = "无法从轨迹表头判断坐标是否包裹，按未包裹坐标处理。"
NOJUMP_WARNING = (
    "输入为包裹坐标，已用 NoJump 重建连续坐标；"
    "相邻帧位移超过半个盒长时结果可能失真。"
)

ALLOWED_KEYS = {
    "name",
    "topology",
    "trajectory",
    "timestep_fs",
    "dump_every",
    "frames",
    "groups",
    "analyses",
    "view",
    "naming",
}


@dataclass(frozen=True)
class ViewConfig:
    """视图坐标的设置。

    origin 是视图坐标的零点（绝对坐标），shift 是盒坐标到视图坐标的偏移，
    二者与盒下角 box_low 满足 shift = box_low - origin。
    shift 同时就是视图坐标下的盒下角。
    """

    origin: tuple[float, float, float]
    shift: tuple[float, float, float]

@dataclass(frozen=True)
class SystemConfig:
    """system.yaml 的解析结果。不持有轨迹句柄，因此读配置不读轨迹。"""

    name: str
    directory: Path
    yaml_path: Path
    topology: Path
    trajectory: Path
    timestep_fs: float
    dump_every: int
    dt_ps: float
    frames: tuple[int, int] | None
    groups: dict[str, str]
    analyses: tuple[dict[str, Any], ...]
    naming: NamingConfig = field(default_factory=NamingConfig)
    box_low: tuple[float, float, float] = (0.0, 0.0, 0.0)
    view: ViewConfig = field(
        default_factory=lambda: ViewConfig((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    )
    input_state: str = "unknown"
    input_evidence: str = ""
    trajectories: tuple[Path, ...] = ()
    seam_notes: tuple[str, ...] = ()
    segment_steps: tuple[tuple[int | None, int | None], ...] = ()

    @property
    def all_trajectories(self) -> tuple[Path, ...]:
        """参与合并的全部轨迹；单段时就是那一个文件。"""
        return self.trajectories or (self.trajectory,)


@dataclass(frozen=True)
class DumpScan:
    """dump 的表头信息：盒下角、坐标状态、首末步。"""

    box_low: tuple[float, float, float]
    state: str
    evidence: str
    first_step: int | None
    last_step: int | None


@dataclass(frozen=True)
class Group:
    """一个已解析的原子选择。key 为命中的具名分组，直传选择串时为 None。"""

    key: str | None
    selection: str
    atoms: mda.AtomGroup

    @property
    def n_atoms(self) -> int:
        return self.atoms.n_atoms


# --------------------------------------------------------------------------- #
# 定位与读取
# --------------------------------------------------------------------------- #


def locate_system_yaml(path: str | Path) -> Path:
    """把 --system 的三种形态统一成 system.yaml 的路径。"""
    raw = Path(path).expanduser()
    if raw.is_dir():
        candidate = raw / SYSTEM_FILENAME
    elif raw.suffix in (".yaml", ".yml"):
        candidate = raw
    else:
        candidate = raw.parent / SYSTEM_FILENAME

    if not candidate.is_file():
        raise ValidationError(
            "找不到 system.yaml；该文件是必需的（可在其中省略 topology/trajectory，"
            "此时在其所在目录内查找）",
            where=str(candidate),
        )
    return candidate.resolve()


def read_system(path: str | Path) -> SystemConfig:
    """解析 system.yaml。不创建 Universe，不读取轨迹。"""
    yaml_path = locate_system_yaml(path)
    data = _load_yaml(yaml_path)
    where = str(yaml_path)

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        raise ValidationError(
            f"未知的顶层字段 {sorted(unknown)}；允许的字段为 {sorted(ALLOWED_KEYS)}",
            where=where,
        )

    directory = yaml_path.parent
    name = data.get("name") or directory.name
    if not isinstance(name, str):
        raise ValidationError("name 必须是字符串", where=f"{where}:name")

    timestep_fs = _positive_float(data.get("timestep_fs", 1.0), "timestep_fs", where)
    dump_every = data.get("dump_every", 1)
    if not isinstance(dump_every, int) or dump_every <= 0:
        raise ValidationError("dump_every 必须是正整数", where=f"{where}:dump_every")

    frames = _parse_frames(data.get("frames"), where)
    groups = _parse_groups(data.get("groups"), where)
    analyses = _parse_analyses(data.get("analyses"), where)

    topology = _resolve_file(
        data.get("topology"), directory, TOPOLOGY_SUFFIXES, "拓扑文件", where
    )
    trajectory = _resolve_trajectories(data.get("trajectory"), directory, where)
    scans = [_scan_dump(path) for path in trajectory]
    states = {scan.state for scan in scans}
    if len(states) > 1:
        detail = "、".join(f"{p.name}: {s.state}" for p, s in zip(trajectory, scans))
        raise ValidationError(
            f"各段轨迹的坐标状态不一致（{detail}）；同一体系的各段必须用同样的坐标列",
            where=f"{where}:trajectory",
        )
    box_low = scans[0].box_low
    input_state = scans[0].state
    input_evidence = scans[0].evidence
    seam_notes = _seam_notes(trajectory, scans)
    view = _parse_view(data.get("view"), box_low, where)
    naming = parse_naming(data.get("naming"), directory, where)

    return SystemConfig(
        name=name,
        directory=directory,
        yaml_path=yaml_path,
        topology=topology,
        trajectory=trajectory[0],
        timestep_fs=timestep_fs,
        dump_every=dump_every,
        dt_ps=timestep_fs * 1e-3,
        frames=frames,
        groups=groups,
        analyses=analyses,
        naming=naming,
        box_low=box_low,
        view=view,
        input_state=input_state,
        input_evidence=input_evidence,
        trajectories=trajectory,
        seam_notes=seam_notes,
        segment_steps=tuple((scan.first_step, scan.last_step) for scan in scans),
    )


# --------------------------------------------------------------------------- #
# Universe 与选择
# --------------------------------------------------------------------------- #


def load_universe(
    cfg: SystemConfig, *, coordinates: str = "in_box", scale_velocity: bool = False
) -> mda.Universe:
    """按视图构建 Universe。

    两种视图都使用盒坐标：读取器坐标加上盒下角折回，范围 0…L。
    视图平移只作用于选择串与输出坐标，不改变 Universe 内的坐标。
    """
    if coordinates not in VIEWS:
        raise ValidationError(
            f"未知的坐标视图 {coordinates!r}；只能是 {list(VIEWS)}"
        )

    files = [str(path) for path in cfg.all_trajectories]
    target: str | list[str] = files[0] if len(files) == 1 else files
    try:
        universe = mda.Universe(
            str(cfg.topology),
            target,
            format="LAMMPSDUMP",
            topology_format="data",
            dt=cfg.dt_ps,
        )
    except Exception as exc:  # MDAnalysis 的异常类型较杂，统一转成可读信息
        raise ValidationError(
            f"读取轨迹失败：{exc}",
            where=f"{cfg.topology} + " + " + ".join(cfg.all_trajectories[i].name for i in range(len(files))),
        ) from exc

    if not hasattr(universe.atoms, "molnums"):
        universe.add_TopologyAttr("molnums", universe.residues.resids)

    if scale_velocity and not universe.trajectory.ts.has_velocities:
        raise ValidationError(
            "有分析需要速度，但轨迹不含速度列", where=str(cfg.trajectory)
        )

    wrapped_input = cfg.input_state == "wrapped"
    transforms = []
    if coordinates == "in_box" or wrapped_input:
        transforms.append(tr.wrap(universe.atoms))
    if coordinates == "continuous" and wrapped_input:
        transforms.append(tr.NoJump())
    if scale_velocity:
        transforms.append(_scale_velocity)

    universe.trajectory.add_transformations(*transforms)
    return universe


def frame_window(cfg: SystemConfig, universe: mda.Universe) -> tuple[int, int]:
    """返回 (start, stop)，并校验落在轨迹长度内。"""
    n_frames = len(universe.trajectory)
    if cfg.frames is None:
        return 0, n_frames

    start, stop = cfg.frames
    if not (0 <= start < stop <= n_frames):
        raise ValidationError(
            f"帧窗口 {[start, stop]} 超出轨迹范围；该轨迹共 {n_frames} 帧，"
            f"要求 0 <= start < stop <= {n_frames}",
            where=f"{cfg.yaml_path}:frames",
        )
    return start, stop


def seek_frame(universe: mda.Universe, frame: int) -> None:
    """把轨迹定位到指定帧。"""
    universe.trajectory[frame]


def resolve_group(cfg: SystemConfig, universe: mda.Universe, value: str) -> Group:
    """把配置里的一个选择值解析成原子组：先查具名分组，再当作选择串。

    选择串里的坐标按视图坐标书写，这里临时把坐标平移一个视图偏移再求值。
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("原子选择必须是非空字符串", where=f"{cfg.yaml_path}:analyses")

    named = value in cfg.groups
    selection = cfg.groups[value] if named else value

    shift = np.asarray(cfg.view.shift, dtype=np.float32)
    universe.atoms.positions += shift
    try:
        atoms = universe.select_atoms(selection)
    finally:
        universe.atoms.positions -= shift

    if atoms.n_atoms == 0:
        hint = "（具名分组）" if named else ""
        raise ValidationError(
            f"选择 {value!r}{hint} 解析为空；对应的选择串为 {selection!r}",
            where=f"{cfg.yaml_path}:analyses",
        )
    return Group(key=value if named else None, selection=selection, atoms=atoms)


def rebuild_group(group: Group, universe: mda.Universe) -> Group:
    """按原子索引在另一个视图上重建原子组。"""
    return Group(
        key=group.key,
        selection=group.selection,
        atoms=universe.atoms[group.atoms.indices],
    )


# --------------------------------------------------------------------------- #
# 内部工具
# --------------------------------------------------------------------------- #


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"无法读取文件：{exc}", where=str(path)) from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f"（第 {mark.line + 1} 行）" if mark is not None else ""
        raise ValidationError(f"YAML 语法错误{line}：{exc}", where=str(path)) from exc

    if data is None:
        raise ValidationError("文件为空", where=str(path))
    if not isinstance(data, dict):
        raise ValidationError("顶层必须是映射", where=str(path))
    return data


def _positive_float(value: Any, key: str, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValidationError(f"{key} 必须是正数", where=f"{where}:{key}")
    return float(value)


def _parse_frames(value: Any, where: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        raise ValidationError(
            "frames 必须是两个整数 [start, stop]（左闭右开）",
            where=f"{where}:frames",
        )
    start, stop = value
    if start < 0 or stop <= start:
        raise ValidationError(
            f"frames 要求 0 <= start < stop，收到 {[start, stop]}",
            where=f"{where}:frames",
        )
    return int(start), int(stop)


def _parse_groups(value: Any, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("groups 必须是映射（名字 → 选择串）", where=f"{where}:groups")
    groups: dict[str, str] = {}
    for key, sel in value.items():
        if not isinstance(key, str) or not key:
            raise ValidationError(f"分组名必须是非空字符串，收到 {key!r}", where=f"{where}:groups")
        if not isinstance(sel, str) or not sel.strip():
            raise ValidationError(
                f"分组 {key!r} 的选择串必须是非空字符串",
                where=f"{where}:groups.{key}",
            )
        groups[key] = sel
    return groups


def _parse_analyses(value: Any, where: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValidationError("analyses 必须是列表", where=f"{where}:analyses")
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            raise ValidationError(
                f"第 {index} 条分析必须是映射", where=f"{where}:analyses[{index}]"
            )
        entries.append(entry)
    return tuple(entries)


def _parse_view(value: Any, box_low: tuple[float, ...], where: str) -> ViewConfig:
    """解析 view 块：把 origin 解析成绝对坐标，并据此算出平移量。"""
    if value is None:
        return ViewConfig((0.0, 0.0, 0.0), box_low)

    if not isinstance(value, dict):
        raise ValidationError(
            "view 必须是映射（只有一个 origin 字段）", where=f"{where}:view"
        )
    unknown = set(value) - {"origin"}
    if unknown:
        raise ValidationError(
            f"view 含未知字段 {sorted(unknown)}；窗口已下放到每条分析的 plot.window",
            where=f"{where}:view",
        )

    origin = _parse_origin(value.get("origin"), box_low, where)
    shift = tuple(float(b - o) for b, o in zip(box_low, origin))
    return ViewConfig(origin, shift)


def _parse_origin(
    value: Any, box_low: tuple[float, ...], where: str
) -> tuple[float, float, float]:
    if value is None:
        return (0.0, 0.0, 0.0)
    if value == "box_corner":
        return tuple(float(v) for v in box_low)  # type: ignore[return-value]
    if (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
        )
    ):
        return tuple(float(v) for v in value)  # type: ignore[return-value]
    raise ValidationError(
        f"view.origin 只能是 [x, y, z] 或 box_corner，收到 {value!r}",
        where=f"{where}:view.origin",
    )


def _resolve_file(
    value: Any, directory: Path, suffixes: tuple[str, ...], label: str, where: str
) -> Path:
    """按配置取值；缺省时在同目录内按后缀查找，必须唯一。"""
    if value is not None:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{label}路径必须是非空字符串", where=where)
        path = (directory / value).expanduser() if not Path(value).is_absolute() else Path(value)
        if not path.is_file():
            raise ValidationError(f"{label}不存在：{path}", where=where)
        return path.resolve()

    candidates = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in suffixes
    )
    if not candidates:
        raise ValidationError(
            f"未指定{label}，且在 {directory} 内找不到 {' / '.join(suffixes)} 文件",
            where=where,
        )
    if len(candidates) > 1:
        raise ValidationError(
            f"{label}不唯一，找到 {[p.name for p in candidates]}；请在 system.yaml 中显式指定",
            where=where,
        )
    return candidates[0].resolve()


def _scan_dump(trajectory: Path) -> DumpScan:
    """读 dump 表头：盒边界、坐标列、首末步。

    MDAnalysis 会把盒平移到原点，输出坐标时用盒下角还原原始坐标。
    """
    bounds: list[list[float]] = []
    columns: list[str] = []
    first_step: int | None = None
    try:
        with open(trajectory, encoding="utf-8", errors="replace") as handle:
            for _ in range(64):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("ITEM: TIMESTEP") and first_step is None:
                    try:
                        first_step = int(handle.readline())
                    except ValueError:
                        first_step = None
                elif line.startswith("ITEM: BOX BOUNDS"):
                    bounds = [
                        [float(v) for v in handle.readline().split()] for _ in range(3)
                    ]
                elif line.startswith("ITEM: ATOMS"):
                    columns = line[len("ITEM: ATOMS") :].split()
                    break
    except (OSError, ValueError):
        return DumpScan((0.0, 0.0, 0.0), "unknown", "", None, None)

    box_low = _box_low(bounds)
    names = set(columns)
    if {"xu", "yu", "zu"} <= names:
        state, evidence = "unwrapped", "xu yu zu"
    elif {"x", "y", "z"} <= names:
        state, evidence = "wrapped", "x y z"
    else:
        state, evidence = "unknown", ""
    return DumpScan(box_low, state, evidence, first_step, _last_step(trajectory))


def _last_step(path: Path, chunk: int = 1 << 16) -> int | None:
    """从文件尾部找最后一个 TIMESTEP，避免为读末帧扫全文件。"""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - chunk))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    index = tail.rfind("ITEM: TIMESTEP")
    if index < 0:
        return None
    lines = tail[index:].splitlines()
    if len(lines) < 2:
        return None
    try:
        return int(lines[1].strip())
    except ValueError:
        return None


def _resolve_trajectories(
    value: Any, directory: Path, where: str
) -> tuple[Path, ...]:
    """解析 trajectory：单个路径、路径列表，或留空时在目录内唯一查找。"""
    if value is None:
        candidates = sorted(
            p
            for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in TRAJECTORY_SUFFIXES
        )
        if not candidates:
            raise ValidationError(
                f"未指定轨迹文件，且在 {directory} 内找不到 "
                f"{' / '.join(TRAJECTORY_SUFFIXES)} 文件",
                where=where,
            )
        if len(candidates) > 1:
            raise ValidationError(
                f"轨迹文件不唯一，找到 {[p.name for p in candidates]}；"
                "请在 system.yaml 中显式指定",
                where=where,
            )
        return (candidates[0].resolve(),)

    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)) and value:
        values = list(value)
    else:
        raise ValidationError(
            "trajectory 必须是路径或路径列表", where=f"{where}:trajectory"
        )

    paths: list[Path] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(
                "trajectory 的每一项都必须是非空字符串", where=f"{where}:trajectory"
            )
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = directory / path
        if not path.is_file():
            raise ValidationError(
                f"轨迹文件不存在：{path}", where=f"{where}:trajectory"
            )
        paths.append(path.resolve())
    return tuple(paths)


def _seam_notes(paths: tuple[Path, ...], scans: list[DumpScan]) -> tuple[str, ...]:
    """段与段接缝处的提示：时间倒退、盒下角不同。"""
    notes: list[str] = []
    for index in range(1, len(scans)):
        previous, current = scans[index - 1], scans[index]
        if (
            current.first_step is not None
            and previous.last_step is not None
            and current.first_step <= previous.last_step
        ):
            if current.first_step == previous.last_step:
                notes.append(
                    f"{paths[index].name} 的起始步与 {paths[index - 1].name} 的结束步"
                    f"相同（{current.first_step}）：接缝处可能是同一帧写了两遍，建议裁掉"
                )
            else:
                notes.append(
                    f"{paths[index].name} 的起始步 {current.first_step} 小于 "
                    f"{paths[index - 1].name} 的结束步 {previous.last_step}："
                    "两段时间倒退，按帧序拼接"
                )
        if current.box_low != previous.box_low:
            notes.append(
                f"{paths[index].name} 的盒下角 {current.box_low} 与上一段 "
                f"{previous.box_low} 不同；视图偏移沿用第一段"
            )
    return tuple(notes)


def _box_low(bounds: list[list[float]]) -> tuple[float, float, float]:
    if len(bounds) != 3:
        return (0.0, 0.0, 0.0)

    if any(len(row) >= 3 for row in bounds):
        xy, xz, yz = (row[2] if len(row) >= 3 else 0.0 for row in bounds)
        lows = [
            bounds[0][0] - min(0.0, xy, xz, xy + xz),
            bounds[1][0] - min(0.0, yz),
            bounds[2][0],
        ]
    else:
        lows = [row[0] for row in bounds]
    return (float(lows[0]), float(lows[1]), float(lows[2]))


def _scale_velocity(ts):
    """把速度从 Å/fs 换成 Å/ps。逐帧执行，一次性相乘会被下一帧覆盖。"""
    ts.velocities *= 1000.0
    return ts
