from pathlib import Path
import csv
import pytest
from autogis.core.envmon.field_completeness_validator import (
    CompletenessIssue, CompletenessResult,
    validate_field_completeness, write_completeness_report,
)

_PLAN = [
    {"SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
    {"SampleID": "H281-MW02-20260615-GW", "LocationID": "MW-02",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
    {"SampleID": "H281-MW03-20260615-GW", "LocationID": "MW-03",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
]
_RESULTS = [
    {"SampleID": "H281-MW01-20260615-GW", "AnalysisDate": "2026-06-20"},
    {"SampleID": "H281-MW02-20260615-GW", "AnalysisDate": "2026-06-22"},
    # MW-03 not in results — not sampled
    # MW-99 unexpected
    {"SampleID": "H281-MW99-20260615-GW", "AnalysisDate": "2026-06-20"},
]


def test_matched_count():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert result.matched_count == 2


def test_not_sampled():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert "H281-MW03-20260615-GW" in result.not_sampled
    assert any(i.issue_type == "not_sampled" for i in result.issues)


def test_unexpected_result():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert "H281-MW99-20260615-GW" in result.unexpected
    assert any(i.issue_type == "unexpected_result" for i in result.issues)


def test_hold_time_exceeded():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-20"}]  # 19 days
    result = validate_field_completeness(plan, results)
    assert any(i.issue_type == "hold_time_exceeded" for i in result.issues)


def test_hold_time_ok():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-10"}]  # 9 days
    result = validate_field_completeness(plan, results)
    assert not any(i.issue_type == "hold_time_exceeded" for i in result.issues)


def test_duplicate_sample_id():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-05"},
               {"SampleID": "S1", "AnalysisDate": "2026-06-05"}]
    result = validate_field_completeness(plan, results)
    assert any(i.issue_type == "duplicate_sample_id" for i in result.issues)


def test_planned_count():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert result.planned_count == 3
    assert result.received_count == 3


def test_write_completeness_report(tmp_path):
    result = validate_field_completeness(_PLAN, _RESULTS)
    out = tmp_path / "issues.csv"
    write_completeness_report(result, out)
    assert out.exists()
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) > 0
    assert "issue_type" in rows[0]


def test_all_matched_no_issues():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-05"}]
    result = validate_field_completeness(plan, results)
    assert len(result.issues) == 0
    assert result.matched_count == 1
