"""分析注册表：读取 analyses.yaml、把 system.yaml 的分析条目变成可执行的计划。

本模块只做解析与校验，不导入任何分析实现，也不做任何计算。
"""

from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .errors import ValidationError
from .system import SystemConfig

API_VERSION = 1
RESERVED_KEYS = {"name", "tag", "sel"}
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
KNOWN_REQUIREMENTS = {"velocities"}


@dataclass(frozen=True)
class AnalysisDef:
    """一个分析的静态定义，来自 analyses.yaml。"""

    name: str
    module: str
    slots: tuple[str, ...]
    params: Mapping[str, Any]
    requires: tuple[str, ...]
    package: Mapping[str, str] | None
    labels: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class PlanItem:
    """system.yaml 中的一条分析，附解析后的落位与最终参数。"""

    order: int
    name: str
    tag: str | None
    directory: str
    selections: tuple[str, ...]
    params: Mapping[str, Any]
    definition: AnalysisDef

    @property
    def needs_velocity(self) -> bool:
        return "velocities" in self.definition.requires


# --------------------------------------------------------------------------- #
# 读取注册表
# --------------------------------------------------------------------------- #


def load_registry(path: str | Path) -> dict[str, AnalysisDef]:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValidationError("找不到分析定义文件", where=str(path))

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f"（第 {mark.line + 1} 行）" if mark is not None else ""
        raise ValidationError(f"YAML 语法错误{line}：{exc}", where=str(path)) from exc

    if not isinstance(data, dict):
        raise ValidationError("顶层必须是映射", where=str(path))

    version = data.pop("api_version", None)
    if version != API_VERSION:
        raise ValidationError(
            f"api_version 必须是 {API_VERSION}，收到 {version!r}",
            where=f"{path}:api_version",
        )
    if not data:
        raise ValidationError("未定义任何分析", where=str(path))

    registry: dict[str, AnalysisDef] = {}
    for name, block in data.items():
        registry[name] = _parse_definition(str(name), block, path)
    return registry


def _parse_definition(name: str, block: Any, path: Path) -> AnalysisDef:
    where = f"{path}:{name}"
    if not isinstance(block, dict):
        raise ValidationError("分析定义必须是映射", where=where)

    allowed = {"module", "slots", "params", "requires", "package", "labels"}
    unknown = set(block) - allowed
    if unknown:
        raise ValidationError(
            f"未知字段 {sorted(unknown)}；允许 {sorted(allowed)}", where=where
        )

    slots = block.get("slots")
    if (
        not isinstance(slots, (list, tuple))
        or not slots
        or not all(isinstance(s, str) and s for s in slots)
    ):
        raise ValidationError("slots 必须是非空字符串列表", where=f"{where}:slots")
    if len(set(slots)) != len(slots):
        raise ValidationError("slots 不能重复", where=f"{where}:slots")

    params = block.get("params", {})
    if not isinstance(params, dict):
        raise ValidationError("params 必须是映射", where=f"{where}:params")

    requires = block.get("requires", [])
    if not isinstance(requires, (list, tuple)) or not all(
        isinstance(r, str) for r in requires
    ):
        raise ValidationError("requires 必须是字符串列表", where=f"{where}:requires")
    unknown_req = set(requires) - KNOWN_REQUIREMENTS
    if unknown_req:
        raise ValidationError(
            f"未知依赖 {sorted(unknown_req)}；已知 {sorted(KNOWN_REQUIREMENTS)}",
            where=f"{where}:requires",
        )

    package = block.get("package")
    if package is not None:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise ValidationError(
                "package 必须是 {name: 包名, min_version: 版本} 或 null",
                where=f"{where}:package",
            )
        package = {
            "name": package["name"],
            "min_version": str(package.get("min_version", "")),
        }

    labels = block.get("labels", {})
    if not isinstance(labels, dict) or not labels:
        raise ValidationError(
            "labels 必须包含 zh 与 en 两套", where=f"{where}:labels"
        )
    for lang in ("zh", "en"):
        table = labels.get(lang)
        if not isinstance(table, dict):
            raise ValidationError(f"labels.{lang} 必须是映射", where=f"{where}:labels")

    module = block.get("module", f"analyses.{name}")
    if not isinstance(module, str):
        raise ValidationError("module 必须是字符串", where=f"{where}:module")

    return AnalysisDef(
        name=name,
        module=module,
        slots=tuple(slots),
        params=dict(params),
        requires=tuple(requires),
        package=package,
        labels={lang: dict(table) for lang, table in labels.items()},
    )


