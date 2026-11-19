"""内置图包的位置。"""

from __future__ import annotations

from pathlib import Path

ANALYSES_PACKAGE = "mdanal.analyses"
ANALYSES_DIR = Path(__file__).resolve().parent.parent / "analyses"
