"""命令行入口：figure-first。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .errors import MdanalError, ValidationError

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_RUNTIME = 4


def cmd_render(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from .figure.config import read_project
    from .figure.engine import render_project

    project = read_project(args.config)
    project = replace(
        project,
        lang=args.lang or project.lang,
        dpi=args.dpi or project.dpi,
        annotate=bool(args.annotate) or project.annotate,
    )
    out = render_project(project, args.out, force=args.force)
    print(f"输出：{out}")
    payload = json.loads((out / "project.json").read_text(encoding="utf-8"))
    for warning in payload.get("warnings") or []:
        print(f"提示：{warning}", file=sys.stderr)
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    from .figure.config import read_project
    from .figure.engine import check_project, check_warnings, source_warnings

    project = read_project(args.config)
    for warning in [*source_warnings(project), *check_warnings(project)]:
        print(f"提示：{warning}", file=sys.stderr)
    problems = check_project(project)
    if problems:
        print("\n发现的问题：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_VALIDATION
    print("图请求校验通过。")
    return EXIT_OK


def cmd_packs(args: argparse.Namespace) -> int:
    from .figure.catalog import discover_packs, pack_payload

    packs = discover_packs()
    if args.json:
        print(
            json.dumps(
                {name: pack_payload(pack) for name, pack in packs.items()},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    for name, pack in packs.items():
        products = ", ".join(pack.products) or "-"
        print(f"{name:<12} {products}")
    return EXIT_OK


def cmd_check_pack(args: argparse.Namespace) -> int:
    from .figure.catalog import load_pack

    pack = load_pack(args.name)
    print(f"图包 {pack.name}：{len(pack.products)} 个产品")
    for product in pack.products.values():
        print(f"  {product.id:<18}{product.kind:<8}{', '.join(product.requires)}")
    return EXIT_OK


def cmd_replot(args: argparse.Namespace) -> int:
    from .figure.overrides import read_overrides
    from .figure.replot import replot_from

    overrides = read_overrides(args.config) if args.config else None
    names = args.figure or [None]
    written = []
    for name in names:
        written.extend(
            replot_from(
                args.from_dir,
                args.out,
                name=name,
                lang=args.lang,
                dpi=args.dpi,
                force=args.force,
                overrides=overrides,
            )
        )
    print(f"输出：{args.out}（{len(written)} 张图）")
    return EXIT_OK


def cmd_help(args: argparse.Namespace) -> int:
    args.parser.print_help()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdanal",
        description="figure-first MD 分析：输入轨迹与图请求，输出 Panel/Figure",
    )
    parser.add_argument("--version", action="version", version=f"mdanal {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="命令")

    render = subparsers.add_parser("render", help="按 figures.yaml 计算并生成最终图")
    render.add_argument("--config", required=True, metavar="FILE", help="图请求配置")
    render.add_argument("--out", required=True, metavar="DIR", help="输出目录")
    render.add_argument("--lang", choices=("zh", "en"), help="覆盖语言")
    render.add_argument("--dpi", type=int, help="覆盖分辨率")
    render.add_argument("--annotate", action="store_true", help="在图内标注帧窗口与参数")
    render.add_argument("--force", action="store_true", help="覆盖本程序生成的输出")
    render.set_defaults(func=cmd_render)

    check = subparsers.add_parser("check", help="只校验图请求，不计算")
    check.add_argument("--config", required=True, metavar="FILE", help="图请求配置")
    check.set_defaults(func=cmd_check)

    packs_cmd = subparsers.add_parser("packs", help="列出图包与产品")
    packs_cmd.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    packs_cmd.set_defaults(func=cmd_packs)

    check_pack = subparsers.add_parser("check-pack", help="检查一个图包的 pack.json")
    check_pack.add_argument("name", help="图包名")
    check_pack.set_defaults(func=cmd_check_pack)

    replot = subparsers.add_parser("replot", help="从已有结果重绘；不读轨迹、不重算")
    replot.add_argument("--from", dest="from_dir", required=True, metavar="DIR",
                        help="render 结果根目录")
    replot.add_argument("--out", required=True, metavar="DIR", help="绘图输出目录")
    replot.add_argument("--figure", action="append", default=[], metavar="NAME",
                        help="只重绘指定最终图（可重复）")
    replot.add_argument("--lang", choices=("zh", "en"), help="覆盖语言")
    replot.add_argument("--dpi", type=int, help="覆盖分辨率")
    replot.add_argument("--config", metavar="FILE", help="plot 覆盖配置")
    replot.add_argument("--force", action="store_true", help="覆盖目标目录中的同名图片")
    replot.set_defaults(func=cmd_replot)

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
