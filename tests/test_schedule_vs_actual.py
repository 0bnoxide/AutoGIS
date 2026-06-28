"""Tests for schedule vs actual comparison module."""
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
from autogis.core.envmon.schedule_vs_actual import (
    ScheduleGapRecord,
    compare_schedule_vs_actual,
    load_schedule_yaml,
    write_gap_csv,
)


def _r(loc, analyte, dt=date(2026, 4, 15)):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=dt, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText="5.0",
        ResultNumeric=5.0, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=0, IsDetected=1,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0, IsNotSampled=0,
        IsNotMeasured=0, ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText="5.0", DisplayColorClass="",
        SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1",
    )


SCHEDULE = {
    "site_id": "H281",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
    "well_analytes": {"MW-2": ["Arsenic"]},
}


def test_all_sampled():
    results = [
        _r("MW-1", "Benzene"), _r("MW-1", "Toluene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    statuses = {r.Status for r in rows}
    assert "MISSING" not in statuses
    assert "SAMPLED" in statuses


def test_missing_analyte():
    # MW-1 missing Toluene
    results = [
        _r("MW-1", "Benzene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    missing = [r for r in rows if r.Status == "MISSING"]
    assert len(missing) == 1
    assert missing[0].LocationID == "MW-1"
    assert missing[0].AnalyteName == "Toluene"


def test_unexpected_well():
    results = [
        _r("MW-1", "Benzene"), _r("MW-1", "Toluene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
        _r("MW-99", "Benzene"),  # unexpected
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    unexpected = [r for r in rows if r.Status == "UNEXPECTED"]
    assert len(unexpected) == 1
    assert unexpected[0].LocationID == "MW-99"


def test_event_date_inferred_from_results():
    results = [_r("MW-1", "Benzene", dt=date(2026, 4, 15))]
    qa = QACollector()
    rows = compare_schedule_vs_actual(results, SCHEDULE, qa=qa)
    # Should not crash; event_date inferred
    assert rows


def test_window_filters_old_results():
    old = _r("MW-1", "Benzene", dt=date(2025, 1, 1))
    new = _r("MW-2", "Benzene", dt=date(2026, 4, 15))
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        [old, new], SCHEDULE,
        event_date=date(2026, 4, 15), window_days=30, qa=qa)
    # MW-1 old result outside window: Benzene+Toluene MISSING for MW-1
    mw1_missing = [r for r in rows if r.LocationID == "MW-1" and r.Status == "MISSING"]
    assert any(r.AnalyteName == "Benzene" for r in mw1_missing)


def test_write_gap_csv(tmp_path):
    rows = [
        ScheduleGapRecord("H281", "MW-1", "Benzene", "MISSING",
                          "Not found", date(2026, 4, 15))
    ]
    out = tmp_path / "gaps.csv"
    write_gap_csv(rows, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "SiteID" in text
    assert "MISSING" in text


def test_load_schedule_yaml(tmp_path):
    yaml_path = tmp_path / "schedule.yaml"
    yaml_path.write_text(
        "site_id: H281\nwells:\n  - MW-1\nrequired_analytes:\n  - Benzene\n",
        encoding="utf-8",
    )
    sched = load_schedule_yaml(yaml_path)
    assert sched["site_id"] == "H281"
    assert "MW-1" in sched["wells"]


def test_qa_info_emitted():
    qa = QACollector()
    compare_schedule_vs_actual([], SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    assert any(r.category == "schedule_vs_actual_complete" for r in qa.records)
