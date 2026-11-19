"""可选的图 recipe 协议：一次分析可以注册多张图。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .panels import Panel


@dataclass(frozen=True)
class FigureRecipe:
    """一个命名图 recipe；build 只负责把表组织成 Panel 列表。"""

    name: str
    build: Callable[[Any, Mapping[str, Any]], Sequence[Panel]]
    requires: tuple[str, ...] = ()
    filename: str | None = None
    ncols: int | None = None
