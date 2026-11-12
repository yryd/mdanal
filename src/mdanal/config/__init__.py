"""配置层：system.yaml 解析、分析发现与命名。"""

from .system import read_system
from .registry import build_plan, load_registry

__all__ = ["read_system", "load_registry", "build_plan"]
