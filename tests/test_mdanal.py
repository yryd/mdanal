"""集成测试。只依赖真实体系目录，缺失时整组跳过。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

import importlib.metadata

from mdanal import cli
from mdanal import registry as registry_module
from mdanal.errors import ValidationError
from mdanal.registry import build_plan, check_packages, load_registry
from mdanal.system import load_universe, read_system, resolve_group

REPO = Path(__file__).resolve().parents[4]
DEFAULT_SYSTEM = REPO / "process" / "runs" / "003-systems" / "zgom" / "flow_F0p2"
SYSTEM = Path(os.environ.get("MDANAL_SYSTEM", DEFAULT_SYSTEM))

pytestmark = pytest.mark.skipif(
    not (SYSTEM / "system.yaml").is_file(),
    reason=f"缺少真实体系目录：{SYSTEM}",
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
  water_o: "type 17"
  walls: "resid 1 or resid 90"
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
    assert [item.order for item in plan] == [1, 2, 3, 4, 5, 6]
    assert [item.directory for item in plan] == [
        "density-xz", "density-xy", "rdf", "hbond", "msd", "velocity",
    ]
    assert len({item.directory for item in plan}) == len(plan)


def test_missing_system_yaml(tmp_path):
    with pytest.raises(ValidationError, match="找不到 system.yaml"):
        read_system(tmp_path)


def test_wrong_selection_count(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: rdf, sel: ["type 17"]}',
    )
    with pytest.raises(ValidationError, match="需要 2 个"):
        build_plan(read_system(path), registry)


def test_unknown_analysis(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory, '  - {name: foo, sel: ["type 17"]}'
    )
    with pytest.raises(ValidationError, match="不存在"):
        build_plan(read_system(path), registry)


def test_unknown_parameter(real, tmp_path):
    cfg, registry = real
    path = _write_system(
        tmp_path, cfg.topology, cfg.trajectory,
        '  - {name: msd, sel: ["type 17"], deltax: 1}',
    )
    with pytest.raises(ValidationError, match="未知字段"):
        build_plan(read_system(path), registry)


def test_duplicate_directory(real, tmp_path):
    cfg, registry = real
    analyses = '  - {name: msd, sel: ["type 17"]}\n  - {name: msd, sel: ["type 18"]}'
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
        '  - {name: density, tag: xz, sel: [water_o], sum_axis: y}\n'
        '  - {name: msd, sel: [water_o]}'
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
    assert total == pytest.approx(ow_count(cfg), rel=1e-9)

    assert (out / "msd" / "tables" / "msd.csv").is_file()
    figure = out / "density-xz" / "figures" / "density_xz.png"
    assert figure.is_file()
    width, _ = Image.open(figure).size
    nominal = 4.2 * 300
    assert 0.85 <= width / nominal <= 1.05


def test_existing_output_refused(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: ["type 17"]}')
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 3


def test_deterministic_tables(real, tmp_path):
    cfg, _ = real
    path = _write_system(tmp_path, cfg.topology, cfg.trajectory, '  - {name: msd, sel: ["type 17"]}')
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


def ow_count(cfg) -> int:
    universe = load_universe(cfg)
    return universe.select_atoms(cfg.groups["water_o"]).n_atoms
