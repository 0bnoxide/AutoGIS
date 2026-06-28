"""Unit tests for identify_data_gaps (Tool 4.10)."""
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, d=date(2026, 4, 1)):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="H281", Matrix="GW", LocationID=loc,
        SampleID=f"{loc}-{analyte}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText="1.0", ResultNumeric=1.0, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=0, DisplayText="1.0",
        DisplayColorClass="OK", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


SCHEDULE = {
    "site_id": "H281", "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2", "MW-3"],
    "required_analytes": ["Benzene", "Toluene", "Ethylbenzene"],
    "well_analytes": {"MW-3": ["Benzene"]},
}


def _types(gaps):
    out = {}
    for g in gaps:
        out.setdefault(g.GapType, set()).add((g.LocationID, g.AnalyteCanonicalName))
    return out


def test_missing_well():
    # MW-2 has no results at all
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-2", "") in t["MISSING_WELL"]
    assert any(r.severity == "ERROR" and r.category == "missing_well"
               for r in qa.records)


def test_missed_analyte_respects_per_well_override():
    # MW-1 missing Toluene; MW-3 only needs Benzene (override) -> no miss
    results = [_r("MW-1", "Benzene"), _r("MW-1", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-1", "Toluene") in t["MISSED_ANALYTE"]
    # MW-3 override means Toluene/Ethylbenzene are NOT required there
    assert all(loc != "MW-3" for (loc, _a) in t.get("MISSED_ANALYTE", set()))


def test_dry_well_suppresses_missing_well():
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={"MW-2": "dry"}, qa=qa)
    t = _types(gaps)
    assert "MISSING_WELL" not in t or ("MW-2", "") not in t["MISSING_WELL"]
    assert ("MW-2", "") in t["DRY_OR_INACCESSIBLE"]


def test_unexpected_well_warns():
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    results += [_r("MW-99", "Benzene")]   # not in network
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-99", "") in t["UNEXPECTED_WELL"]
    assert any(r.category == "unexpected_well" and r.severity == "WARNING"
               for r in qa.records)


def test_event_window_filters_old_results():
    # MW-1 only has a result far outside the window -> treated as missing
    results = [_r("MW-1", a, d=date(2025, 1, 1))
               for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    assert ("MW-1", "") in _types(gaps)["MISSING_WELL"]


def test_no_event_date_uses_all_results():
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=None,
                              window_days=30, dry_wells={}, qa=qa)
    assert not any(g.GapType in ("MISSING_WELL", "MISSED_ANALYTE") for g in gaps)


def test_schedule_without_well_analytes():
    sched = {
        "site_id": "H281", "event_label": "2026Q2",
        "wells": ["MW-1"],
        "required_analytes": ["Benzene"],
    }
    results = [_r("MW-1", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, sched, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    assert not any(g.GapType in ("MISSING_WELL", "MISSED_ANALYTE") for g in gaps)
