"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import __version__
from .errors import MdanalError, UsageError, ValidationError
from .registry import (
    AnalysisDef,
    build_plan,
    check_packages,
    check_requirements,
    load_registry,
)
from .runner import Prepared, RunOptions, execute, prepare
from .system import (
    SystemConfig,
    UNKNOWN_INPUT_WARNING,
    read_system,
)

PROGRAM_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PROGRAM_DIR / "analyses.yaml"
DEFAULTS_PATH = PROGRAM_DIR / "defaults.yaml"
LABELS_PATH = PROGRAM_DIR / "labels.yaml"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_RUNTIME = 4

INPUT_LABELS = {
    "unwrapped": "未包裹",
    "wrapped": "包裹",
    "unknown": "无法判断",
}


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry(REGISTRY_PATH)
    if args.system:
        return _list_system(args.system, registry)
    _print_registry(registry)
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    prepared, problems, warnings = _prepare(args.system)
    _print_inspection(prepared, warnings)
    _raise_if_problems(problems)
    print("\n校验通过。")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    prepared, problems, warnings = _prepare(args.system)
    _print_inspection(prepared, warnings)
    _raise_if_problems(problems)

    defaults = _load_defaults()
    options = RunOptions(
        lang=args.lang or defaults["language"],
        dpi=args.dpi or int(defaults["dpi"]),
        annotate=bool(args.annotate or defaults["annotate"]),
        force=bool(args.force),
        figure_sizes={
            key: tuple(float(v) for v in size)
            for key, size in defaults["figure"].items()
        },
    )

    print()
    execute(
        prepared=prepared,
        outdir=args.out,
        options=options,
        common_labels=_load_labels(),
    )
    return EXIT_OK


def cmd_help(args: argparse.Namespace) -> int:
    args.parser.print_help()
    return EXIT_OK


# --------------------------------------------------------------------------- #
# 准备与打印
# --------------------------------------------------------------------------- #


def _prepare(path: str) -> tuple[Prepared, list[str], list[str]]:
    """读配置 → 建计划 → 查依赖 → 建视图 → 解析分组，返回 (输入, 问题, 提示)。"""
    cfg = read_system(path)
    registry = load_registry(REGISTRY_PATH)
    plan = build_plan(cfg, registry)

    problems: list[str] = list(check_packages(plan))
    prepared = prepare(cfg, plan)
    problems.extend(check_requirements(plan, prepared.views["in_box"]))
    warnings = [UNKNOWN_INPUT_WARNING] if cfg.input_state == "unknown" else []
    return prepared, problems, warnings


def _print_inspection(prepared: Prepared, warnings: Sequence[str]) -> None:
    cfg = prepared.cfg
    in_box = prepared.views["in_box"]
    print(f"体系：{cfg.name}（{cfg.directory}）")
    print(f"配置：{cfg.yaml_path.name}    分析：{len(prepared.plan)} 条")
    print(
        f"轨迹：{len(in_box.trajectory)} 帧    "
        f"窗口：[{prepared.start}, {prepared.stop})    原子：{in_box.atoms.n_atoms}"
    )
    print(f"输入：{_input_text(cfg)}")
    print(
        f"视图：原点 {_point(cfg.view.origin)}    "
        f"平移 {_point(cfg.view.shift)} Å"
    )
    if cfg.view.window:
        window = "、".join(
            f"{axis}=[{low:g}, {high:g}]" for axis, (low, high) in cfg.view.window.items()
        )
        print(f"      窗口 {window}")
    print(f"选择：按第 {prepared.selection_frame} 帧解析")

    print("\n分组解析：")
    for item in prepared.plan:
        for slot, value in zip(item.definition.slots, item.selections):
            group = prepared.groups[item.order][slot]
            origin = f"分组 {group.key}" if group.key else "选择串"
            print(
                f"  {item.directory:<18}{slot:<10}{value:<34}"
                f"{group.n_atoms:>7} 原子   （{origin}）"
            )

    if warnings:
        print()
        for message in warnings:
            print(f"提示：{message}")


def _input_text(cfg: SystemConfig) -> str:
    label = INPUT_LABELS.get(cfg.input_state, cfg.input_state)
    if cfg.input_state in ("unwrapped", "wrapped") and cfg.input_evidence:
        return f"{label}坐标（{cfg.input_evidence}）"
    return f"{label}坐标"


def _point(values: Sequence[float]) -> str:
    return "[" + ", ".join(f"{v:g}" for v in values) + "]"


