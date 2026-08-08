import csv
from datetime import datetime
from pathlib import Path
import uuid

import pytest
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.common.run_history import RunHistory, RunRecord
from autogis.core.envmon.evaluate_readiness import evaluate_readiness


def _record(tool, site, event, status="success"):
    now = datetime.now()
    return RunRecord(
        run_id=str(uuid.uuid4()), tool_name=tool,
        site_id=site, event_id=event,
        started_at=now, finished_at=now,
        status=status, inputs={}, outputs={},
        qa_count_error=0, qa_count_warning=0, qa_count_info=0,
        message="")


def _history(tmp_path, records):
    h = RunHistory(tmp_path / "run_history.csv")
    for r in records:
        h.write(r)
    return h


def test_pass_when_all_tools_succeeded(tmp_path):
    h = _history(tmp_path, [
        _record("import-lab-edd", "H281", "EV01"),
        _record("reconcile-locations", "H281", "EV01")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd", "reconcile-locations"])
    assert qa.status() == "PASS"


def test_error_when_required_tool_not_run(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", "EV01")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd", "reconcile-locations"])
    cats = {r.category for r in qa.records}
    assert "required_tool_not_run" in cats
    assert qa.status() == "FAIL"


def test_error_when_last_run_failed(tmp_path):
    h = _history(tmp_path, [
        _record("import-lab-edd", "H281", "EV01", status="success"),
        _record("import-lab-edd", "H281", "EV01", status="error")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd"])
    assert any(r.category == "required_tool_not_run" for r in qa.records)
    assert qa.status() == "FAIL"


def test_warning_when_qa_errors_present(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", "EV01")])
    qa_csv = tmp_path / "qa.csv"
    qa_csv.write_text(
        "severity,category,message,recommended_action,site_id,location_id,"
        "sample_id,sample_date,analyte_name,source_workbook,source_sheet,"
        "source_row,source_column,source_cell,import_batch_id\n"
        "ERROR,some_error,oops,,H281,,,,,,,,,,\n",
        encoding="utf-8")
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd"],
                            qa_csv=qa_csv)
    assert any(r.category == "import_qa_errors_present" for r in qa.records)
    assert qa.status(allow_warnings=True) == "PASS"


# --- Task 5b: CLI ---
from click.testing import CliRunner
from autogis.adapters.cli import autogis as _cli


def test_evaluate_readiness_cli_fail_missing_tool(tmp_path):
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-readiness",
        "--site-id", "H281",
        "--run-history", str(tmp_path / "run_history.csv"),
        "--required-tool", "import-lab-edd"])
    assert r.exit_code == 1
    assert "required_tool_not_run" in r.output


def test_evaluate_readiness_cli_pass(tmp_path):
    h = _history(tmp_path, [_record("import-lab-edd", "H281", None)])
    r = CliRunner().invoke(_cli, [
        "envmon", "evaluate-readiness",
        "--site-id", "H281",
        "--run-history", str(tmp_path / "run_history.csv"),
        "--required-tool", "import-lab-edd"])
    assert r.exit_code == 0
    assert "PASS" in r.output or "readiness_summary" in r.output


# --- #412: site-less tool records must not be structurally unmatchable -------
#
# validate-db (and every .pyt tool decorated site_config_param=None) records
# site_id="" on BOTH execution paths, while RunHistory.latest() matches site_id
# by strict equality. A site-scoped readiness check therefore could never be
# satisfied, and its recommended_action told the operator to run the tool again
# -- which writes another site_id="" record and fails identically.

def test_site_less_tool_record_satisfies_a_site_scoped_check(tmp_path):
    h = _history(tmp_path, [_record("validate-db", "", None)])
    qa = evaluate_readiness("H281", "EV01", h, required_tools=["validate-db"])
    cats = {r.category for r in qa.records}
    assert "required_tool_not_run" not in cats
    assert qa.status() == "PASS"


def test_site_less_fallback_is_recorded_not_silent(tmp_path):
    h = _history(tmp_path, [_record("validate-db", "", None)])
    qa = evaluate_readiness("H281", "EV01", h, required_tools=["validate-db"])
    notes = [r for r in qa.records if r.category == "tool_run_not_site_scoped"]
    assert len(notes) == 1
    assert notes[0].severity == SEV_INFO


def test_site_less_fallback_does_not_launder_a_failed_run(tmp_path):
    """The fallback widens *which record* is found, never what counts as
    success -- a failed site-less run must still fail the check."""
    h = _history(tmp_path, [_record("validate-db", "", None, status="failed")])
    qa = evaluate_readiness("H281", "EV01", h, required_tools=["validate-db"])
    assert "required_tool_not_run" in {r.category for r in qa.records}
    assert qa.status() == "FAIL"


def test_site_scoped_record_still_wins_over_a_site_less_one(tmp_path):
    """A tool that DOES carry site identity must keep matching strictly: a
    successful run for another site must not satisfy this site's check."""
    h = _history(tmp_path, [_record("import-lab-edd", "OTHER_SITE", "EV01")])
    qa = evaluate_readiness("H281", "EV01", h,
                            required_tools=["import-lab-edd"])
    assert "required_tool_not_run" in {r.category for r in qa.records}
    assert "tool_run_not_site_scoped" not in {r.category for r in qa.records}


def test_no_fallback_when_the_check_itself_is_site_less(tmp_path):
    """site_id="" asks for the site-less series directly; there is nothing to
    fall back to, and no INFO note should be emitted."""
    h = _history(tmp_path, [_record("validate-db", "", None)])
    qa = evaluate_readiness("", None, h, required_tools=["validate-db"])
    assert qa.status() == "PASS"
    assert "tool_run_not_site_scoped" not in {r.category for r in qa.records}
