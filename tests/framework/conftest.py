"""框架测试共用的夹具。"""

import pytest

from helpers import SYSTEM
from mdanal.config.system import read_system


@pytest.fixture(scope="module")
def tiny():
    return read_system(SYSTEM)
