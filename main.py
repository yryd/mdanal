"""入口：python main.py <命令>。

把 src/ 加入 sys.path 后转调 mdanal.cli.main，因此无需安装即可运行。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mdanal.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
