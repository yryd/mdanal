"""新 figure-first 架构下的科学测试辅助。"""

from __future__ import annotations

from pathlib import Path

from mdanal.config.source import parse_source
from mdanal.figure.catalog import load_pack
from mdanal.figure.model import PanelRef
from mdanal.figure.runtime import SourceRuntime, compute_context

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def tiny_source(*, frames=(0, 20), names: bool = True, groups=None):
    data = {
        "topology": "data.lmp",
        "trajectory": "run.lammpstrj",
        "timestep_fs": 1.0,
        "dump_every": 5000,
        "frames": list(frames),
        "groups": groups
        or {"all": "all", "o13": "type 1 3", "oh": "type 5 6"},
    }
    if names:
        data["naming"] = {"from_data": "data.lmp"}
    return parse_source("tiny", data, base_dir=TINY, yaml_path=TINY / "figures.yaml")


def compute_pack(
    name: str,
    *,
    select: dict[str, str],
    compute: dict | None = None,
    frames=(0, 20),
    section=None,
    names: bool = True,
):
    pack = load_pack(name)
    ref = PanelRef(
        source="tiny",
        pack=name,
        product=pack.default_product,
        select=select,
        compute=compute or {},
        section=section,
        plot={},
    )
    runtime = SourceRuntime("tiny", tiny_source(frames=frames, names=names))
    ctx = compute_context(runtime, pack, ref)
    return dict(pack.compute(ctx)), ctx
