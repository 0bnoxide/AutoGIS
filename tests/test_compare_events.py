"""Unit tests for compare_events (Tool 4.7)."""
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.envmon.compare_events import compare_events, ComparisonRecord
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, d, *, raw="1.0", num=1.0, detected=1, nondetect=0,
       exceed=0, matrix="GW"):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix=matrix, LocationID=loc,
        SampleID=f"{loc}-{analyte}-{d}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText=raw, ResultNumeric=num, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="",
        IsNonDetect=nondetect, IsDetected=detected, IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=exceed,
        DisplayText=raw, DisplayColorClass="OK", SourceWorkbook="t.xlsx",
        SourceSheet="S1", SourceRow=1, SourceColumn="A", SourceCell="A1")


def test_increase_decrease_stable():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="20", num=20.0),  # +100% up
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="20", num=20.0),
        _r("MW-2", "Benzene", date(2026, 4, 1), raw="10", num=10.0),  # -50% down
        _r("MW-3", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-3", "Benzene", date(2026, 4, 1), raw="10.5", num=10.5),  # +5% stable
    ]
    qa = QACollector()
    out = {(c.LocationID): c for c in compare_events(recs, qa)}
    assert out["MW-1"].TrendClass == "INCREASED"
    assert out["MW-1"].PercentChange == 100.0
    assert out["MW-2"].TrendClass == "DECREASED"
    assert out["MW-3"].TrendClass == "STABLE"


def test_new_and_no_longer_detected():
    recs = [
        # prev nondetect, current detected -> NEW_DETECTION
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="<1", num=None,
           detected=0, nondetect=1),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="3", num=3.0),
        # prev detected, current nondetect -> NO_LONGER_DETECTED
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="3", num=3.0),
        _r("MW-2", "Benzene", date(2026, 4, 1), raw="<1", num=None,
           detected=0, nondetect=1),
    ]
    qa = QACollector()
    out = {c.LocationID: c for c in compare_events(recs, qa)}
    assert out["MW-1"].TrendClass == "NEW_DETECTION"
    assert out["MW-1"].Delta is None
    assert out["MW-2"].TrendClass == "NO_LONGER_DETECTED"


def test_single_event_is_new_detection_no_previous():
    recs = [_r("MW-1", "Benzene", date(2026, 4, 1), raw="3", num=3.0)]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.PreviousEventDate is None
    assert c.TrendClass == "NEW_DETECTION"


def test_exceedance_flags_mapping():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0, exceed=0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0, exceed=1),
    ]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.CurrentExceedance == "Y"
    assert c.PreviousExceedance == "N"


def test_current_event_date_override_skips_series_without_record():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0),
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="3", num=3.0),  # no Apr record
    ]
    qa = QACollector()
    out = compare_events(recs, qa, current_event_date=date(2026, 4, 1))
    locs = {c.LocationID for c in out}
    assert locs == {"MW-1"}
    assert any(r.category == "no_current_record" for r in qa.records)


def test_mixed_matrix_warns_and_splits():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0, matrix="GW"),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0, matrix="GW"),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="2", num=2.0, matrix="SOIL"),
    ]
    qa = QACollector()
    out = compare_events(recs, qa)
    assert any(r.category == "mixed_matrix" for r in qa.records)
    assert {c.Matrix for c in out} == {"GW", "SOIL"}


def test_both_nondetect():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="<1", num=None,
           detected=0, nondetect=1),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="<1", num=None,
           detected=0, nondetect=1),
    ]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.TrendClass == "NONDETECT_BOTH"
    assert c.Delta is None
    assert c.PercentChange is None


def test_zero_previous_value_warns():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="0", num=0.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="5", num=5.0),
    ]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.PercentChange is None
    assert any(r.category == "percent_change_zero_base" for r in qa.records)
