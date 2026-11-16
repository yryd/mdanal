#!/usr/bin/env python3
"""生成文档用图件：图库、快速开始、颜色页和改图示例。

只写 docs/assets 下的小图，不复制大轨迹；运行结果放在临时目录。
用法（仓库根目录）：
    python scripts/build_docs_assets.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from cycler import cycler

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from mdanal import cli  # noqa: E402
from mdanal.plot import chart  # noqa: E402
from mdanal.plot.settings import resolve_palette  # noqa: E402

ASSETS = ROOT / "docs" / "assets"
GALLERY = ASSETS / "gallery"
RECIPES = ASSETS / "recipes"
FIXTURE = ROOT / "tests" / "fixtures" / "tiny"
PALETTES = (
    "retro",
    "bright",
    "high-contrast",
    "high-vis",
    "light",
    "muted",
    "vibrant",
    "std-colors",
)


def run_cli(args: list[str]) -> None:
    code = cli.main(args)
    if code != 0:
        raise RuntimeError(f"命令失败（{code}）：{args}")


def copy_figure(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def write_recipe_system(path: Path, section: tuple[int, int], tag: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "system.yaml").write_text(
        f"""name: compare-{tag}
topology: {FIXTURE / 'data.lmp'}
trajectory: {FIXTURE / 'run.lammpstrj'}
timestep_fs: 1.0
dump_every: 5000
frames: [0, 5]
groups:
  all_atoms: "all"
analyses:
  - name: lineardensity
    sel: [all_atoms]
    dim: z
    binsize: 0.5
    section: [{section[0]}, {section[1]}]
""",
        encoding="utf-8",
    )


def build_palette_preview() -> None:
    names = list(PALETTES)
    colors = {name: resolve_palette(name, "docs") for name in names}
    max_colors = max(len(values) for values in colors.values())
    (ASSETS / "palettes.json").write_text(
        json.dumps(
            {
                "scienceplots": "2.2.2",
                "palettes": {name: list(values) for name, values in colors.items()},
                "fixed": {
                    "primary": chart.COLORS["primary"],
                    "secondary": chart.COLORS["secondary"],
                    "reference": chart.COLORS["reference"],
                    "guide": chart.COLORS["guide"],
                    "label": chart.COLORS["label"],
                },
                "density_colors": [
                    "#ffffff",
                    "#dcecf7",
                    "#9ec9e4",
                    "#4a90c2",
                    "#1d5b8f",
                    "#0b2d5c",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    plt.rcParams["font.family"] = ["Noto Serif CJK SC"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(15, 10))
    ax.set_xlim(0, 2.4 + max_colors * 1.45)
    ax.set_ylim(0, len(names) + 3.2)
    ax.axis("off")
    ax.set_title("SciencePlots 颜色循环", fontsize=14, loc="left")
    for row, name in enumerate(names):
        y = len(names) + 1 - row
        ax.text(0, y + 0.35, name, fontsize=10, ha="left", va="center")
        for index, color in enumerate(colors[name]):
            x = 2.4 + index * 1.45
            ax.add_patch(
                plt.Rectangle((x, y), 1.32, 0.7, color=color, lw=0)
            )
            ax.text(
                x + 0.66, y + 0.35, color,
                fontsize=5.8, ha="center", va="center",
                color="white" if index % 5 != 0 else "black",
            )
    # fixed colors and density gradient
    y = 0.55
    ax.text(0, y + 0.35, "固定主色 / 对照色", fontsize=9, va="center")
    for index, color in enumerate((chart.COLORS["primary"], chart.COLORS["secondary"])):
        ax.add_patch(plt.Rectangle((2.4 + index * 1.45, y), 1.32, 0.7, color=color, lw=0))
        ax.text(3.06 + index * 1.45, y + 0.35, color, fontsize=6, ha="center", va="center", color="white")
    ax.text(6.0, y + 0.35, "密度图色标（低 → 高）", fontsize=9, va="center")
    cmap = chart.density_cmap()
    for index in range(64):
        ax.add_patch(
            plt.Rectangle(
                (8.7 + index * 0.075, y), 0.075, 0.7,
                color=cmap(index / 63), lw=0,
            )
        )
    fig.savefig(ASSETS / "palette-preview.png", dpi=220, bbox_inches="tight")
    svg = ASSETS / "palette-preview.svg"
    fig.savefig(svg, bbox_inches="tight")
    # Matplotlib 的 SVG 会在路径行尾留空格；去掉，避免 diff --check 噪声
    svg.write_text(
        "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n",
        encoding="utf-8",
    )
    plt.close(fig)

    fig, axes = plt.subplots(2, 4, figsize=(12, 6), sharex=True, sharey=True)
    x = np.linspace(0, 10, 200)
    for ax, name in zip(axes.ravel(), names):
        palette = colors[name]
        for index in range(min(4, len(palette))):
            ax.plot(
                x, np.sin(x + index) * np.exp(-x / 8) + index * 0.15,
                color=palette[index], lw=1.2,
            )
        ax.set_title(name, fontsize=9)
        ax.set_xlim(0, 10)
    fig.tight_layout()
    fig.savefig(ASSETS / "palette-curves.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def build_gallery(tiny_out: Path) -> None:
    for directory in (
        "density-xy",
        "lineardensity",
        "rdf",
        "hbond",
        "hbond_type",
        "hbond_lifetime",
        "msd",
        "velocity",
    ):
        figures = sorted((tiny_out / directory / "figures").glob("*.png"))
        if not figures:
            raise RuntimeError(f"{directory} 没有图")
        copy_figure(figures[0], GALLERY / f"{directory}.png")


def build_quickstart(quick_out: Path, quick_replot: Path) -> None:
    copy_figure(quick_out / "msd/figures/msd.png", ASSETS / "quickstart-msd-zh.png")
    copy_figure(quick_replot / "msd/figures/msd.png", ASSETS / "quickstart-msd-en.png")


def build_recipes(tiny_out: Path, recipes: Path) -> None:
    def replot(name: str, config: Path, analysis: str, figure: str) -> None:
        target = recipes / name
        run_cli(
            [
                "replot", "--from", str(tiny_out), "--out", str(target),
                "--config", str(config),
            ]
        )
        copy_figure(target / analysis / "figures" / figure, RECIPES / name / figure)

    replot("clip", ROOT / "example/recipes/plot-clip.yaml",
           "density-xy", "density_xy.png")
    copy_figure(
        tiny_out / "density-xy/figures/density_xy.png",
        RECIPES / "clip" / "before.png",
    )
    shutil.move(RECIPES / "clip" / "density_xy.png", RECIPES / "clip" / "after.png")
    replot("annotate", ROOT / "example/recipes/plot-annotate.yaml",
           "lineardensity", "lineardensity_z.png")


def build_compare(temp: Path) -> None:
    roots = []
    for tag, section in (("a", (0, 1)), ("b", (1, 2))):
        source = temp / f"compare-{tag}"
        write_recipe_system(source, section, tag)
        out = temp / f"compare-{tag}-out"
        run_cli(["run", "--system", str(source / "system.yaml"), "--out", str(out)])
        roots.append(out)
    config = temp / "compare.yaml"
    config.write_text(
        f"""items:
  - {{root: {roots[0]}, label: frame 0}}
  - {{root: {roots[1]}, label: frame 1}}
