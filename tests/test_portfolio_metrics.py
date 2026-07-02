"""Tests for cross-site portfolio metrics rollup (portfolio_metrics.py)."""
from datetime import datetime

from autogis.core.common.qa import QACollector
from autogis.core.common.run_history import RunHistory, RunRecord
from autogis.core.envmon.portfolio_metrics import (
    build_portfolio_metrics,
    discover_site_ids,
    write_portfolio_csv,
)


def _record(site_id, tool_name, status, finished_at):
    return RunRecord(
        run_id=f"{site_id}-{tool_name}-{finished_at}",
        tool_name=tool_name,
        site_id=site_id,
        event_id=None,
        started_at=datetime(2026, 1, 1),
        finished_at=datetime.fromisoformat(finished_at),
        status=status,
        inputs={}, outputs={},
        qa_count_error=0, qa_count_warning=0, qa_count_info=0,
        message="",
    )


def _history_with(tmp_path, records):
    path = tmp_path / "run_history.csv"
    history = RunHistory(path)
    for r in records:
        history.write(r)
    return history


def test_discover_site_ids(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
        _record("SITE-B", "import-gdb", "success", "2026-06-02T00:00:00"),
        _record("SITE-A", "build-event", "success", "2026-06-01T01:00:00"),
    ])
    assert discover_site_ids(history) == ["SITE-A", "SITE-B"]


def test_site_ready_when_all_required_tools_succeeded(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
        _record("SITE-A", "build-event", "success", "2026-06-01T01:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(
        history, ["import-gdb", "build-event"], qa=qa)
    assert len(statuses) == 1
    assert statuses[0].site_id == "SITE-A"
    assert statuses[0].ready is True
    assert statuses[0].missing_tools == ""
    assert statuses[0].total_runs == 2


def test_site_not_ready_when_a_tool_missing(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(
        history, ["import-gdb", "build-event"], qa=qa)
    assert statuses[0].ready is False
    assert statuses[0].missing_tools == "build-event"


def test_site_not_ready_when_latest_run_failed(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "error", "2026-06-01T00:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(history, ["import-gdb"], qa=qa)
    assert statuses[0].ready is False
    assert statuses[0].missing_tools == "import-gdb"


def test_explicit_site_ids_overrides_discovery(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
        _record("SITE-B", "import-gdb", "success", "2026-06-02T00:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(
        history, ["import-gdb"], site_ids=["SITE-B"], qa=qa)
    assert [s.site_id for s in statuses] == ["SITE-B"]


def test_empty_run_history_no_sites(tmp_path):
    history = RunHistory(tmp_path / "missing.csv")
    qa = QACollector()
    statuses = build_portfolio_metrics(history, ["import-gdb"], qa=qa)
    assert statuses == []
    assert any(r.category == "portfolio_metrics_complete" for r in qa.records)


def test_last_activity_is_most_recent_run(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
        _record("SITE-A", "build-event", "success", "2026-06-05T12:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(history, ["import-gdb"], qa=qa)
    assert statuses[0].last_activity == "2026-06-05T12:00:00"


def test_disagreement_between_ready_and_missing_is_flagged(tmp_path, monkeypatch):
    """If evaluate_readiness() and the missing-tools recomputation ever
    disagree (e.g. a future evaluate_readiness failure path this function
    doesn't independently re-derive), that must be surfaced, not hidden."""
    import autogis.core.envmon.portfolio_metrics as portfolio_metrics_mod
    from autogis.core.common.qa import QACollector as _QAC, SEV_ERROR

    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
    ])

    def fake_evaluate_readiness(**kwargs):
        qa = _QAC()
        qa.add(SEV_ERROR, "some_future_check", "simulated unrelated failure")
        return qa

    monkeypatch.setattr(
        portfolio_metrics_mod, "evaluate_readiness", fake_evaluate_readiness)

    qa = QACollector()
    statuses = build_portfolio_metrics(history, ["import-gdb"], qa=qa)
    # evaluate_readiness() says FAIL (ready=False) but the independent
    # missing-tools recomputation finds nothing missing -> disagreement.
    assert statuses[0].ready is False
    assert statuses[0].missing_tools == ""
    assert any(r.category == "portfolio_status_inconsistent" for r in qa.records)


def test_write_portfolio_csv(tmp_path):
    history = _history_with(tmp_path, [
        _record("SITE-A", "import-gdb", "success", "2026-06-01T00:00:00"),
    ])
    qa = QACollector()
    statuses = build_portfolio_metrics(history, ["import-gdb"], qa=qa)
    out = tmp_path / "portfolio.csv"
    write_portfolio_csv(statuses, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "SITE-A" in text
