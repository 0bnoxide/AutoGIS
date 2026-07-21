"""Event status & staleness checker (Phase 2, ADR-0093).

The centerpiece is ``test_input_change_invalidates_only_correct_downstream`` —
the production gate as a matrix: each changed input must move ONLY its correct
downstream artifacts, leaving the rest current.
"""
from datetime import datetime

import pytest

from autogis.core.common.run_history import RunHistory, RunRecord
from autogis.core.envmon import event_status as es
from autogis.core.envmon.source_registry import SourceDocRecord, SourceRegistry

SITE, EVENT = "H281", "2026-Q2"
T0 = datetime(2026, 1, 1, 9, 0, 0)    # baseline accepted (before builds)
T1 = datetime(2026, 1, 1, 10, 0, 0)   # producers build
T2 = datetime(2026, 1, 1, 11, 0, 0)   # model approved

_PRODUCERS = ("import-edd", "export-snapshot", "apply-screening",
              "export-figures", "run-gw-model-pipeline")


def _run(h, tool, when, status="success", event=EVENT):
    h.write(RunRecord(
        run_id=f"{tool}-{when.isoformat()}", tool_name=tool, site_id=SITE,
        event_id=event, started_at=when, finished_at=when, status=status,
        inputs={}, outputs={}, qa_count_error=0, qa_count_warning=0,
        qa_count_info=0, message="boom" if status == "error" else ""))


def _world(tmp_path, *, approve=True, run_tools=_PRODUCERS,
           import_status="success"):
    files = {}
    for kind, content in (("workbook", "WB"), ("site-config", "SC"),
                          ("screening", "SL"), ("figure-spec", "FS")):
        p = tmp_path / f"{kind}.dat"
        p.write_text(content)
        files[kind] = p
    reg = SourceRegistry(tmp_path / "src.csv")
    es.accept_baseline(site_id=SITE, event_id=EVENT, inputs=dict(files),
                       source_registry=reg, now=T0.isoformat())
    h = RunHistory(tmp_path / "rh.csv")
    for tool in run_tools:
        _run(h, tool, T1,
             status=import_status if tool == "import-edd" else "success")
    if approve:
        _run(h, "approve-gw-model", T2)
    return files, reg, h


def _states(files, reg, h, open_review=0):
    report = es.classify_event(
        site_id=SITE, event_id=EVENT,
        inputs={k: files.get(k) for k in es.FILE_INPUT_KINDS},
        run_history=h, source_registry=reg, open_review_count=open_review)
    return report, {a.kind: a.state for a in report.artifacts}


def test_all_current(tmp_path):
    files, reg, h = _world(tmp_path)
    report, states = _states(files, reg, h)
    assert set(states.values()) == {es.CURRENT}
    assert report.exit_code() == 0


_ALL = ("canonical-import", "snapshot", "screening-evaluation",
        "figures", "groundwater-surface")


@pytest.mark.parametrize("changed, expected", [
    # Foundational inputs of canonical-import: staleness propagates to all.
    ("workbook", {k: es.STALE for k in _ALL}),
    ("site-config", {k: es.STALE for k in _ALL}),
    # Narrow inputs: ONLY their one dependent moves; everything else current.
    ("screening", {**{k: es.CURRENT for k in _ALL},
                   "screening-evaluation": es.STALE}),
    ("figure-spec", {**{k: es.CURRENT for k in _ALL},
                     "figures": es.STALE}),
])
def test_input_change_invalidates_only_correct_downstream(
        tmp_path, changed, expected):
    files, reg, h = _world(tmp_path)
    files[changed].write_text("MUTATED")  # new content -> new sha256
    _report, states = _states(files, reg, h)
    assert states == expected


def test_approved_model_pending_awaits_only_the_surface(tmp_path):
    files, reg, h = _world(tmp_path, approve=False)
    _report, states = _states(files, reg, h)
    assert states["groundwater-surface"] == es.AWAITING_REVIEW
    assert all(v == es.CURRENT for k, v in states.items()
               if k != "groundwater-surface")


def test_open_reviewer_comment_awaits_only_the_figure_package(tmp_path):
    files, reg, h = _world(tmp_path)
    _report, states = _states(files, reg, h, open_review=2)
    assert states["figures"] == es.AWAITING_REVIEW
    assert all(v == es.CURRENT for k, v in states.items()
               if k != "figures")


