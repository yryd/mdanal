"""density 插件包；实现暂由共享模块 ``_density`` 提供。"""

from ._impl import *  # noqa: F401,F403
from ._impl import _project_grid  # 兼容旧测试/调用
