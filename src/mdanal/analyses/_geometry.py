"""插件共享的几何状态元数据。"""

from __future__ import annotations

from typing import Any


def geometry_meta(
    ctx: Any,
    *,
    kernel_pbc: tuple[bool, bool, bool] | str | None = None,
    geometry_status: str | None = None,
) -> dict[str, Any]:
    """记录输入边界与距离内核实际假设，二者不一致时明确标出。

    `input_pbc` 是 dump 的 BOX BOUNDS 声明；`kernel_pbc` 是本插件真正
    使用的周期方向。
    """
    geometry = getattr(ctx, "geometry", None)
    window = getattr(ctx, "geometry_window", None)
    reference_pbc = tuple(
        bool(value) for value in getattr(geometry, "pbc", (True, True, True))
    )
    input_pbc = (
        tuple(bool(value) for value in window.pbc_all)
        if window is not None
        else reference_pbc
    )
    if isinstance(kernel_pbc, str):
        actual: tuple[bool, bool, bool] | str = kernel_pbc
        matches = True
    elif kernel_pbc is not None:
        actual = tuple(kernel_pbc)
        matches = actual == input_pbc
    else:
        actual = input_pbc
        matches = True
    if geometry_status is None:
        geometry_status = (
            "supported"
            if matches and (isinstance(actual, str) or all(actual))
            else "unsupported_geometry"
        )
    result = {
        "input_pbc": list(input_pbc),
        "input_pbc_reference": list(reference_pbc),
        "kernel_pbc": actual if isinstance(actual, str) else list(actual),
        "pbc_match": bool(matches),
        "geometry_status": str(geometry_status),
    }
    if window is not None:
        result.update(
            {
                "pbc_all": list(window.pbc_all),
                "pbc_changed": bool(window.pbc_changed),
                "cell_changed": bool(window.cell_changed),
                "origin_changed": bool(window.origin_changed),
                "full_periodic": bool(window.full_periodic),
            }
        )
    return result


def full_periodic_meta(ctx: Any) -> dict[str, Any]:
    """MDAnalysis 氢键内核固定按全周期盒计算；非周期输入只能标为不支持。"""
    window = getattr(ctx, "geometry_window", None)
    input_pbc = (
        tuple(bool(value) for value in window.pbc_all)
        if window is not None
        else tuple(
            bool(value)
            for value in getattr(getattr(ctx, "geometry", None), "pbc", (True, True, True))
        )
    )
    return geometry_meta(
        ctx,
        kernel_pbc=(True, True, True),
        geometry_status="supported" if all(input_pbc) else "unsupported_geometry",
    )