def _raise_if_problems(problems: Sequence[str]) -> None:
    if not problems:
        return
    print("\n发现的问题：", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    raise ValidationError("\n".join(problems), where="校验未通过")


def _list_system(path: str, registry: Mapping[str, AnalysisDef]) -> int:
    cfg = read_system(path)
    print(f"体系：{cfg.name}")
    print(f"目录：{cfg.directory}")
    print(f"配置：{cfg.yaml_path}")
    print(f"拓扑：{cfg.topology.name}    轨迹：{cfg.trajectory.name}")
    print(
        f"时间步长：{cfg.timestep_fs} fs    "
        f"每帧时间：{cfg.dump_every * cfg.dt_ps:g} ps"
    )
    print(
        f"帧窗口：{list(cfg.frames)}（左闭右开）" if cfg.frames else "帧窗口：未指定（全帧）"
    )
    print(f"输入：{_input_text(cfg)}")
    print(
        f"视图：原点 {_point(cfg.view.origin)}    平移 {_point(cfg.view.shift)} Å"
    )

    print(f"\n具名分组（{len(cfg.groups)}）：")
    if cfg.groups:
        for key, selection in cfg.groups.items():
            print(f"  {key:<16} {selection}")
    else:
        print("  （无）")

    plan = build_plan(cfg, registry)
    print(f"\n将要运行的分析（{len(plan)}）：")
    print(f"  {'序号':<4}{'子目录':<18}{'分析':<12}{'视图':<12}选择")
    for item in plan:
        print(
            f"  {item.order:<6}{item.directory:<20}{item.name:<14}"
            f"{item.view:<14}{', '.join(item.selections)}"
        )
    return EXIT_OK


def _print_registry(registry: Mapping[str, AnalysisDef]) -> None:
    rows = []
    for name in sorted(registry):
        definition = registry[name]
        params = ", ".join(f"{k}={v}" for k, v in definition.params.items()) or "-"
        requires = ", ".join(definition.requires) or "-"
        rows.append(
            (
                name,
                ", ".join(definition.slots),
                params,
                requires,
                definition.coordinates,
                definition.module,
            )
        )

    headers = ("分析", "槽位", "默认参数", "依赖", "坐标需求", "模块")
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))
    ]
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


# --------------------------------------------------------------------------- #
# 配置读取
# --------------------------------------------------------------------------- #


def _load_defaults() -> dict[str, Any]:
    data = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MdanalError("defaults.yaml 顶层必须是映射", where=str(DEFAULTS_PATH))
    data.setdefault("language", "zh")
    data.setdefault("dpi", 300)
    data.setdefault("annotate", False)
    data.setdefault("figure", {"single": [3.5, 2.6]})
    return data


def _load_labels() -> dict[str, dict[str, str]]:
    """labels.yaml 按语言合并各分节，得到 {lang: {键: 文案}}。"""
    data = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8")) or {}
    merged: dict[str, dict[str, str]] = {}
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for lang, table in section.items():
            if isinstance(table, dict):
                merged.setdefault(lang, {}).update(table)
    return merged


# --------------------------------------------------------------------------- #
# 参数解析
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdanal",
        description="通用 MD 分析层：按体系目录下的 system.yaml 执行分析",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"mdanal {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="命令")

    run = subparsers.add_parser("run", help="执行 system.yaml 中列出的分析")
    run.add_argument("--system", required=True, metavar="PATH", help="体系目录或 system.yaml")
    run.add_argument("--out", required=True, metavar="DIR", help="输出目录")
    run.add_argument("--lang", choices=("zh", "en"), help="图内文字语言（默认取 defaults.yaml）")
    run.add_argument("--dpi", type=int, help="图片分辨率（默认取 defaults.yaml）")
    run.add_argument("--annotate", action="store_true", help="在图内标注帧窗口与参数")
    run.add_argument("--force", action="store_true", help="允许覆盖已存在的输出目录")
    run.set_defaults(func=cmd_run)

    check = subparsers.add_parser("check", help="只校验，不计算")
    check.add_argument("--system", required=True, metavar="PATH", help="体系目录或 system.yaml")
    check.set_defaults(func=cmd_check)

    listing = subparsers.add_parser("list", help="列出分析或体系信息")
    listing.add_argument("--system", metavar="PATH", help="查看某个体系的分组与计划")
    listing.set_defaults(func=cmd_list)

    help_cmd = subparsers.add_parser("help", help="显示帮助")
    help_cmd.set_defaults(func=cmd_help, parser=parser)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE

    try:
        return args.func(args)
    except UsageError as exc:
        print(f"用法错误：{exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValidationError as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return EXIT_VALIDATION
    except MdanalError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_RUNTIME
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
