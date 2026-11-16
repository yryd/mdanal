"""空参数分析与模板：真实发现、run、快照与 replot。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mdanal.analyses as analyses_package

from mdanal import cli

from helpers import SYSTEM, write_system

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "example" / "analysis_template.py"


def test_empty_params_template_end_to_end(tmp_path):
    name = "zz_template_probe"
    target = Path(analyses_package.__path__[0]) / f"{name}.py"
    target.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        path = write_system(
            tmp_path,
            SYSTEM / "data.lmp",
            SYSTEM / "run.lammpstrj",
            f"  - {{name: {name}, sel: [all_atoms]}}\n",
            frames="[0, 3]",
        )
        out = tmp_path / "out"
        assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
        assert (out / f"{name}/tables/template.csv").is_file()
        snapshot = json.loads(
            (out / f"{name}/plot.json").read_text(encoding="utf-8")
        )
        assert snapshot["context"]["params"] == {}

        replot = tmp_path / "replot"
        assert cli.main(["replot", "--from", str(out), "--out", str(replot)]) == 0
        assert (replot / f"{name}/figures/template.png").is_file()
    finally:
        target.unlink(missing_ok=True)
        sys.modules.pop(f"mdanal.analyses.{name}", None)
