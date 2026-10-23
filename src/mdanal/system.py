"""体系加载：定位 system.yaml、解析配置、构建 Universe、解析原子选择。

system.yaml 是必需的：找不到就拒绝运行，不做任何自动推断。
文件内的 topology / trajectory 可以省略，此时在 system.yaml 所在目录内查找。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import MDAnalysis as mda
import MDAnalysis.transformations as tr
import yaml

from .errors import ValidationError

SYSTEM_FILENAME = "system.yaml"
TOPOLOGY_SUFFIXES = (".lmp", ".data")
TRAJECTORY_SUFFIXES = (".lammpstrj",)
ALLOWED_KEYS = {
    "name",
    "topology",
    "trajectory",
    "timestep_fs",
    "dump_every",
    "frames",
    "groups",
    "analyses",
}


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
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)


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

    return SystemConfig(
        name=name,
        origin=_read_origin(trajectory),
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
    )


# --------------------------------------------------------------------------- #
# Universe 与选择
# --------------------------------------------------------------------------- #


def load_universe(cfg: SystemConfig, *, scale_velocity: bool = False) -> mda.Universe:
    """按配置构建 Universe：补分子号、包裹坐标、按需换算速度单位。"""
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

    transforms = [tr.wrap(universe.atoms)]
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


def resolve_group(cfg: SystemConfig, universe: mda.Universe, value: str) -> Group:
    """把配置里的一个选择值解析成原子组：先查具名分组，再当作选择串。"""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("原子选择必须是非空字符串", where=f"{cfg.yaml_path}:analyses")

    named = value in cfg.groups
    selection = cfg.groups[value] if named else value

    atoms = universe.select_atoms(selection)
    if atoms.n_atoms == 0:
        hint = "（具名分组）" if named else ""
        raise ValidationError(
            f"选择 {value!r}{hint} 解析为空；对应的选择串为 {selection!r}",
            where=f"{cfg.yaml_path}:analyses",
        )
    return Group(key=value if named else None, selection=selection, atoms=atoms)


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


def _read_origin(trajectory: Path) -> tuple[float, float, float]:
    """读取 dump 首个盒边界，得到盒下角坐标。

    MDAnalysis 的 dump reader 会把盒平移到原点，图上的 z 因此与 data.lmp 相差一个
    常数偏移；输出坐标时用本函数把它加回去。
    """
    lows: list[float] = []
    bounds: list[list[float]] = []
    try:
        with open(trajectory, encoding="utf-8", errors="replace") as handle:
            for _ in range(12):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("ITEM: BOX BOUNDS"):
                    bounds = [
                        [float(v) for v in handle.readline().split()] for _ in range(3)
                    ]
                    break
    except OSError:
        return (0.0, 0.0, 0.0)

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
