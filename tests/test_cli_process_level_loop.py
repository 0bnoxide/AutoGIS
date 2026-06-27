"""CLI tests for envmon process-level-loop (Tool 8.1)."""
import csv
import dataclasses
from datetime import date
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.schema.survey import LevelLoopObservation


def _write_obs_csv(path: Path, obs_list):
    fields = [f.name for f in dataclasses.fields(LevelLoopObservation)
              if f.name != "table_name"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for obs in obs_list:
            row = {f: getattr(obs, f) for f in fields}
            w.writerow(row)


def _obs(setup, point, bs=None, fs=None, is_=None):
    return LevelLoopObservation(run_id="L1", setup_id=str(setup), point_id=point,
                                backsight=bs, foresight=fs, intermediate_sight=is_)


def test_help_lists_options():
    r = CliRunner().invoke(autogis, ["envmon", "process-level-loop", "--help"])
    assert r.exit_code == 0
    for opt in ("--observations-csv", "--known-elevation", "--benchmark-id",
                "--tolerance", "--run-output", "--observations-output"):
        assert opt in r.output


def test_happy_path_perfect_loop(tmp_path):
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=3.000),
    ]
    obs_csv = tmp_path / "obs.csv"
    run_out = tmp_path / "run.csv"
    obs_out = tmp_path / "obs_out.csv"
    _write_obs_csv(obs_csv, obs)

    r = CliRunner().invoke(autogis, [
        "envmon", "process-level-loop",
        "--observations-csv", str(obs_csv),
        "--run-id", "L1",
        "--site-id", "S",
        "--survey-date", "2026-04-01",
        "--benchmark-id", "BM",
        "--known-elevation", "100.0",
        "--tolerance", "0.05",
        "--run-output", str(run_out),
        "--observations-output", str(obs_out),
    ])
    assert r.exit_code == 0, r.output
    assert run_out.exists()
    assert obs_out.exists()
    run_rows = list(csv.DictReader(run_out.open(encoding="utf-8")))
    assert len(run_rows) == 1
    assert float(run_rows[0]["misclosure_ft"]) == 0.0


def test_misclosure_error_exits_nonzero(tmp_path):
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=2.900),  # misclosure 0.100 > 0.05
    ]
    obs_csv = tmp_path / "obs.csv"
    run_out = tmp_path / "run.csv"
    obs_out = tmp_path / "obs_out.csv"
    _write_obs_csv(obs_csv, obs)

    r = CliRunner().invoke(autogis, [
        "envmon", "process-level-loop",
        "--observations-csv", str(obs_csv),
        "--run-id", "L1",
        "--site-id", "S",
        "--survey-date", "2026-04-01",
        "--benchmark-id", "BM",
        "--known-elevation", "100.0",
        "--tolerance", "0.05",
        "--run-output", str(run_out),
        "--observations-output", str(obs_out),
    ])
    # Should exit 1 because misclosure ERROR with --fail-on error
    assert r.exit_code == 1
