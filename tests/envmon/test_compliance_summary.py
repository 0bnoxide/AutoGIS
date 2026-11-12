import inspect
from pathlib import Path
import pytest
import openpyxl
import functools
from autogis.core.envmon import compliance_summary as cs
from autogis.core.envmon.compliance_summary import (
    ComplianceRecord, ComplianceSummaryResult,
    build_compliance_summary, write_compliance_workbook,
)

# Slope-logic tests below use 3-point series; the production default is 4 (#615).
compute_trend = functools.partial(cs.compute_trend, min_points=3)

_SL = {"Benzene": 5.0}
_ROWS = [
    # MW-01 Benzene: detected, exceeds, trend worsening
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "1.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2024-06-15"},
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
    {"LocationID": "MW-03", "AnalyteName": "Benzene", "ResultValue": "4.5",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2024-06-15"},
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


def test_write_workbook_has_no_silent_group_map_keyword():
    assert "group_map" not in inspect.signature(
        write_compliance_workbook).parameters


def test_compute_trend_is_unit_independent():
    dates = ["2024-01", "2024-02", "2024-03"]
    ug = [1.0, 1.5, 2.0]
    mg = [v / 1000 for v in ug]
    assert compute_trend(ug, dates) == compute_trend(mg, dates) == "worsening"
    flat = [100.0, 100.5, 101.0]  # +0.5/month on ~100 is <1%/month
    assert compute_trend(flat, dates) == "stable"


def test_compute_trend_negative_and_zero_mean():
    dates = ["2024-01", "2024-02", "2024-03"]
    assert compute_trend([-5.0, -3.0, -1.0], dates) == "worsening"  # e.g. ORP rising
    assert compute_trend([0.0, 0.0, 0.0], dates) == "stable"


def test_compute_trend_boundary_is_unit_independent():
    dates = ["2024-01", "2024-02", "2024-03"]
    for vals in ([101.0, 100.0, 99.0], [99.0, 100.0, 101.0]):
        verdicts = {compute_trend([v * k for v in vals], dates)
                    for k in (1, 1e-3, 1e-6, 1e3)}
        assert verdicts == {"stable"}


def test_compute_trend_resolves_days_within_a_month():
    """#617: same-month samples shared one x and always read stable."""
    days = ["2024-01-01", "2024-01-15", "2024-01-30"]
    assert compute_trend([1.0, 2.0, 3.0], days) == "worsening"
    assert compute_trend([3.0, 2.0, 1.0], days) == "improving"
    # mixed precision still parses; month-only dates keep their old meaning
    assert compute_trend([1.0, 2.0, 3.0], ["2024-01", "2024-06-15", "2025-01"]) == "worsening"


def test_compute_trend_impossible_day_keeps_month_resolution():
    """#624 review: a bad day must not drop the series to row-order index fallback."""
    # newest row first; values rise over time
    assert compute_trend([3.0, 2.0, 1.0],
                         ["2024-06-15", "2024-03-15", "2023-02-29"]) == "worsening"


@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_non_finite_result_is_not_a_detection(bad):
    """#618: float("nan"/"inf") parsed, so they counted as detections/exceedances."""
    rows = [{"LocationID": "MW-9", "AnalyteName": "Benzene", "ResultValue": v,
             "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": d}
            for v, d in ((bad, "2025-01-15"), ("1", "2025-02-15"), ("2", "2025-03-15"))]
    rec = build_compliance_summary(rows, screening_levels={"Benzene": 5.0}).records[0]
    assert rec.detection_count == 2
    assert rec.max_value == 2.0
    assert rec.exceedance_count == 0


def test_trend_requires_four_points_by_default():
    """#615 policy: a trend needs at least 4 points."""
    d = ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert cs.compute_trend([1.0, 2.0, 3.0], d[:3]) == "insufficient_data"
    assert cs.compute_trend([1.0, 2.0, 3.0, 4.0], d) == "worsening"


def test_nondetects_enter_trend_at_half_rl():
    """#615 policy: NDs count at RL/2, so a well going to ND reads improving."""
    rows = [{"LocationID": "MW-7", "AnalyteName": "Benzene", "ResultValue": v,
             "ResultQualifier": q, "ReportedUnits": "ug/L", "SampleDate": d,
             "ReportingLimit": "1.0"}
            for v, q, d in (("8", "", "2024-01-15"), ("6", "", "2024-02-15"),
                            ("ND", "ND", "2024-03-15"), ("ND", "ND", "2024-04-15"))]
    rec = build_compliance_summary(rows, screening_levels={"Benzene": 5.0}).records[0]
    assert rec.trend == "improving"
    assert rec.detection_count == 2  # NDs feed the trend only, not detection stats
    rows[2].pop("ReportingLimit")
    rows[3].pop("ReportingLimit")
    res = build_compliance_summary(rows, screening_levels={"Benzene": 5.0})
    assert res.records[0].trend == "insufficient_data"
    assert any(r.category == "trend_nondetect_no_limit" for r in res.qa.records)
