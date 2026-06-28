"""CLI tests for envmon run-history command."""
import csv
import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.run_history import RunHistory, RunRecord


def _write_run(path, tool="import-edd", site="H281", status="success", event=None):
    rh = RunHistory(path)
    rh.write(RunRecord(
        run_id=f"RUN-{tool[:4].upper()}",
        tool_name=tool,
        site_id=site,
        event_id=event,
        started_at=datetime(2026, 6, 1, 10, 0, 0),
        finished_at=datetime(2026, 6, 1, 10, 5, 0),
        status=status,
        inputs={},
        outputs={},
        qa_count_error=0,
        qa_count_warning=0,
        qa_count_info=1,
        message="ok",
    ))


def test_run_history_table_output(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
    ])
    assert result.exit_code == 0, result.output
    assert "import-edd" in result.output
    assert "H281" in result.output


def test_run_history_filter_site(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path, site="SITE-A")
    _write_run(rh_path, tool="validate-config", site="SITE-B")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--site", "SITE-A",
    ])
    assert result.exit_code == 0
    assert "SITE-A" in result.output
    assert "SITE-B" not in result.output


def test_run_history_json_format(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "json",
    ])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 1


def test_run_history_filter_status(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path, status="success")
    _write_run(rh_path, tool="compare-events", status="error")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--status", "error",
    ])
    assert result.exit_code == 0
    assert "compare-events" in result.output
    assert "import-edd" not in result.output


def test_run_history_empty_file(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
    ])
    assert result.exit_code == 0
    assert "0 record" in result.output


def test_run_history_empty_json_is_parseable(tmp_path):
    """Empty result set in json format must emit [] (machine-parseable)."""
    rh_path = tmp_path / "run_history.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "json",
    ])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_run_history_empty_csv_has_header(tmp_path):
    """Empty result set in csv format must still emit the header row."""
    rh_path = tmp_path / "run_history.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "csv",
    ])
    assert result.exit_code == 0
    assert "tool_name" in result.output.splitlines()[0]


def test_run_history_csv_format(tmp_path):
    rh_path = tmp_path / "run_history.csv"
    _write_run(rh_path)
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "run-history",
        "--run-history", str(rh_path),
        "--format", "csv",
    ])
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert "tool_name" in lines[0]
    assert len(lines) >= 2  # header + at least 1 row
