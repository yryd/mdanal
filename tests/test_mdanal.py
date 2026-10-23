"""集成测试。需要 MDANAL_SYSTEM 指向一个含 system.yaml 与轨迹的目录，未设置时整组跳过。"""

from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from mdanal import cli
from mdanal import registry as registry_module
from mdanal.errors import ValidationError
from mdanal.registry import build_plan, check_packages, load_registry
from mdanal.system import load_universe, read_system, resolve_group

_SYSTEM_ENV = os.environ.get("MDANAL_SYSTEM")
SYSTEM = Path(_SYSTEM_ENV) if _SYSTEM_ENV else None

pytestmark = pytest.mark.skipif(
    SYSTEM is None or not (SYSTEM / "system.yaml").is_file(),
    reason="未设置 MDANAL_SYSTEM，或该目录下没有 system.yaml",
)


def _write_system(tmp_path: Path, data_lmp: Path, traj: Path, analyses: str, frames: str = "[400, 402]") -> Path:
    content = f"""\
name: probe
topology: {data_lmp}
trajectory: {traj}
timestep_fs: 1.0
dump_every: 10000
frames: {frames}
groups:
  all_atoms: "all"
analyses:
{analyses}
"""
    path = tmp_path / "system.yaml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def real():
    cfg = read_system(SYSTEM)
    registry = load_registry(cli.REGISTRY_PATH)
    return cfg, registry


def test_registry_has_six_analyses(real):
    _, registry = real
    assert set(registry) == {"density", "lineardensity", "rdf", "hbond", "msd", "velocity"}
    assert registry["hbond"].slots == ("donor", "hydrogen", "acceptor")
    assert registry["velocity"].requires == ("velocities",)


def test_plan_from_real_system(real):
    cfg, registry = real
    plan = build_plan(cfg, registry)
    assert [item.order for item in plan] == list(range(1, len(plan) + 1))
    for item in plan:
        expected = f"{item.name}-{item.tag}" if item.tag else item.name
        assert item.directory == expected
    assert len({item.directory for item in plan}) == len(plan)


def test_missing_system_yaml(tmp_path):
    with pytest.raises(ValidationError, match="找不到 system.yaml"):
        read_system(tmp_path)


def test_wrong_selection_count(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: rdf, sel: ["all"]}',
    )
    with pytest.raises(ValidationError, match="需要 2 个"):
        build_plan(read_system(path), registry)


def test_unknown_analysis(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: foo, sel: ["all"]}'
    )
    with pytest.raises(ValidationError, match="不存在"):
        build_plan(read_system(path), registry)


def test_unknown_parameter(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: ["all"], deltax: 1}',
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), registry)


def test_duplicate_directory(real, tmp_path):
    cfg, registry = real
    analyses = '  - {name: msd, sel: ["all"]}\n  - {name: msd, sel: ["all"]}'
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    with pytest.raises(ValidationError, match="重复使用"):
        build_plan(read_system(path), registry)


def test_empty_selection_is_rejected(real):
    cfg, _ = real
    universe = load_universe(cfg)
    with pytest.raises(ValidationError, match="解析为空"):
        resolve_group(cfg, universe, "type 3-13")


def test_density_and_msd_end_to_end(real, tmp_path):
    cfg, _ = real
    analyses = (
        '  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y}\n'
        '  - {name: msd, sel: [all_atoms]}'
    )
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, analyses)
    out = tmp_path / "out"

    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0

    density_csv = out / "density-xz" / "tables" / "density_xz.csv"
    assert density_csv.is_file()
    table = pd.read_csv(density_csv, encoding="utf-8-sig")
    assert list(table.columns) == ["x (Å)", "z (Å)", "数密度 (Å^-3)"]

    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    meta = provenance["analyses"][0]["meta"]
    extent = meta["grid_extent"]
    delta = float(meta["delta"])
    # Σρ · Δa · Δb · L_axis = 原子数（L_axis 为网格沿求和方向的覆盖长度）
    total = float(table["数密度 (Å^-3)"].sum()) * delta * delta * extent[meta["sum_axis"]]
    assert total == pytest.approx(selection_count(cfg, "all"), rel=1e-9)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


def test_existing_output_refused(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_force_replaces_previous_output(real, tmp_path):
    cfg, _ = real
    first_cfg = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(first_cfg), "--out", str(out)]) == 0
    assert (out / "msd").is_dir()

    second_cfg = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y}'
    )
    assert cli.main(["run", "--system", str(second_cfg), "--out", str(out), "--force"]) == 0
    assert (out / "density-xz").is_dir()
    assert not (out / "msd").exists()


def test_deterministic_tables(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: [all_atoms]}')
    first, second = tmp_path / "a", tmp_path / "b"
    assert cli.main(["run", "--system", str(path), "--out", str(first)]) == 0
    assert cli.main(["run", "--system", str(path), "--out", str(second)]) == 0
    assert (first / "msd/tables/msd.csv").read_bytes() == (second / "msd/tables/msd.csv").read_bytes()


def test_list_commands_run(real, capsys):
    assert cli.main(["list"]) == 0
    assert "density" in capsys.readouterr().out
    assert cli.main(["list", "--system", str(SYSTEM)]) == 0
    assert "将要运行的分析" in capsys.readouterr().out


def test_missing_package_reported(real, monkeypatch):
    cfg, registry = real
    plan = [item for item in build_plan(cfg, registry) if item.name == "velocity"]
    assert plan, "样例体系应包含 velocity"

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(registry_module.importlib.metadata, "version", missing)
    problems = check_packages(plan)
    assert problems and "未安装" in problems[0]


def selection_count(cfg, selection: str) -> int:
    universe = load_universe(cfg)
    return universe.select_atoms(selection).n_atoms
