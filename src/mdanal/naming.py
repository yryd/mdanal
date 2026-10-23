"""命名：给残基（分子）与原子补上名字与元素，供选择串与标签使用。

名字有两个来源：带注释的 LAMMPS data 文件（Atoms 段每行 `# 原子名 分子名`），
以及 system.yaml 里按原子类型给出的规则；规则覆盖文件里的名字时会记一条警告。
写进拓扑的只有 names / resnames / elements，types 与 resids 不动。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .errors import ValidationError

# 常见元素的平均原子质量（u）。元素按质量推断，可覆盖 C1 / Cl1 这类名字歧义。
ELEMENT_MASSES = {
    "H": 1.008,
    "He": 4.003,
    "Li": 6.94,
    "Be": 9.012,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998,
    "Ne": 20.180,
    "Na": 22.990,
    "Mg": 24.305,
    "Al": 26.982,
    "Si": 28.085,
    "P": 30.974,
    "S": 32.060,
    "Cl": 35.450,
    "Ar": 39.948,
    "K": 39.098,
    "Ca": 40.078,
    "Ti": 47.867,
    "Cr": 51.996,
    "Mn": 54.938,
    "Fe": 55.845,
    "Co": 58.933,
    "Ni": 58.693,
    "Cu": 63.546,
    "Zn": 65.380,
    "Br": 79.904,
    "Mo": 95.950,
    "Ag": 107.868,
    "I": 126.904,
    "Pt": 195.084,
    "Au": 196.967,
}

# 质量与元素标准原子量之差超过这个值就不猜，直接报错
MASS_TOLERANCE = 0.35


@dataclass(frozen=True)
class NamingConfig:
    """system.yaml 中 naming 块的解析结果。"""

    from_data: Path | None = None
    residues: tuple[tuple[str, frozenset[str]], ...] = ()
    atoms: Mapping[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.from_data is None and not self.residues and not self.atoms


@dataclass(frozen=True)
class NamingPlan:
    """命名所需的全部输入：配置加上从 data 文件读到的注释。"""

    config: NamingConfig
    comments: Mapping[int, tuple[str, str]]


@dataclass(frozen=True)
class NamingSummary:
    """命名结果，用于打印与溯源。"""

    sources: tuple[str, ...]
    residue_counts: Mapping[str, int]
    atom_count: int
    overrides: tuple[str, ...]

    @property
    def warning(self) -> str | None:
        if not self.overrides:
            return None
        return "命名规则覆盖了文件中的名字：" + "；".join(self.overrides)


def parse_naming(value: Any, directory: Path, where: str) -> NamingConfig:
    """解析 system.yaml 的 naming 块。"""
    if value is None:
        return NamingConfig()
    if not isinstance(value, dict):
        raise ValidationError("naming 必须是映射", where=f"{where}:naming")

    unknown = set(value) - {"from_data", "residues", "atoms"}
    if unknown:
        raise ValidationError(
            f"naming 含未知字段 {sorted(unknown)}；允许 from_data、residues、atoms",
            where=f"{where}:naming",
        )

    from_data = None
    raw = value.get("from_data")
    if raw is not None:
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError(
                "naming.from_data 必须是文件路径", where=f"{where}:naming.from_data"
            )
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = directory / path
        if not path.is_file():
            raise ValidationError(
                f"naming.from_data 指向的文件不存在：{path}",
                where=f"{where}:naming.from_data",
            )
        from_data = path.resolve()

    residues: list[tuple[str, frozenset[str]]] = []
    raw_residues = value.get("residues") or []
    if not isinstance(raw_residues, (list, tuple)):
        raise ValidationError(
            "naming.residues 必须是列表", where=f"{where}:naming.residues"
        )
    for index, entry in enumerate(raw_residues, start=1):
        position = f"{where}:naming.residues[{index}]"
        if not isinstance(entry, dict):
            raise ValidationError("每条残基规则必须是映射", where=position)
        unknown = set(entry) - {"name", "types"}
        if unknown:
            raise ValidationError(
                f"残基规则含未知字段 {sorted(unknown)}；允许 name、types", where=position
            )
        name = entry.get("name")
        types = entry.get("types")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("残基规则缺少非空的 name", where=position)
        if (
            not isinstance(types, (list, tuple))
            or not types
            or not all(isinstance(t, (str, int)) and not isinstance(t, bool) for t in types)
        ):
            raise ValidationError(
                "残基规则的 types 必须是非空的类型列表", where=position
            )
        residues.append((name, frozenset(str(t) for t in types)))

    atoms: dict[str, str] = {}
    raw_atoms = value.get("atoms") or {}
    if not isinstance(raw_atoms, dict):
        raise ValidationError("naming.atoms 必须是映射", where=f"{where}:naming.atoms")
    for key, name in raw_atoms.items():
        if not isinstance(name, str) or not name.strip():
            raise ValidationError(
                f"naming.atoms 的 {key!r} 必须是字符串", where=f"{where}:naming.atoms"
            )
        atoms[str(key)] = name

    return NamingConfig(from_data=from_data, residues=tuple(residues), atoms=atoms)


def build_plan(config: NamingConfig) -> NamingPlan | None:
    """读 from_data 的注释，得到可执行的命名计划；没有命名配置时返回 None。"""
    if config.empty:
        return None
    comments = (
        _read_comments(config.from_data) if config.from_data is not None else {}
    )
    return NamingPlan(config=config, comments=comments)


def apply_naming(universe, plan: NamingPlan) -> NamingSummary:
    """把名字写进 Universe，并返回汇总。缺名字或规则冲突时抛 ValidationError。"""
    config = plan.config
    types = np.asarray(universe.atoms.types)
    atom_ids = np.asarray(universe.atoms.ids).astype(int)
    residx = np.asarray(universe.atoms.resindices)
    n_atoms = universe.atoms.n_atoms
    n_residues = universe.residues.n_residues

    atom_names = np.array([""] * n_atoms, dtype=object)
    mol_names = np.array([""] * n_atoms, dtype=object)
    for index, atom_id in enumerate(atom_ids):
        entry = plan.comments.get(int(atom_id))
        if entry is not None:
            atom_names[index], mol_names[index] = entry

    resnames = np.array([""] * n_residues, dtype=object)
    for ri in range(n_residues):
        found = {mol_names[i] for i in np.nonzero(residx == ri)[0] if mol_names[i]}
        if len(found) > 1:
            raise ValidationError(
                f"残基 {int(universe.residues.resids[ri])} 内的分子名不一致："
                f"{sorted(found)}",
                where=str(config.from_data),
            )
        if found:
            resnames[ri] = found.pop()

    overrides: list[str] = []
    overrides.extend(_apply_residue_rules(config, types, residx, resnames, universe))
    overrides.extend(_apply_atom_rules(config, types, atom_names))

    _require_complete(resnames, atom_names, universe)

    _set_attribute(universe, "names", atom_names)
    _set_attribute(universe, "resnames", resnames)
    _require_selectable(universe, "resname", resnames)
    _require_selectable(universe, "name", atom_names)

    elements = _elements_from_mass(types, np.asarray(universe.atoms.masses))
    _set_attribute(universe, "elements", elements)

    sources = []
    if config.from_data is not None:
        sources.append(f"from_data:{config.from_data}")
    if config.residues:
        sources.append("residues")
    if config.atoms:
        sources.append("atoms")

    return NamingSummary(
        sources=tuple(sources),
        residue_counts=dict(Counter(resnames)),
        atom_count=n_atoms,
        overrides=tuple(overrides),
    )


# --------------------------------------------------------------------------- #
# 内部
# --------------------------------------------------------------------------- #


def _read_comments(path: Path) -> dict[int, tuple[str, str]]:
    """读 Atoms 段注释，返回 {原子 id: (原子名, 分子名)}。"""
    comments: dict[int, tuple[str, str]] = {}
    inside = False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("Atoms"):
                    inside = True
                    continue
                if not inside:
                    continue
                text = line.strip()
                if not text:
                    continue
                if text[0].isalpha():
                    break
                if "#" not in text:
                    continue
                body, comment = text.split("#", 1)
                fields = body.split()
                parts = comment.split()
                if len(fields) < 3 or len(parts) < 2:
                    continue
                try:
                    atom_id = int(fields[0])
                except ValueError:
                    continue
                comments[atom_id] = (parts[0], parts[1])
    except OSError as exc:
        raise ValidationError(f"无法读取命名来源：{exc}", where=str(path)) from exc

    if not comments:
        raise ValidationError(
            "文件中没有可用的 Atoms 注释（每行应为 `# 原子名 分子名`）", where=str(path)
        )
    return comments


def _apply_residue_rules(
    config: NamingConfig,
    types: np.ndarray,
    residx: np.ndarray,
    resnames: np.ndarray,
    universe,
) -> list[str]:
    if not config.residues:
        return []

    counts: Counter = Counter()
    for ri in range(universe.residues.n_residues):
        present = frozenset(types[residx == ri])
        matched = [name for name, allowed in config.residues if allowed == present]
        if len(matched) > 1:
            raise ValidationError(
                f"残基 {int(universe.residues.resids[ri])} 同时命中多条 residues 规则："
                f"{matched}",
                where="naming.residues",
            )
        if not matched:
            continue
        new = matched[0]
        old = resnames[ri]
        if old != new:
            counts[(old or "（无名）", new)] += 1
            resnames[ri] = new

    return [
        f"分子名 {count} 个（{old}→{new}）" for (old, new), count in sorted(counts.items())
    ]


def _apply_atom_rules(
    config: NamingConfig, types: np.ndarray, atom_names: np.ndarray
) -> list[str]:
    if not config.atoms:
        return []

    overrides: list[str] = []
    for type_value, new in config.atoms.items():
        mask = types == type_value
        if not mask.any():
            raise ValidationError(
                f"naming.atoms 里的 type {type_value} 在拓扑中不存在",
                where="naming.atoms",
            )
        changed = int((atom_names[mask] != new).sum())
        if changed:
            previous = sorted({name for name in atom_names[mask] if name and name != new})
            label = "、".join(previous) if previous else "（无名）"
            overrides.append(f"原子名 {changed} 个（{label}→{new}，type {type_value}）")
        atom_names[mask] = new
    return overrides


def _require_complete(resnames: np.ndarray, atom_names: np.ndarray, universe) -> None:
    missing_residues = [
        int(universe.residues.resids[i])
        for i in range(len(resnames))
        if not resnames[i]
    ]
    if missing_residues:
        raise ValidationError(
            f"{len(missing_residues)} 个残基没有分子名（如 resid "
            f"{missing_residues[:5]}）；请补 naming.from_data 或 naming.residues"
        )

    missing_atoms = np.nonzero(atom_names == "")[0]
    if missing_atoms.size:
        shown = [int(i) + 1 for i in missing_atoms[:5]]
        raise ValidationError(
            f"{missing_atoms.size} 个原子没有原子名（如 atom {shown}）；"
            "请补 naming.from_data 或 naming.atoms"
        )


def _require_selectable(universe, kind: str, values: np.ndarray) -> None:
    """名字要能直接写进选择串：不能带空格，也不能撞选择串关键字。"""
    for value in sorted(set(values)):
        if any(ch.isspace() for ch in value):
            raise ValidationError(
                f"{kind} 名字 {value!r} 含空白，无法写进选择串", where="naming"
            )
        # 关键字都是纯字母；带数字的名字（C1、H2）不会撞
        if not value.isalpha():
            continue
        try:
            universe.select_atoms(f"{kind} {value}")
        except Exception as exc:  # MDAnalysis 抛 SelectionError
            raise ValidationError(
                f"{kind} 名字 {value!r} 与选择串关键字冲突，请换一个名字"
                f"（如 WAT、SOL）",
                where="naming",
            ) from exc


def _elements_from_mass(types: np.ndarray, masses: np.ndarray) -> np.ndarray:
    symbols: dict[str, str] = {}
    for type_value in np.unique(types):
        mass = float(masses[types == type_value][0])
        symbols[str(type_value)] = _element_of(mass, str(type_value))
    mapping = np.vectorize(lambda t: symbols[str(t)], otypes=[object])
    return mapping(types)


def _element_of(mass: float, type_value: str) -> str:
    symbol, reference = min(ELEMENT_MASSES.items(), key=lambda kv: abs(kv[1] - mass))
    if abs(reference - mass) > MASS_TOLERANCE:
        raise ValidationError(
            f"type {type_value} 的质量 {mass:g} 对不上已知元素（最近的是 "
            f"{symbol} {reference:g}）",
            where="naming.elements",
        )
    return symbol


def _set_attribute(universe, name: str, values: np.ndarray) -> None:
    if hasattr(universe.atoms, name):
        raise ValidationError(
            f"拓扑里已经有 {name} 属性，无法再用 naming 覆盖", where="naming"
        )
    universe.add_TopologyAttr(name, values)
