"""分析注册表：扫描 analyses/ 下的模块，读取自描述常量，生成执行计划。

每个分析是 `mdanal/analyses/` 下的一个 .py 文件，文件名就是分析名；模块顶部的
`SLOTS` / `PARAMS` / `LABELS` 等常量描述它需要什么。核心只依赖这些常量，不登记、
不引用具体分析。
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..errors import ValidationError
from ..plot.annotations import parse as parse_annotations
from ..plot.settings import parse_plot
from .system import SystemConfig

ANALYSES_PACKAGE = "mdanal.analyses"
ANALYSES_DIR = Path(__file__).resolve().parent.parent / "analyses"

RESERVED_KEYS = {"name", "tag", "sel", "annotate", "section", "plot"}
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
KNOWN_REQUIREMENTS = {"velocities"}
COORDINATE_NEEDS = ("in_box", "continuous", "any")
PARAM_KEYS = {"type", "default", "unit", "min", "max", "choices", "help"}
SUPPORTED_TYPES = (bool, int, float, str, list, tuple)
COMPARE_KEYS = {"table", "x", "y", "box_axis"}


@dataclass
class ImportFailure:
    """一个模块无法加载或声明不合法。"""

    name: str
    path: str
    category: str
    detail: str
    declaration: AnalysisDef | None = None


@dataclass(frozen=True)
class AnalysisDef:
    """一个分析的静态定义，来自模块常量。"""

    name: str
    module: str
    slots: tuple[str, ...]
    params: Mapping[str, Mapping[str, Any]]
    labels: Mapping[str, Mapping[str, str]]
    column_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    package: Mapping[str, str] | None = None
    coordinates: str = "any"
    mutates_positions: bool = False
    compare: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Discovery:
    """一次扫描的结果：可用的定义 + 失败原因。"""

    definitions: Mapping[str, AnalysisDef]
    failures: tuple[ImportFailure, ...] = ()


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
    annotations: tuple[dict[str, Any], ...] = ()
    section: tuple[int, int] | None = None
    window: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    plot: Mapping[str, Any] = field(default_factory=dict)

    @property
    def needs_velocity(self) -> bool:
        return "velocities" in self.definition.requires

    @property
    def mutates_positions(self) -> bool:
        return self.definition.mutates_positions

    @property
    def view(self) -> str:
        """该分析实际使用的坐标视图。"""
        if self.definition.coordinates == "continuous":
            return "continuous"
        return "in_box"


# --------------------------------------------------------------------------- #
# 发现与校验
# --------------------------------------------------------------------------- #


def load_registry() -> dict[str, AnalysisDef]:
    """返回全部可用的分析定义；加载失败的模块不在这里，见 `discover()`。"""
    return dict(discover().definitions)


def discover() -> Discovery:
    """扫描 analyses/ 并校验声明；导入失败按原因分类，不中断其他模块。"""
    definitions: dict[str, AnalysisDef] = {}
    failures: list[ImportFailure] = []

    for path in sorted(ANALYSES_DIR.glob("*.py")):
        name = path.stem
        if name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{ANALYSES_PACKAGE}.{name}")
        except SyntaxError as exc:
            failures.append(
                ImportFailure(
                    name, path.name, "语法错误", f"{exc.msg}（第 {exc.lineno} 行）"
                )
            )
            continue
        except ModuleNotFoundError as exc:
            missing = exc.name or str(exc)
            category = (
                "插件内部导入错误"
                if missing.split(".")[0] == "mdanal"
                else "缺可选依赖"
            )
            failures.append(ImportFailure(name, path.name, category, missing))
            continue
        except ImportError as exc:
            failures.append(
                ImportFailure(name, path.name, "插件内部导入错误", str(exc))
            )
            continue
        except Exception as exc:  # noqa: BLE001 - 插件顶层代码的任何异常都要归类
            failures.append(
                ImportFailure(
                    name, path.name, "插件代码异常", f"{type(exc).__name__}: {exc}"
                )
            )
            continue

        try:
            definitions[name] = _definition_from_module(name, module, path)
        except ValidationError as exc:
            failures.append(ImportFailure(name, path.name, "声明错误", str(exc)))

    for failure in failures:
        if failure.declaration is None:
            failure.declaration = _definition_from_source(
                ANALYSES_DIR / failure.path, failure.name
            )
    return Discovery(definitions, tuple(failures))


_TYPE_NAMES = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
    "list": list,
    "tuple": tuple,
}


def _eval_constant(node: ast.AST) -> Any:
    """读字面量常量；额外允许 float/int/str/bool/list/tuple 这些类型名。"""
    if isinstance(node, ast.Name) and node.id in _TYPE_NAMES:
        return _TYPE_NAMES[node.id]
    if isinstance(node, ast.Dict):
        result = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                raise ValueError("不支持字典展开")
            result[_eval_constant(key)] = _eval_constant(value)
        return result
    if isinstance(node, ast.List):
        return [_eval_constant(item) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_constant(item) for item in node.elts)
    return ast.literal_eval(node)


def _definition_from_source(path: Path, name: str) -> AnalysisDef | None:
    """不导入模块，用 AST 读取字面量常量；语法错或常量不全时返回 None。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return None

    values: dict[str, Any] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                values[node.targets[0].id] = _eval_constant(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue
    if not {"SLOTS", "PARAMS", "LABELS"} <= set(values):
        return None
    try:
        return _definition_from_module(name, SimpleNamespace(**values), path)
    except ValidationError:
        return None


def _definition_from_module(name: str, module: Any, path: Path) -> AnalysisDef:
    where = path.name
    slots = _normalise_slots(getattr(module, "SLOTS", None), where)
    params = _normalise_params(getattr(module, "PARAMS", None), where)
    labels = _normalise_labels(getattr(module, "LABELS", None), where)

    coordinates = getattr(module, "COORDINATES", "any")
    if coordinates not in COORDINATE_NEEDS:
        raise ValidationError(
            f"COORDINATES 只能是 {list(COORDINATE_NEEDS)}，收到 {coordinates!r}",
            where=f"{where}:COORDINATES",
        )

    requires = tuple(getattr(module, "REQUIRES", ()))
    if any(not isinstance(item, str) for item in requires):
        raise ValidationError("REQUIRES 必须是字符串元组", where=f"{where}:REQUIRES")
    unknown = set(requires) - KNOWN_REQUIREMENTS
    if unknown:
        raise ValidationError(
            f"未知依赖 {sorted(unknown)}；已知 {sorted(KNOWN_REQUIREMENTS)}",
            where=f"{where}:REQUIRES",
        )

    package = _normalise_package(getattr(module, "PACKAGE", None), where)
    compare = _normalise_compare(getattr(module, "COMPARE", None), where)

    mutates = getattr(module, "MUTATES_POSITIONS", False)
    if not isinstance(mutates, bool):
        raise ValidationError(
            "MUTATES_POSITIONS 必须是布尔值", where=f"{where}:MUTATES_POSITIONS"
        )

    return AnalysisDef(
        name=name,
        module=f"{ANALYSES_PACKAGE}.{name}",
        slots=slots,
        params=params,
        labels=labels,
        column_labels=_normalise_column_labels(
            getattr(module, "COLUMN_LABELS", None), where
        ),
        requires=requires,
        package=package,
        coordinates=str(coordinates),
        mutates_positions=mutates,
        compare=compare,
    )


def _normalise_slots(value: Any, where: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValidationError("SLOTS 必须是非空字符串元组", where=f"{where}:SLOTS")
    if len(set(value)) != len(value):
        raise ValidationError("SLOTS 不能重复", where=f"{where}:SLOTS")
    return tuple(value)


def _normalise_params(value: Any, where: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise ValidationError("PARAMS 必须是映射（可为 {}）", where=f"{where}:PARAMS")
    return {
        str(key): _param_spec(str(key), item, where)
        for key, item in value.items()
    }


def _param_spec(name: str, value: Any, where: str) -> dict[str, Any]:
    here = f"{where}:PARAMS.{name}"
    if isinstance(value, Mapping):
        unknown = set(value) - PARAM_KEYS
        if unknown:
            raise ValidationError(
                f"未知字段 {sorted(unknown)}；允许 {sorted(PARAM_KEYS)}", where=here
            )
        if "default" not in value:
            raise ValidationError("缺少 default", where=here)
        spec = dict(value)
    else:
        spec = {"default": value}

    default = spec["default"]
    expected = spec.get("type")
    if expected is None:
        expected = _infer_type(default, here)
    expected = _normalise_type(expected, here)
    spec["type"] = expected

    for key in ("unit", "help"):
        if key in spec and not isinstance(spec[key], str):
            raise ValidationError(f"{key} 必须是字符串", where=here)
    if "choices" in spec:
        choices = tuple(spec["choices"])
        if not choices:
            raise ValidationError("choices 不能为空", where=here)
        spec["choices"] = choices
    for key in ("min", "max"):
        if key in spec and not isinstance(spec[key], (int, float)):
            raise ValidationError(f"{key} 必须是数值", where=here)

    _check_value(default, spec, here)
    return spec


def _infer_type(value: Any, where: str) -> type:
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    if isinstance(value, list):
        return list
    if isinstance(value, tuple):
        return tuple
    raise ValidationError(
        f"无法从默认值 {value!r} 推断类型；请显式写 type", where=where
    )


def _normalise_type(expected: Any, where: str) -> Any:
    candidates = expected if isinstance(expected, tuple) else (expected,)
    if not candidates or any(item not in SUPPORTED_TYPES for item in candidates):
        raise ValidationError(
            f"type 只能是 {[item.__name__ for item in SUPPORTED_TYPES]} 或其元组，"
            f"收到 {expected!r}",
            where=where,
        )
    return expected


def _matches(value: Any, expected: type) -> bool:
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected)


def _type_text(expected: Any) -> str:
    if isinstance(expected, tuple):
        return " / ".join(item.__name__ for item in expected)
    return expected.__name__


def _check_value(value: Any, spec: Mapping[str, Any], where: str) -> Any:
    expected = spec["type"]
    candidates = expected if isinstance(expected, tuple) else (expected,)
    normalised: Any = value
    if not any(_matches(value, item) for item in candidates):
        raise ValidationError(
            f"需要 {_type_text(expected)}，收到 {value!r}", where=where
        )
    choices = spec.get("choices")
    if choices and normalised not in choices:
        raise ValidationError(
            f"只能是 {list(choices)}，收到 {normalised!r}", where=where
        )
    for key, compare in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
        bound = spec.get(key)
        if bound is None:
            continue
        try:
            bad = compare(normalised, bound)
        except TypeError as exc:
            raise ValidationError(
                f"{key} 约束不适用于 {type(normalised).__name__}", where=where
            ) from exc
        if bad:
            raise ValidationError(
                f"必须{'≥' if key == 'min' else '≤'} {bound}，收到 {normalised!r}",
                where=where,
            )
    return normalised


def _normalise_labels(value: Any, where: str) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or not value:
        raise ValidationError("LABELS 必须包含 zh 与 en", where=f"{where}:LABELS")
    labels: dict[str, dict[str, str]] = {}
    for lang in ("zh", "en"):
        table = value.get(lang)
        if not isinstance(table, Mapping):
            raise ValidationError(
                f"LABELS.{lang} 必须是映射", where=f"{where}:LABELS"
            )
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in table.items()):
            raise ValidationError(
                f"LABELS.{lang} 的键与值都必须是字符串", where=f"{where}:LABELS"
            )
        labels[lang] = dict(table)
    return labels


def _normalise_column_labels(
    value: Any, where: str
) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not value:
        raise ValidationError(
            "COLUMN_LABELS 必须是 {zh: {...}, en: {...}}", where=f"{where}:COLUMN_LABELS"
        )
    labels: dict[str, dict[str, str]] = {}
    for lang in ("zh", "en"):
        table = value.get(lang)
        if not isinstance(table, Mapping) or not table:
            raise ValidationError(
                f"COLUMN_LABELS.{lang} 必须是非空映射",
                where=f"{where}:COLUMN_LABELS",
            )
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in table.items()):
            raise ValidationError(
                f"COLUMN_LABELS.{lang} 的键与值都必须是字符串",
                where=f"{where}:COLUMN_LABELS",
            )
        labels[lang] = dict(table)
    return labels


