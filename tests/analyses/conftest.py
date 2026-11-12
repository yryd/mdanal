"""分析侧测试：只在这里加载内置分析。"""

import pytest

from helpers import SYSTEM
from mdanal.config.registry import load_registry
from mdanal.config.system import read_system


@pytest.fixture(scope="module")
def real():
    return read_system(SYSTEM), load_registry()
