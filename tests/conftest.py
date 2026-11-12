"""让测试无需安装即可导入 mdanal；测试目录自身也进 sys.path，便于共享 helpers/假分析。"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