figure:
  analysis: lineardensity
  align: left
  palette: bright
  xlim: [0, 45]
""",
        encoding="utf-8",
    )
    for name, palette in (("retro", "retro"), ("bright", "bright")):
        text = config.read_text(encoding="utf-8")
        text = text.replace("palette: bright", f"palette: {palette}")
        variant = temp / f"compare-{name}.yaml"
        variant.write_text(text, encoding="utf-8")
        out = temp / f"compare-{name}-out"
        run_cli(["compare", "--config", str(variant), "--out", str(out)])
        copy_figure(
            out / "lineardensity.png",
            RECIPES / "compare" / f"lineardensity-{name}.png",
        )




def build_template(temp: Path) -> None:
    """临时把模板放进 analyses/ 跑一遍，生成插件页的真实表和真实图。"""
    module_path = SRC / "mdanal" / "analyses" / "zz_template_preview.py"
    module_path.write_text(
        (ROOT / "example" / "analysis_template.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    try:
        system_dir = temp / "template-system"
        system_dir.mkdir()
        (system_dir / "system.yaml").write_text(
            f"""name: template-preview
topology: {FIXTURE / 'data.lmp'}
trajectory: {FIXTURE / 'run.lammpstrj'}
timestep_fs: 1.0
dump_every: 5000
frames: [0, 3]
groups:
  all_atoms: "all"
analyses:
  - name: zz_template_preview
    sel: [all_atoms]
""",
            encoding="utf-8",
        )
        out = temp / "template-out"
        run_cli(["run", "--system", str(system_dir / "system.yaml"), "--out", str(out)])
        target = ASSETS / "plugin-template"
        target.mkdir(parents=True, exist_ok=True)
        copy_figure(
            out / "zz_template_preview" / "figures" / "template.png",
            target / "template.png",
        )
        table = out / "zz_template_preview" / "tables" / "template.csv"
        target.joinpath("table-head.txt").write_text(
            "\n".join(table.read_text(encoding="utf-8-sig").splitlines()[:4]) + "\n",
            encoding="utf-8",
        )
    finally:
        module_path.unlink(missing_ok=True)
        for stale in (SRC / "mdanal" / "analyses" / "__pycache__").glob(
            "zz_template_preview*.pyc"
        ):
            stale.unlink(missing_ok=True)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    GALLERY.mkdir(parents=True, exist_ok=True)
    RECIPES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mdanal-docs-") as temp_name:
        temp = Path(temp_name)
        tiny_out = temp / "tiny"
        run_cli(
            ["run", "--system", str(FIXTURE), "--out", str(tiny_out), "--force"]
        )
        build_gallery(tiny_out)

        quick_out = temp / "quick"
        quick_replot = temp / "quick-replot"
        run_cli(
            [
                "run", "--system", str(ROOT / "example/quickstart"),
                "--out", str(quick_out), "--force",
            ]
        )
        run_cli(
            [
                "replot", "--from", str(quick_out), "--out", str(quick_replot),
                "--config", str(ROOT / "example/recipes/plot-en.yaml"),
                "--format", "png",
            ]
        )
        build_quickstart(quick_out, quick_replot)
        build_recipes(tiny_out, temp / "recipes")
        build_compare(temp)
        build_template(temp)
    build_palette_preview()
    print(f"文档资产已生成：{ASSETS}")


if __name__ == "__main__":
    main()
