"""Unit tests for history_report (Tool 10.1)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.envmon.history_report import build_history_report, HistorySummaryRow
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, num, sample_date, nd=False, not_analyzed=False):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=sample_date, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=str(num or "ND"),
        ResultNumeric=num, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=int(nd),
        IsDetected=int(not nd), IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=int(not_analyzed), IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText=str(num or "ND"),
        DisplayColorClass="", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


D1, D2 = date(2026, 1, 1), date(2026, 4, 1)


def test_basic_summary():
    results = [_r("MW-1", "Benzene", 5.0, D1), _r("MW-1", "Benzene", 10.0, D2)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert len(rows) == 1
    r = rows[0]
    assert r.NTotal == 2 and r.NDetects == 2 and r.NNonDetects == 0
    assert r.MinResult == 5.0 and r.MaxResult == 10.0
    assert r.TrendVsPrevious == "INCREASE"


def test_nondetect_counted():
    results = [_r("MW-1", "Benzene", None, D1, nd=True),
               _r("MW-1", "Benzene", None, D2, nd=True)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].NNonDetects == 2
    assert rows[0].TrendVsPrevious == "ND_BOTH"


def test_not_analyzed_excluded():
    results = [_r("MW-1", "Benzene", 5.0, D1),
               _r("MW-1", "Benzene", 5.0, D2, not_analyzed=True)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].NTotal == 1


def test_stable_trend():
    results = [_r("MW-1", "Benzene", 10.0, D1), _r("MW-1", "Benzene", 10.5, D2)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].TrendVsPrevious == "STABLE"


def test_decrease_trend():
    results = [_r("MW-1", "Benzene", 10.0, D1), _r("MW-1", "Benzene", 5.0, D2)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].TrendVsPrevious == "DECREASE"


def test_insufficient_data_single_event():
    results = [_r("MW-1", "Benzene", 5.0, D1)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].TrendVsPrevious == "INSUFFICIENT_DATA"


def test_multiple_groups():
    results = [
        _r("MW-1", "Benzene", 5.0, D1),
        _r("MW-2", "Benzene", 3.0, D1),
        _r("MW-1", "Toluene", 2.0, D1),
    ]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert len(rows) == 3


def test_qa_info_emitted():
    results = [_r("MW-1", "Benzene", 5.0, D1)]
    qa = QACollector()
    build_history_report(results, qa=qa)
    assert any(r.category == "history_report_complete" for r in qa.records)
