"""离线 derive：从已有表重算，不读轨迹。"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from mdanal import cli
from mdanal.derive import run_derive
from mdanal.errors import ValidationError

from helpers import SYSTEM, write_system


def _run_msd(tmp_path):
    path = write_system(
        tmp_path,
        SYSTEM / "data.lmp",
        SYSTEM / "run.lammpstrj",
        "  - {name: msd, sel: [all_atoms]}\n",
        frames="[0, 10]",
    )
    out = tmp_path / "run"
    assert cli.main(["run", "--system", str(path), "--out", str(out)]) == 0
    return out


def _config(tmp_path, window):
    path = tmp_path / "derive.yaml"
    path.write_text(
        "schema_version: 1\n"
        "analyses:\n"
        "  msd:\n"
        f"    derive: {{fit: {{window_ns: [{window[0]}, {window[1]}]}}, rdc: {{}}}}\n"
        "    figures: {raw: {}, fit: {}, rdc: {}}\n",
        encoding="utf-8",
    )
    return path


def test_derive_reuses_tables_and_does_not_load_trajectory(tmp_path, monkeypatch):
    out = _run_msd(tmp_path)
    import mdanal.config.system as system_module

    def boom(*args, **kwargs):
        raise AssertionError("derive 不应加载轨迹")

    monkeypatch.setattr(system_module, "load_universe", boom)
    target = run_derive(
        out,
        tmp_path / "derived",
        config=_config(tmp_path, (0.0, 0.01)),
    )
    assert (target / "msd/tables/msd_fit_summary.csv").is_file()
    assert (target / "msd/figures/msd-fit.png").is_file()
    assert (target / "derive.json").is_file()
    record = json.loads((target / "derive.json").read_text(encoding="utf-8"))
    assert record["analyses"][0]["directory"] == "msd"


def test_derive_changes_d_with_window_and_replots(tmp_path):
    out = _run_msd(tmp_path)
    first = run_derive(
        out, tmp_path / "a", config=_config(tmp_path, (0.0, 0.01))
    )
    second = run_derive(
        out, tmp_path / "b", config=_config(tmp_path, (0.0, 0.02))
    )
    a = pd.read_csv(first / "msd/tables/msd_fit_summary.csv", encoding="utf-8-sig")
    b = pd.read_csv(second / "msd/tables/msd_fit_summary.csv", encoding="utf-8-sig")
    assert a["D_A2_per_ps"].iloc[0] != pytest.approx(b["D_A2_per_ps"].iloc[0])
    # 派生结果可继续 replot。
    config = tmp_path / "plot.yaml"
    config.write_text("schema_version: 1\ndefaults:\n  format: svg\n", encoding="utf-8")
    assert (
        cli.main(
            [
                "replot",
                "--from",
                str(first),
                "--out",
                str(tmp_path / "replot"),
                "--figure",
                "fit",
                "--config",
                str(config),
            ]
        )
        == 0
    )
    assert (tmp_path / "replot/msd/figures/msd-fit.svg").is_file()


def test_derive_rejects_unknown_key(tmp_path):
    out = _run_msd(tmp_path)
    config = tmp_path / "bad.yaml"
    config.write_text(
        "schema_version: 1\n"
        "analyses:\n"
        "  msd:\n"
        "    derive: {fit: {fit_window_ns: [0, 1]}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="未知字段"):
        run_derive(out, tmp_path / "bad", config=config)
