"""插件共享的几何状态元数据。"""

from __future__ import annotations

from typing import Any


def geometry_meta(ctx: Any) -> dict[str, Any]:
    """记录插件实际使用的 PBC 假设，而不只依赖警告文字。"""
    geometry = getattr(ctx, "geometry", None)
    pbc = tuple(bool(value) for value in getattr(geometry, "pbc", (True, True, True)))
    return {
        "effective_pbc": list(pbc),
        "geometry_status": "supported" if all(pbc) else "unsupported_geometry",
    }
