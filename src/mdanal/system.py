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

from .errors import ValidationError
from .naming import NamingConfig, parse_naming

SYSTEM_FILENAME = "system.yaml"
TOPOLOGY_SUFFIXES = (".lmp", ".data")
TRAJECTORY_SUFFIXES = (".lammpstrj",)
AXES = ("x", "y", "z")
VIEWS = ("in_box", "continuous")
INPUT_STATES = ("unwrapped", "wrapped", "unknown")

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
    window: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def lower(self) -> tuple[float, float, float]:
        """视图坐标下的盒下角。"""
        return self.shift


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
    trajectory = _resolve_file(
        data.get("trajectory"), directory, TRAJECTORY_SUFFIXES, "轨迹文件", where
    )
    box_low, input_state, input_evidence = _scan_dump(trajectory)
    view = _parse_view(data.get("view"), box_low, where)
    naming = parse_naming(data.get("naming"), directory, where)

    return SystemConfig(
        name=name,
        directory=directory,
        yaml_path=yaml_path,
        topology=topology,
        trajectory=trajectory,
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

    try:
        universe = mda.Universe(
            str(cfg.topology),
            str(cfg.trajectory),
            format="LAMMPSDUMP",
            topology_format="data",
            dt=cfg.dt_ps,
        )
    except Exception as exc:  # MDAnalysis 的异常类型较杂，统一转成可读信息
        raise ValidationError(
            f"读取轨迹失败：{exc}",
            where=f"{cfg.topology} + {cfg.trajectory}",
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
            "view 必须是映射（可含 origin 与 window）", where=f"{where}:view"
        )
    unknown = set(value) - {"origin", "window"}
    if unknown:
        raise ValidationError(
            f"view 含未知字段 {sorted(unknown)}；允许 origin、window",
            where=f"{where}:view",
        )

    origin = _parse_origin(value.get("origin"), box_low, where)
    window = _parse_window(value.get("window"), where)
    shift = tuple(float(b - o) for b, o in zip(box_low, origin))
    return ViewConfig(origin, shift, window)


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


def _parse_window(value: Any, where: str) -> dict[str, tuple[float, float]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(
            "view.window 必须是映射（轴 → [下界, 上界]）", where=f"{where}:view.window"
        )
    unknown = set(value) - set(AXES)
    if unknown:
        raise ValidationError(
            f"view.window 含未知轴 {sorted(unknown)}；允许 {list(AXES)}",
            where=f"{where}:view.window",
        )

    window: dict[str, tuple[float, float]] = {}
    for axis, bounds in value.items():
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 2
            or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in bounds
            )
        ):
            raise ValidationError(
                f"view.window.{axis} 必须是两个数 [下界, 上界]，收到 {bounds!r}",
                where=f"{where}:view.window.{axis}",
            )
        low, high = (float(v) for v in bounds)
        if high <= low:
            raise ValidationError(
                f"view.window.{axis} 要求下界小于上界，收到 {[low, high]}",
                where=f"{where}:view.window.{axis}",
            )
        window[axis] = (low, high)
    return window


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


def _scan_dump(trajectory: Path) -> tuple[tuple[float, float, float], str, str]:
    """读 dump 首帧的盒边界与原子列，返回 (盒下角, 输入状态, 依据)。

    MDAnalysis 会把盒平移到原点，输出坐标时用盒下角还原原始坐标。
    """
    bounds: list[list[float]] = []
    columns: list[str] = []
    try:
        with open(trajectory, encoding="utf-8", errors="replace") as handle:
            for _ in range(64):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("ITEM: BOX BOUNDS"):
                    bounds = [
                        [float(v) for v in handle.readline().split()] for _ in range(3)
                    ]
                elif line.startswith("ITEM: ATOMS"):
                    columns = line[len("ITEM: ATOMS") :].split()
                    break
    except (OSError, ValueError):
        return (0.0, 0.0, 0.0), "unknown", ""

    box_low = _box_low(bounds)
    names = set(columns)
    if {"xu", "yu", "zu"} <= names:
        return box_low, "unwrapped", "xu yu zu"
    if {"x", "y", "z"} <= names:
        return box_low, "wrapped", "x y z"
    return box_low, "unknown", ""


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
