from __future__ import annotations
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from autogis.core.common.run_history import RunHistory, RunRecord, RunHistoryError


def _record(**overrides) -> RunRecord:
    defaults = dict(
        run_id=str(uuid.uuid4()),
        tool_name="TestTool",
        site_id="H281",
        event_id="2026-Q2",
        started_at=datetime(2026, 6, 25, 9, 0, 0),
        finished_at=datetime(2026, 6, 25, 9, 0, 5),
        status="success",
        inputs={"workbook": "test.xlsx"},
        outputs={"rows": 42},
        qa_count_error=0,
        qa_count_warning=1,
        qa_count_info=3,
        message="Imported 42 rows, 1 warning.",
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


def test_write_creates_file(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record())
    assert (tmp_path / "run_history.csv").exists()


def test_write_then_query_all(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(site_id="H281"))
    h.write(_record(site_id="ZT42"))
    results = h.query()
    assert len(results) == 2


def test_query_filter_by_site(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(site_id="H281"))
    h.write(_record(site_id="ZT42"))
    results = h.query(site_id="H281")
    assert len(results) == 1
    assert results[0].site_id == "H281"


def test_query_filter_by_tool(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(tool_name="ImportLabEDD"))
    h.write(_record(tool_name="ValidateRTKSurvey"))
    results = h.query(tool_name="ImportLabEDD")
    assert len(results) == 1
    assert results[0].tool_name == "ImportLabEDD"


def test_query_filter_by_status(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(status="success"))
    h.write(_record(status="error"))
    results = h.query(status="error")
    assert len(results) == 1
    assert results[0].status == "error"


def test_query_filter_by_since(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    old = datetime(2026, 1, 1, 0, 0, 0)
    new = datetime(2026, 6, 1, 0, 0, 0)
    h.write(_record(finished_at=old))
    h.write(_record(finished_at=new))
    results = h.query(since=datetime(2026, 3, 1))
    assert len(results) == 1
    assert results[0].finished_at == new


def test_latest_returns_most_recent(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(tool_name="ImportLabEDD", site_id="H281",
                    finished_at=datetime(2026, 6, 1)))
    h.write(_record(tool_name="ImportLabEDD", site_id="H281",
                    finished_at=datetime(2026, 6, 25)))
    rec = h.latest("ImportLabEDD", "H281")
    assert rec is not None
    assert rec.finished_at == datetime(2026, 6, 25)


def test_latest_returns_none_when_no_match(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    assert h.latest("NoSuchTool", "H281") is None


def test_write_is_best_effort_on_bad_path(tmp_path):
    """write() must not raise even if disk write fails."""
    h = RunHistory(Path("/nonexistent/path/run_history.csv"))
    h.write(_record())   # must not raise


def test_inputs_outputs_roundtrip(tmp_path):
    """inputs/outputs dicts must survive write->query roundtrip."""
    inputs = {"workbook": "data.xlsx", "site_id": "H281"}
    outputs = {"rows_imported": 99, "qa_path": "/tmp/qa.csv"}
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(inputs=inputs, outputs=outputs))
    rec = h.query()[0]
    assert rec.inputs == inputs
    assert rec.outputs == outputs


def test_event_id_none_roundtrip(tmp_path):
    """event_id=None must survive write->query roundtrip."""
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(event_id=None))
    rec = h.query()[0]
    assert rec.event_id is None


def test_corrupt_file_raises_run_history_error(tmp_path):
    p = tmp_path / "run_history.csv"
    p.write_text("not,a,valid,csv,file\n{{{broken", encoding="utf-8")
    h = RunHistory(p)
    with pytest.raises(RunHistoryError):
        h.query()
