from __future__ import annotations

import json
from pathlib import Path

from mdanal import cli

TINY = Path(__file__).resolve().parents[1] / "fixtures" / "tiny"


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "figures.yaml"
    path.write_text(
        f"""schema_version: 1
name: cli
render: {{lang: en, dpi: 50}}
sources:
  A:
    topology: {TINY / 'data.lmp'}
    trajectory: {TINY / 'run.lammpstrj'}
    frames: [0, 5]
    groups: {{all: "all"}}
figures:
  - name: msd
    panels:
      - {{source: A, pack: msd, product: msd-raw, select: {{group: all}}}}
""",
        encoding="utf-8",
    )
    return path


def test_cli_render_check_replot(tmp_path, capsys):
    config = _config(tmp_path)
    assert cli.main(["check", "--config", str(config)]) == 0
    assert cli.main(
        ["render", "--config", str(config), "--out", str(tmp_path / "out"), "--force"]
    ) == 0
    assert (tmp_path / "out" / "figures" / "msd.png").is_file()
    assert cli.main(
        [
            "replot",
            "--from",
            str(tmp_path / "out"),
            "--out",
            str(tmp_path / "replot"),
            "--dpi",
            "40",
        ]
    ) == 0
    assert (tmp_path / "replot" / "figures" / "msd.png").is_file()


def test_cli_packs_json(capsys):
    assert cli.main(["packs", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {"density", "hbond", "msd", "rdf", "velocity"} <= set(payload)


def test_cli_check_pack(capsys):
    assert cli.main(["check-pack", "density"]) == 0
    out = capsys.readouterr().out
    assert "density-2d" in out
    assert "density-line" in out


def test_cli_invalid_config_returns_validation(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("schema_version: 1\nsources: {}\nfigures: []\n", encoding="utf-8")
    assert cli.main(["check", "--config", str(path)]) == 3