def test_missing_import_makes_downstream_stale(tmp_path):
    files, reg, h = _world(
        tmp_path, run_tools=[t for t in _PRODUCERS if t != "import-edd"])
    _report, states = _states(files, reg, h)
    assert states["canonical-import"] == es.MISSING
    assert states["snapshot"] == es.STALE
    assert states["screening-evaluation"] == es.STALE


def test_failed_import_reports_failed_and_propagates(tmp_path):
    files, reg, h = _world(tmp_path, import_status="error")
    report, states = _states(files, reg, h)
    assert states["canonical-import"] == es.FAILED
    assert states["snapshot"] == es.STALE
    assert report.exit_code() == 5  # failed outranks the downstream stale


def test_rebaseline_then_rebuild_two_ledger_rule(tmp_path):
    """The BS-1 partial-rebuild case: re-accept marks the dependent rebuild-
    pending (hash matches, baseline newer than build); a rebuild clears it."""
    files, reg, h = _world(tmp_path)
    t3 = datetime(2026, 1, 1, 12, 0, 0)
    es.accept_baseline(site_id=SITE, event_id=EVENT,
                       inputs={"screening": files["screening"]},
                       source_registry=reg, now=t3.isoformat())
    report, states = _states(files, reg, h)
    assert states["screening-evaluation"] == es.STALE
    cause = "; ".join(c for a in report.artifacts
                      if a.kind == "screening-evaluation" for c in a.causes)
    assert "rebuild pending" in cause
    # rebuild apply-screening after the re-baseline -> current again
    _run(h, "apply-screening", datetime(2026, 1, 1, 13, 0, 0))
    _report2, states2 = _states(files, reg, h)
    assert states2["screening-evaluation"] == es.CURRENT


def test_failed_approval_does_not_count_as_approval(tmp_path):
    """P1-2: a failed approve-gw-model run must NOT bless the surface."""
    files, reg, h = _world(tmp_path, approve=False)
    _run(h, "approve-gw-model", T2, status="error")  # failed, after the build
    _report, states = _states(files, reg, h)
    assert states["groundwater-surface"] == es.AWAITING_REVIEW


def test_foreign_registry_row_does_not_hijack_baseline(tmp_path):
    """P2-2: a register-source-doc row whose notes match a kind but tool differs
    must not become the baseline."""
    files, reg, h = _world(tmp_path)
    reg.register(SourceDocRecord(
        registered_at=datetime(2026, 1, 1, 14, 0, 0).isoformat(),
        file_path="/elsewhere/other.xlsx", sha256="de" * 32, file_size_bytes=1,
        site_id=SITE, event_id=EVENT, tool="register-source-doc",
        notes="workbook"))  # notes collides with the workbook kind
    _report, states = _states(files, reg, h)
    assert states["canonical-import"] == es.CURRENT  # own baseline still wins


def test_tz_aware_baseline_timestamp_does_not_crash(tmp_path):
    """P2-3: a tz-aware registered_at must be normalized, not raise."""
    files = {}
    for kind, content in (("workbook", "WB"), ("site-config", "SC"),
                          ("screening", "SL"), ("figure-spec", "FS")):
        p = tmp_path / f"{kind}.dat"
        p.write_text(content)
        files[kind] = p
    reg = SourceRegistry(tmp_path / "src.csv")
    es.accept_baseline(site_id=SITE, event_id=EVENT, inputs=files,
                       source_registry=reg,
                       now="2026-01-01T09:00:00+05:00")  # tz-aware baseline
    h = RunHistory(tmp_path / "rh.csv")
    for tool in _PRODUCERS:
        _run(h, tool, T1)
    _run(h, "approve-gw-model", T2)
    _report, states = _states(files, reg, h)  # must not raise
    assert states["canonical-import"] == es.CURRENT  # 09:00 (naive) < T1


def test_exit_code_precedence_is_not_numeric_max():
    report = es.EventStatusReport("S", "E", (
        es.ArtifactStatus("a", es.AWAITING_REVIEW, "p"),
        es.ArtifactStatus("b", es.FAILED, "p"),
        es.ArtifactStatus("c", es.CURRENT, "p"),
    ))
    assert report.worst_state == es.FAILED  # failed > awaiting-review
    assert report.exit_code() == 5


def test_render_table_and_json_shape(tmp_path):
    files, reg, h = _world(tmp_path)
    report, _states_ = _states(files, reg, h)
    text = es.render_table(report)
    assert "Event status" in text and "canonical-import" in text
    d = report.as_dict()
    assert d["schema"] == 1
    assert {a["kind"] for a in d["artifacts"]} == set(_ALL)
    assert d["summary"]["current"] == len(_ALL)
