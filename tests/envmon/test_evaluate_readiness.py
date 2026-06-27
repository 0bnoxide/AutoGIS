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
