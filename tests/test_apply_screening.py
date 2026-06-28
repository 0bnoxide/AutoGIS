"""Unit tests for apply_screening (Tool 3.5)."""
import dataclasses
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.envmon.apply_screening import apply_screening_levels
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(analyte="Benzene", num=5.0, units="ug/L", matrix="GW",
       nd=False, exceed=None):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix=matrix,
        LocationID="MW-1", SampleID="S1", ParentSampleID="",
        SampleDate=date(2026, 4, 1), DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=str(num or "ND"),
        ResultNumeric=num, ReportingLimit=None, DetectionLimit=None,
        Units=units, Qualifier="", IsNonDetect=int(nd),
        IsDetected=int(not nd), IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=exceed, DisplayText=str(num or "ND"),
        DisplayColorClass="", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


SCREENING = {"Benzene": {"GW": {"unit": "ug/L", "level": 5.0, "source": "RBSL"}}}


def test_exceedance_detected():
    qa = QACollector()
    results = apply_screening_levels([_r("Benzene", 10.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 1
    assert results[0].DisplayColorClass == "EXCEED"
    assert results[0].ScreeningLevel == 5.0
    assert results[0].ScreeningLevelSource == "RBSL"


def test_no_exceedance():
    qa = QACollector()
    results = apply_screening_levels([_r("Benzene", 3.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 0
    assert results[0].DisplayColorClass == "OK"


def test_nondetect_never_exceeds():
    qa = QACollector()
    r = _r("Benzene", None, nd=True)
    results = apply_screening_levels([r], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 0
    assert results[0].DisplayColorClass == "OK"


def test_no_screening_level_passthrough():
    qa = QACollector()
    results = apply_screening_levels([_r("Toluene", 99.0)], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel is None  # unchanged


def test_multiple_records():
    qa = QACollector()
    results = apply_screening_levels([
        _r("Benzene", 10.0),
        _r("Benzene", 3.0),
        _r("Toluene", 99.0),
    ], SCREENING, qa=qa)
    assert results[0].ExceedsScreeningLevel == 1
    assert results[1].ExceedsScreeningLevel == 0
    assert results[2].ExceedsScreeningLevel is None


def test_qa_info_emitted():
    qa = QACollector()
    apply_screening_levels([_r("Benzene", 5.0)], SCREENING, qa=qa)
    assert any(r.category == "apply_screening_complete" for r in qa.records)


def test_boundary_value_exact_equal_not_exceed():
    qa = QACollector()
    results = apply_screening_levels([_r("Benzene", 5.0)], SCREENING, qa=qa)
    # Exactly at threshold does NOT exceed (> not >=)
    assert results[0].ExceedsScreeningLevel == 0


def test_empty_results():
    qa = QACollector()
    results = apply_screening_levels([], SCREENING, qa=qa)
    assert results == []
