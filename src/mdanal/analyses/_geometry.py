"""插件共享的几何状态元数据。"""

from __future__ import annotations

from typing import Any


def geometry_meta(
    ctx: Any,
    *,
    kernel_pbc: tuple[bool, bool, bool] | None = None,
    geometry_status: str | None = None,
) -> dict[str, Any]:
    """记录输入边界与距离内核实际假设，二者不一致时明确标出。

    `input_pbc` 是 dump 的 BOX BOUNDS 声明；`kernel_pbc` 是本插件真正
    使用的周期方向。旧字段 `effective_pbc` 保留为 kernel 的别名，避免
    已有快照/下游脚本失效。
    """
    geometry = getattr(ctx, "geometry", None)
    input_pbc = tuple(
        bool(value) for value in getattr(geometry, "pbc", (True, True, True))
    )
    actual = tuple(kernel_pbc) if kernel_pbc is not None else input_pbc
    matches = actual == input_pbc
    if geometry_status is None:
        geometry_status = (
            "supported"
            if matches and all(actual)
            else "unsupported_geometry"
        )
    return {
        "input_pbc": list(input_pbc),
        "kernel_pbc": list(actual),
        "effective_pbc": list(actual),
        "pbc_match": bool(matches),
        "geometry_status": str(geometry_status),
    }


def full_periodic_meta(ctx: Any) -> dict[str, Any]:
    """MDAnalysis 氢键内核固定按全周期盒计算；非周期输入只能标为不支持。"""
    input_pbc = tuple(
        bool(value)
        for value in getattr(getattr(ctx, "geometry", None), "pbc", (True, True, True))
    )
    return geometry_meta(
        ctx,
        kernel_pbc=(True, True, True),
        geometry_status="supported" if all(input_pbc) else "unsupported_geometry",
    )
