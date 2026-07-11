"""Run-history recording for ArcGIS Pro `.pyt` executions (ADR-0068)."""
from pathlib import Path

import pytest

from autogis.adapters import toolbox_core
from autogis.core.common.run_history import RunHistory


class _Parameter:
    def __init__(self, name, value):
        self.name = name
        self.valueAsText = value


class _Tool:
    @toolbox_core.record_pyt_run("import-gdb")
    def execute(self, parameters, messages):
        return "done"


def test_pyt_recorder_uses_gdb_parent_and_site_config(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOGIS_RUN_HISTORY", raising=False)
    config = tmp_path / "site.yaml"
    config.write_text("site_id: S1\n", encoding="utf-8")
    gdb = tmp_path / "project.gdb"

    assert _Tool().execute([
        _Parameter("gdb", str(gdb)),
        _Parameter("site_config", str(config)),
        _Parameter("event_date", "2026-07-10"),
    ], None) == "done"

    records = RunHistory(tmp_path / "run_history.csv").query()
    assert len(records) == 1
    record = records[0]
    assert (record.tool_name, record.site_id, record.event_id) == (
        "import-gdb", "S1", "2026-07-10")
    assert record.status == "success"
    assert record.inputs["gdb"] == str(gdb)


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
