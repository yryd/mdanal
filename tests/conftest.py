"""让测试无需安装即可导入 mdanal；测试目录自身也进 sys.path，便于共享 helpers/假分析。"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _close_matplotlib_figures():
    """测试之间关闭 Figure，避免超 20 个的全局警告掩盖真实泄漏。"""
    yield
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    plt.close("all")
