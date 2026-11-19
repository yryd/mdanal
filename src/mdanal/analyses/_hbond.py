"""氢键家族共享的 HBA 构建与同运行缓存。"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from MDAnalysis.analysis.hydrogenbonds import HydrogenBondAnalysis

_CACHE: "OrderedDict[tuple, HydrogenBondAnalysis]" = OrderedDict()
_MAX_CACHE = 4


def _selection(group) -> str:
    indices = [int(value) + 1 for value in group.atoms.indices]
    return "bynum " + " ".join(str(value) for value in indices)


def build(ctx) -> HydrogenBondAnalysis:
    return HydrogenBondAnalysis(
        ctx.universe,
        donors_sel=_selection(ctx.groups["donor"]),
        hydrogens_sel=_selection(ctx.groups["hydrogen"]),
        acceptors_sel=_selection(ctx.groups["acceptor"]),
        d_a_cutoff=float(ctx.params["d_a_cutoff"]),
        d_h_a_angle_cutoff=float(ctx.params["d_h_a_angle_cutoff"]),
        update_selections=False,
    )


def _key(ctx) -> tuple:
    return (
        id(ctx.universe),
        int(ctx.start),
        int(ctx.stop),
        tuple(int(value) for value in ctx.groups["donor"].atoms.indices),
        tuple(int(value) for value in ctx.groups["hydrogen"].atoms.indices),
        tuple(int(value) for value in ctx.groups["acceptor"].atoms.indices),
        float(ctx.params["d_a_cutoff"]),
        float(ctx.params["d_h_a_angle_cutoff"]),
    )


def analysis(ctx) -> HydrogenBondAnalysis:
    """同一 universe/选择/窗口/判据只运行一次 HBA。"""
    key = _key(ctx)
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached
    result = build(ctx)
    result.run(start=ctx.start, stop=ctx.stop)
    _CACHE[key] = result
    while len(_CACHE) > _MAX_CACHE:
        _CACHE.popitem(last=False)
    return result
