"""执行层：上下文、运行与落盘。"""

from __future__ import annotations

from .context import RunContext

__all__ = ["RunContext", "Prepared", "RunOptions", "execute", "prepare"]


def __getattr__(name: str):
    """延迟导入 runner，避免 plot.snapshot → run.writers → run.runner 的循环。"""
    if name in {"Prepared", "RunOptions", "execute", "prepare"}:
        from . import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
