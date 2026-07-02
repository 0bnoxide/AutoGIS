from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.compliance_summary import (
    ComplianceRecord, ComplianceSummaryResult,
    compute_trend, build_compliance_summary, write_compliance_workbook,
)

_SL = {"Benzene": 5.0}
_ROWS = [
    # MW-01 Benzene: detected, exceeds, trend worsening
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "3.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2025-01-15"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "6.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2025-06-15"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "9.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
    # MW-02 Benzene: all ND
    {"LocationID": "MW-02", "AnalyteName": "Benzene", "ResultValue": "ND",
     "ResultQualifier": "ND", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
    # MW-03 Benzene: improving trend (below MCL)
    {"LocationID": "MW-03", "AnalyteName": "Benzene", "ResultValue": "4.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2025-01-15"},
    {"LocationID": "MW-03", "AnalyteName": "Benzene", "ResultValue": "2.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2025-06-15"},
    {"LocationID": "MW-03", "AnalyteName": "Benzene", "ResultValue": "1.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
]


def test_compute_trend_worsening():
    assert compute_trend([1.0, 2.0, 3.0], ["2025-01", "2025-06", "2026-01"]) == "worsening"


def test_compute_trend_improving():
    assert compute_trend([3.0, 2.0, 1.0], ["2025-01", "2025-06", "2026-01"]) == "improving"


def test_compute_trend_insufficient():
    assert compute_trend([5.0, 4.0], ["2025-01", "2025-06"]) == "insufficient_data"


def test_mw01_ever_exceeded():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    mw01 = next(r for r in result.records
                if r.location_id == "MW-01" and r.analyte_name == "Benzene")
    assert mw01.ever_exceeded is True
    assert mw01.exceedance_count == 2  # 6.0 and 9.0 > 5.0


def test_mw01_trend_worsening():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    mw01 = next(r for r in result.records
                if r.location_id == "MW-01" and r.analyte_name == "Benzene")
    assert mw01.trend == "worsening"


def test_mw02_nd_not_detected():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    mw02 = next(r for r in result.records
                if r.location_id == "MW-02" and r.analyte_name == "Benzene")
    assert mw02.ever_detected is False
    assert mw02.ever_exceeded is False


def test_mw03_improving():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    mw03 = next(r for r in result.records
                if r.location_id == "MW-03" and r.analyte_name == "Benzene")
    assert mw03.trend == "improving"


def test_locations_with_exceedances():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    assert result.locations_with_exceedances == 1  # only MW-01 exceeds


def test_max_ratio():
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    mw01 = next(r for r in result.records
                if r.location_id == "MW-01" and r.analyte_name == "Benzene")
    assert mw01.max_ratio == pytest.approx(9.0 / 5.0)


def test_zero_screening_level_flags_exceedance():
    rows = [
        {"LocationID": "MW-04", "AnalyteName": "Lead", "ResultValue": "0.5",
         "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
    ]
    result = build_compliance_summary(rows, screening_levels={"Lead": 0.0})
    mw04 = next(r for r in result.records
                if r.location_id == "MW-04" and r.analyte_name == "Lead")
    assert mw04.ever_exceeded is True
    assert mw04.exceedance_count == 1


def test_write_workbook(tmp_path):
    result = build_compliance_summary(_ROWS, screening_levels=_SL)
    out = tmp_path / "compliance.xlsx"
    write_compliance_workbook(result, out)
    assert out.exists()
    wb = openpyxl.load_workbook(str(out))
    assert len(wb.sheetnames) >= 2
