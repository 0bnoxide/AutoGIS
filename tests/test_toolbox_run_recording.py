"""Run-history recording for ArcGIS Pro `.pyt` executions (ADR-0068)."""
from pathlib import Path

import pytest

from autogis.adapters import toolbox_core
from autogis.core.common.run_history import RunHistory
from autogis.core.envmon.evaluate_readiness import evaluate_readiness


class _Parameter:
    def __init__(self, name, value):
        self.name = name
        self.valueAsText = value


class _Tool:
    @toolbox_core.record_pyt_run("import-gdb")
    def execute(self, parameters, messages):
        return "done"


class _Messages:
    def __init__(self):
        self.lines = []

    def addErrorMessage(self, line):
        self.lines.append(("ERROR", line))

    def addWarningMessage(self, line):
        self.lines.append(("WARNING", line))

    def addMessage(self, line):
        self.lines.append(("INFO", line))


class _BlockedTool:
    @toolbox_core.record_pyt_run("full-pipeline")
    def execute(self, parameters, messages):
        messages.addErrorMessage("Pipeline halted: import QA failed.")


class _WarningTool:
    @toolbox_core.record_pyt_run("build-event")
    def execute(self, parameters, messages):
        messages.addWarningMessage("Review this output.")
        messages.addMessage("Output written.")


def test_pyt_recorder_uses_gdb_parent_and_site_config(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOGIS_RUN_HISTORY", raising=False)
    config = tmp_path / "site.yaml"
    config.write_text("site_id: S1\n", encoding="utf-8")
    gdb = tmp_path / "project.gdb"

    assert _Tool().execute([
        _Parameter("gdb", str(gdb)),
        _Parameter("site_config", str(config)),
        _Parameter("event_date", "2026-07-10"),
    ], _Messages()) == "done"

    records = RunHistory(tmp_path / "run_history.csv").query()
    assert len(records) == 1
    record = records[0]
    assert (record.tool_name, record.site_id, record.event_id) == (
        "import-gdb", "S1", "2026-07-10")
    assert record.status == "success"
    assert record.inputs["gdb"] == str(gdb)


def test_pyt_error_message_records_error_status(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOGIS_RUN_HISTORY", raising=False)
    config = tmp_path / "site.yaml"
    config.write_text("site_id: S1\n", encoding="utf-8")

    _BlockedTool().execute([
        _Parameter("gdb", str(tmp_path / "project.gdb")),
        _Parameter("site_config", str(config)),
    ], _Messages())

    record = RunHistory(tmp_path / "run_history.csv").query()[0]
    assert record.status == "error"
    assert record.qa_count_error == 1
    assert record.message == "1 error QA message(s)"
    readiness = evaluate_readiness(
        "S1", None, RunHistory(tmp_path / "run_history.csv"),
        required_tools=["full-pipeline"])
    assert readiness.status() == "FAIL"


def test_pyt_warnings_are_counted_without_failing_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOGIS_RUN_HISTORY", raising=False)
    _WarningTool().execute([
        _Parameter("gdb", str(tmp_path / "project.gdb")),
        _Parameter("site_config", ""),
    ], _Messages())

    record = RunHistory(tmp_path / "run_history.csv").query()[0]
    assert record.status == "success"
    assert (record.qa_count_error, record.qa_count_warning,
            record.qa_count_info) == (0, 1, 1)


def test_pyt_recorder_env_override_and_off_keep_tool_outcome(tmp_path, monkeypatch):
    env_path = tmp_path / "elsewhere" / "history.csv"
    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", str(env_path))
    with pytest.raises(RuntimeError, match="tool failed"):
        with toolbox_core.recording_pyt_run(
            "tool", inputs={}, dest_hint=tmp_path, site_id="S1"):
            raise RuntimeError("tool failed")

    record = RunHistory(env_path).query()[0]
    assert record.status == "error"
    assert record.message == "RuntimeError: tool failed"

    monkeypatch.setenv("AUTOGIS_RUN_HISTORY", "off")
    with pytest.raises(KeyboardInterrupt):
        with toolbox_core.recording_pyt_run(
            "tool", inputs={}, dest_hint=tmp_path, site_id="S1"):
            raise KeyboardInterrupt
    assert len(RunHistory(env_path).query()) == 1
