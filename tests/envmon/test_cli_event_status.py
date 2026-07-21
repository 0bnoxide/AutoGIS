"""CLI wiring for `envmon event-status` (Phase 2, ADR-0093).

Core classification logic is covered in test_event_status.py; this pins the
CLI contract: --accept round-trip, JSON output shape, and the semantic exit
codes automation depends on.
"""
import json
import time
from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.run_history import RunHistory, RunRecord

SITE, EVENT = "H281", "2026-Q2"
# Far future so the recorded builds are unambiguously AFTER the baseline that
# --accept stamps with the real wall-clock time (the accept-then-build order the
# tool models). Avoids any UTC/local skew in the comparison.
T1 = datetime(2099, 1, 1, 10, 0, 0)
T_APPROVE = datetime(2099, 1, 2, 10, 0, 0)


def _write_inputs(tmp_path):
    paths = {}
    for kind, content in (("workbook", "WB"), ("site-config", "SC"),
                          ("screening", "SL"), ("figure-spec", "FS")):
        p = tmp_path / f"{kind}.dat"
        p.write_text(content)
        paths[kind] = p
    return paths


def _all_producers(tmp_path):
    h = RunHistory(tmp_path / "rh.csv")
    for tool in ("import-edd", "export-snapshot", "apply-screening",
                 "export-figures", "run-gw-model-pipeline"):
        h.write(RunRecord(run_id=tool, tool_name=tool, site_id=SITE,
                          event_id=EVENT, started_at=T1, finished_at=T1,
                          status="success", inputs={}, outputs={},
                          qa_count_error=0, qa_count_warning=0, qa_count_info=0,
                          message=""))
    h.write(RunRecord(run_id="ap", tool_name="approve-gw-model", site_id=SITE,
                      event_id=EVENT, started_at=T_APPROVE,
                      finished_at=T_APPROVE,
                      status="success", inputs={}, outputs={}, qa_count_error=0,
                      qa_count_warning=0, qa_count_info=0, message=""))
    return tmp_path / "rh.csv"


def _base_args(tmp_path, paths, registry):
    return [
        "envmon", "event-status", "--site-id", SITE, "--event-id", EVENT,
        "--source-registry", str(registry),
        "--workbook", str(paths["workbook"]),
        "--site-config", str(paths["site-config"]),
        "--screening", str(paths["screening"]),
        "--figure-spec", str(paths["figure-spec"]),
    ]


def test_accept_then_all_current_exits_zero(tmp_path):
    runner = CliRunner()
    paths = _write_inputs(tmp_path)
    registry = tmp_path / "src.csv"
    rh = _all_producers(tmp_path)

    accept = runner.invoke(autogis, _base_args(tmp_path, paths, registry)
                           + ["--accept"])
    assert accept.exit_code == 0, accept.output
    assert "Accepted baseline" in accept.output
    assert registry.exists()

    res = runner.invoke(autogis, _base_args(tmp_path, paths, registry)
                        + ["--run-history", str(rh), "--format", "json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["summary"]["current"] == 5


def test_changed_screening_exits_stale_code_3(tmp_path):
    runner = CliRunner()
    paths = _write_inputs(tmp_path)
    registry = tmp_path / "src.csv"
    rh = _all_producers(tmp_path)
    runner.invoke(autogis, _base_args(tmp_path, paths, registry) + ["--accept"])

    paths["screening"].write_text("CHANGED")  # drift after baseline
    res = runner.invoke(autogis, _base_args(tmp_path, paths, registry)
                        + ["--run-history", str(rh), "--format", "json"])
    assert res.exit_code == 3  # stale
    payload = json.loads(res.output)
    states = {a["kind"]: a["state"] for a in payload["artifacts"]}
    assert states["screening-evaluation"] == "stale"
    assert states["figures"] == "current"  # ONLY correct downstream


@pytest.mark.skipif(not hasattr(time, "tzset"),
                    reason="time.tzset is Unix-only; TZ is a no-op on Windows")
def test_accept_stamp_is_local_not_utc(tmp_path, monkeypatch):
    """P1-1: --accept must stamp the baseline in the same (local) clock as
    run_history's finished_at. A UTC stamp skews the comparison in non-UTC
    timezones, marking a freshly-built event stale for the offset's duration.
    Forces a non-UTC zone so a UTC regression would flip the result to stale.
    """
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    runner = CliRunner()
    paths = _write_inputs(tmp_path)
    registry = tmp_path / "src.csv"
    runner.invoke(autogis, _base_args(tmp_path, paths, registry) + ["--accept"])

    # producers build a few seconds AFTER the accept, in the same local clock
    built = datetime.now() + timedelta(seconds=5)
    h = RunHistory(tmp_path / "rh.csv")
    for tool in ("import-edd", "export-snapshot", "apply-screening",
                 "export-figures", "run-gw-model-pipeline"):
        h.write(RunRecord(run_id=tool, tool_name=tool, site_id=SITE,
                          event_id=EVENT, started_at=built, finished_at=built,
                          status="success", inputs={}, outputs={},
                          qa_count_error=0, qa_count_warning=0, qa_count_info=0,
                          message=""))
    ap = built + timedelta(seconds=1)
    h.write(RunRecord(run_id="ap", tool_name="approve-gw-model", site_id=SITE,
                      event_id=EVENT, started_at=ap, finished_at=ap,
                      status="success", inputs={}, outputs={}, qa_count_error=0,
                      qa_count_warning=0, qa_count_info=0, message=""))

    res = runner.invoke(autogis, _base_args(tmp_path, paths, registry)
                        + ["--run-history", str(tmp_path / "rh.csv"),
                           "--format", "json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["summary"]["current"] == 5


def test_missing_run_history_reports_missing_exit_4(tmp_path):
    runner = CliRunner()
    paths = _write_inputs(tmp_path)
    registry = tmp_path / "src.csv"
    runner.invoke(autogis, _base_args(tmp_path, paths, registry) + ["--accept"])

    # No --run-history file -> no producer runs -> everything missing.
    res = runner.invoke(autogis, _base_args(tmp_path, paths, registry)
                        + ["--run-history", str(tmp_path / "absent.csv")])
    assert res.exit_code == 4  # missing outranks the downstream stale
    assert "missing" in res.output
