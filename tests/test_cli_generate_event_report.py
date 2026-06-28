"""CLI tests for envmon generate-event-report command."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_missing_input_csv_is_skipped_not_errored(tmp_path):
    """An absent optional input path must be skipped, not rejected by click."""
    out = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "generate-event-report",
        "--site", "H281", "--event", "2026Q2",
        "--output", str(out),
        "--results-csv", str(tmp_path / "does_not_exist.csv"),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# Monitoring Event Report")


def test_present_input_csv_counted(tmp_path):
    results_csv = tmp_path / "results.csv"
    results_csv.write_text("ExceedsScreeningLevel\n1\n0\n1\n", encoding="utf-8")
    out = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "generate-event-report",
        "--site", "H281", "--event", "2026Q2",
        "--output", str(out),
        "--results-csv", str(results_csv),
    ])
    assert result.exit_code == 0, result.output
    assert "Total analytical results | 3" in out.read_text(encoding="utf-8")