def _normalise_package(value: Any, where: str) -> Mapping[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not isinstance(value.get("name"), str):
        raise ValidationError(
            "PACKAGE 必须是 {name: 包名, min_version: 版本} 或 None",
            where=f"{where}:PACKAGE",
        )
    return {
        "name": value["name"],
        "min_version": str(value.get("min_version", "")),
    }


def _normalise_compare(value: Any, where: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValidationError("COMPARE 必须是映射或 None", where=f"{where}:COMPARE")
    unknown = set(value) - COMPARE_KEYS
    if unknown:
        raise ValidationError(
            f"未知字段 {sorted(unknown)}；允许 {sorted(COMPARE_KEYS)}",
            where=f"{where}:COMPARE",
        )
    if not isinstance(value.get("table"), str):
        raise ValidationError("COMPARE.table 必须是字符串", where=f"{where}:COMPARE")
    if not isinstance(value.get("x"), str):
        raise ValidationError("COMPARE.x 必须是字符串", where=f"{where}:COMPARE")
    y = value.get("y")
    if not isinstance(y, (list, tuple)) or not all(isinstance(item, str) for item in y):
        raise ValidationError("COMPARE.y 必须是字符串列表", where=f"{where}:COMPARE")
    if "box_axis" in value and not isinstance(value["box_axis"], bool):
        raise ValidationError(
            "COMPARE.box_axis 必须是布尔值", where=f"{where}:COMPARE"
        )
    return {
        "table": value["table"],
        "x": value["x"],
        "y": list(y),
        "box_axis": bool(value.get("box_axis", False)),
    }


# --------------------------------------------------------------------------- #
# 生成计划
# --------------------------------------------------------------------------- #


def build_plan(
    cfg: SystemConfig,
    registry: Mapping[str, AnalysisDef],
    failures: Sequence[ImportFailure] = (),
) -> list[PlanItem]:
    """把 system.yaml 的 analyses 列表变成计划；一次报出全部问题。"""
    problems: list[str] = []
    items: list[PlanItem] = []
    failed = {failure.name: failure for failure in failures}

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
            failure = failed.get(name)
            if failure is not None:
                problems.append(
                    f"第 {index} 条的分析 {name!r} 加载失败："
                    f"{failure.category}（{failure.detail}）"
                )
            else:
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

        try:
            section = _parse_section(entry.get("section"), where)
            plot_settings = parse_plot(entry.get("plot"), f"{where}.plot")
            window = dict(plot_settings.get("window") or {})
        except ValidationError as exc:
            problems.append(str(exc))
            continue

        params = {key: spec["default"] for key, spec in definition.params.items()}
        for key, value in entry.items():
            if key in RESERVED_KEYS:
                continue
            spec = definition.params.get(key)
            if spec is None:
                continue  # 未知字段已单独报告
            try:
                params[key] = _check_value(value, spec, where=f"{where}.{key}")
            except ValidationError as exc:
                problems.append(str(exc))

        try:
            annotations = parse_annotations(
                entry.get("annotate"), f"analyses[{index}]"
            )
        except ValidationError as exc:
            problems.append(str(exc))
            continue

        items.append(
            PlanItem(
                order=index,
                name=name,
                tag=tag,
                directory=f"{name}-{tag}" if tag else name,
                selections=tuple(str(s) for s in selections),
                params=params,
                definition=definition,
                annotations=annotations,
                section=section,
                window=window,
                plot=plot_settings,
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


def _parse_section(value: Any, where: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        raise ValidationError(
            "section 必须是 [起, 止] 两个整数（相对体系窗口）", where=f"{where}.section"
        )
    start, stop = value
    if start < 0 or stop <= start:
        raise ValidationError(
            f"section 需满足 0 ≤ 起 < 止，收到 {[start, stop]}", where=f"{where}.section"
        )
    return (start, stop)


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
            problems.append(f"{item.name} 需要第三方包 {name}，当前环境未安装")
            continue

        minimum = package.get("min_version") or ""
        if minimum and _version_less(installed, minimum):
            problems.append(f"{item.name} 需要 {name} >= {minimum}，当前为 {installed}")
    return problems


def check_requirements(plan: Sequence[PlanItem], universe) -> list[str]:
    """检查轨迹是否具备分析所需属性。"""
    problems: list[str] = []
    needs = {item.name for item in plan if item.needs_velocity}
    if needs and not universe.trajectory.ts.has_velocities:
        problems.append(f"以下分析需要速度，但轨迹不含速度列：{sorted(needs)}")
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
