"""CLI tests for validate-schedule (Tool 10.2)."""
import pytest
import yaml
from click.testing import CliRunner
from pathlib import Path
from autogis.adapters.cli import autogis


def _write_schedule(path, data):
    Path(path).write_text(yaml.dump(data), encoding="utf-8")


GOOD_SCHEDULE = {
    "site_id": "H281",
    "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
}


def test_validate_schedule_valid(tmp_path):
    runner = CliRunner()
    sch = tmp_path / "schedule.yaml"
    _write_schedule(sch, GOOD_SCHEDULE)
    result = runner.invoke(autogis, [
        "envmon", "validate-schedule",
        "--schedule", str(sch),
    ])
    assert result.exit_code == 0, result.output


def test_validate_schedule_missing_site_id(tmp_path):
    runner = CliRunner()
    sch = tmp_path / "schedule.yaml"
    bad = {**GOOD_SCHEDULE, "site_id": ""}
    _write_schedule(sch, bad)
    result = runner.invoke(autogis, [
        "envmon", "validate-schedule",
        "--schedule", str(sch),
    ])
    assert result.exit_code != 0


def test_validate_schedule_with_analyte_dict(tmp_path):
    runner = CliRunner()
    sch = tmp_path / "schedule.yaml"
    _write_schedule(sch, GOOD_SCHEDULE)
    adict = tmp_path / "analytes.csv"
    adict.write_text("AnalyteCanonicalName\nBenzene\nToluene\n", encoding="utf-8")
    result = runner.invoke(autogis, [
        "envmon", "validate-schedule",
        "--schedule", str(sch),
        "--analyte-dict", str(adict),
    ])
    assert result.exit_code == 0, result.output


def test_validate_schedule_unknown_analyte_warns(tmp_path):
    runner = CliRunner()
    sch = tmp_path / "schedule.yaml"
    bad = {**GOOD_SCHEDULE, "required_analytes": ["Benzene", "Xylene"]}
    _write_schedule(sch, bad)
    adict = tmp_path / "analytes.csv"
    adict.write_text("AnalyteCanonicalName\nBenzene\nToluene\n", encoding="utf-8")
    result = runner.invoke(autogis, [
        "envmon", "validate-schedule",
        "--schedule", str(sch),
        "--analyte-dict", str(adict),
        "--fail-on", "warning",
    ])
    assert result.exit_code != 0