# --------------------------------------------------------------------------- #
# 生成计划
# --------------------------------------------------------------------------- #


def build_plan(
    cfg: SystemConfig, registry: Mapping[str, AnalysisDef]
) -> list[PlanItem]:
    """把 system.yaml 的 analyses 列表变成计划；一次报出全部问题。"""
    problems: list[str] = []
    items: list[PlanItem] = []

    if not cfg.analyses:
        raise ValidationError(
            "analyses 为空，没有要运行的分析", where=f"{cfg.yaml_path}:analyses"
        )

    for index, entry in enumerate(cfg.analyses, start=1):
        where = f"{cfg.yaml_path}:analyses[{index}]"
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"第 {index} 条缺少 name")
            continue
        if name not in registry:
            problems.append(
                f"第 {index} 条的分析 {name!r} 不存在；可用 {sorted(registry)}"
            )
            continue

        definition = registry[name]
        allowed = RESERVED_KEYS | set(definition.params)
        unknown = set(entry) - allowed
        if unknown:
            problems.append(
                f"第 {index} 条（{name}）含未知字段 {sorted(unknown)}；"
                f"该分析允许 {sorted(allowed)}"
            )

        tag = entry.get("tag")
        if tag is not None and (not isinstance(tag, str) or not TAG_PATTERN.match(tag)):
            problems.append(
                f"第 {index} 条（{name}）的 tag 非法：{tag!r}；只允许字母、数字、_ . -"
            )
            continue

        selections = entry.get("sel")
        if not isinstance(selections, (list, tuple)):
            problems.append(
                f"第 {index} 条（{name}）缺少 sel；该分析需要 {len(definition.slots)} 个选择 "
                f"{list(definition.slots)}"
            )
            continue
        if len(selections) != len(definition.slots):
            problems.append(
                f"第 {index} 条（{name}）的 sel 有 {len(selections)} 个，"
                f"需要 {len(definition.slots)} 个 {list(definition.slots)}"
            )
            continue

        params = dict(definition.params)
        params.update({k: v for k, v in entry.items() if k not in RESERVED_KEYS})

        items.append(
            PlanItem(
                order=index,
                name=name,
                tag=tag,
                directory=f"{name}-{tag}" if tag else name,
                selections=tuple(str(s) for s in selections),
                params=params,
                definition=definition,
            )
        )

    duplicates = _duplicate_directories(items)
    for directory, orders in duplicates.items():
        problems.append(
            f"输出子目录 {directory!r} 被第 {orders} 条重复使用；给其中一条加唯一 tag"
        )

    if problems:
        raise ValidationError("\n".join(problems), where=str(cfg.yaml_path))

    return items


def _duplicate_directories(items: Sequence[PlanItem]) -> dict[str, list[int]]:
    seen: dict[str, list[int]] = {}
    for item in items:
        seen.setdefault(item.directory, []).append(item.order)
    return {d: orders for d, orders in seen.items() if len(orders) > 1}


# --------------------------------------------------------------------------- #
# 依赖检查
# --------------------------------------------------------------------------- #


def check_packages(plan: Sequence[PlanItem]) -> list[str]:
    """检查第三方包是否安装、版本是否满足下限。"""
    problems: list[str] = []
    for item in plan:
        package = item.definition.package
        if not package:
            continue
        name = package["name"]
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            problems.append(
                f"{item.name} 需要第三方包 {name}，当前环境未安装"
            )
            continue

        minimum = package.get("min_version") or ""
        if minimum and _version_less(installed, minimum):
            problems.append(
                f"{item.name} 需要 {name} >= {minimum}，当前为 {installed}"
            )
    return problems


def check_requirements(plan: Sequence[PlanItem], universe) -> list[str]:
    """检查轨迹是否具备分析所需属性。"""
    problems: list[str] = []
    needs = {item.name for item in plan if item.needs_velocity}
    if needs and not universe.trajectory.ts.has_velocities:
        problems.append(
            f"以下分析需要速度，但轨迹不含速度列：{sorted(needs)}"
        )
    return problems


def _version_less(installed: str, minimum: str) -> bool:
    try:
        from packaging.version import Version
    except ImportError:  # 没有 packaging 时只做存在性检查
        return False
    try:
        return Version(installed) < Version(minimum)
    except Exception:
        return False
