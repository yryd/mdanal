"""测试辅助：临时 system.yaml、夹具 Universe、假分析的注册与运行。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import MDAnalysis as mda

import fake_analysis
from mdanal.config.registry import _definition_from_module, build_plan
from mdanal.config.system import load_universe, read_system
from mdanal.run.runner import RunOptions, execute, prepare

SYSTEM = Path(__file__).resolve().parent / "fixtures" / "tiny"
START, STOP = 0, 5  # 五帧窗口：够算寿命（4 帧滞后），且跑得快


def write_system(
    tmp_path: Path,
    data_lmp: Path,
    traj: Path,
    analyses: str,
    frames: str = f"[{START}, {STOP}]",
    extra: str = "",
) -> Path:
    content = f"""\
name: probe
topology: {data_lmp}
trajectory: {traj}
timestep_fs: 1.0
dump_every: 5000
frames: {frames}
{extra}groups:
  all_atoms: "all"
  tma_o: "type 1 3"
  tma_h: "type 5 6"
analyses:
{analyses}
"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "system.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def selection_count(cfg, selection: str) -> int:
    return load_universe(cfg).select_atoms(selection).n_atoms


def raw_universe(cfg) -> mda.Universe:
    """不做任何变换的 Universe，用于对照。"""
    return mda.Universe(
        str(cfg.topology),
        str(cfg.trajectory),
        format="LAMMPSDUMP",
        topology_format="data",
        dt=cfg.dt_ps,
    )


def split_trajectory(
    directory: Path, *, reset_second_steps: bool = False
) -> tuple[Path, Path, int]:
    """把夹具轨迹从中间切成两段，返回 (第一段, 第二段, 总帧数)。

    reset_second_steps=True 时把第二段每帧的 TIMESTEP 改成 0，模拟续跑归零。
    """
    lines = (SYSTEM / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("ITEM: TIMESTEP")]
    cut = starts[len(starts) // 2]
    first_lines = lines[:cut]
    second_lines = lines[cut:]
    if reset_second_steps:
        for index, line in enumerate(second_lines):
            if line.startswith("ITEM: TIMESTEP"):
                second_lines[index + 1] = "0\n"
    first = directory / "a.lammpstrj"
    second = directory / "b.lammpstrj"
    first.write_text("".join(first_lines), encoding="utf-8")
    second.write_text("".join(second_lines), encoding="utf-8")
    return first, second, len(starts)


def constant_box_trajectory(directory: Path) -> Path:
    """把夹具轨迹每一帧的 BOX BOUNDS 改成第一帧的，用于固定盒测试。"""
    lines = (SYSTEM / "run.lammpstrj").read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("ITEM: BOX BOUNDS")]
    first = lines[starts[0] + 1 : starts[0] + 4]
    for index in starts:
        lines[index + 1 : index + 4] = first
    path = directory / "constant.lammpstrj"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def segmented_system(directory: Path, trajectory: str) -> Path:
    """照抄夹具体系，只换轨迹与绝对路径。"""
    content = (SYSTEM / "system.yaml").read_text(encoding="utf-8")
    content = content.replace("topology: data.lmp", f"topology: {SYSTEM / 'data.lmp'}")
    content = content.replace("trajectory: run.lammpstrj", f"trajectory: {trajectory}")
    content = content.replace(
        "from_data: data.lmp", f"from_data: {SYSTEM / 'data.lmp'}"
    )
    path = directory / "system.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def fake_definition(module: str = "fake_analysis"):
    definition = _definition_from_module("fake", fake_analysis, Path("fake_analysis.py"))
    return dataclasses.replace(definition, module=module)


def fake_registry() -> dict:
    return {"fake": fake_definition()}


def load_fake(cfg_path, *, memory: bool = True):
    """读配置、建假分析计划并准备视图；返回 Prepared。"""
    cfg = read_system(cfg_path)
    plan = build_plan(cfg, fake_registry())
    return prepare(cfg, plan, memory=memory)


def run_fake(
    cfg_path,
    out,
    *,
    lang: str = "zh",
    dpi: int = 300,
    force: bool = False,
    aligned: bool = False,
    memory: bool = True,
):
    """用假分析跑一次完整流程，返回 (SystemConfig, Prepared)。"""
    cfg = read_system(cfg_path)
    plan = build_plan(cfg, fake_registry())
    prepared = prepare(cfg, plan, memory=memory)
    execute(
        prepared,
        out,
        RunOptions(lang=lang, dpi=dpi, force=force, aligned=aligned),
        {},
    )
    return cfg, prepared
