import pytest
from autogis.core.envmon.max_result_dataset import (
    build_max_result_dataset, MaxResultRecord,
)

_ROWS = [
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "5.2", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15", "SampleID": "S1"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "12.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-06-15", "SampleID": "S2"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2025-06-15", "SampleID": "S0"},
    {"LocationID": "MW-02", "AnalyteName": "Benzene",
     "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15", "SampleID": "S3"},
]
_SL = {"Benzene": 5.0}


def test_max_detected_selected():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.max_result_value == 12.0
    assert mw01.max_sample_id == "S2"


def test_detection_count():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.detection_count == 2
    assert mw01.total_sample_count == 3


def test_all_nd_excluded_by_default():
    records = build_max_result_dataset(_ROWS)
    ids = [r.location_id for r in records]
    assert "MW-02" not in ids


def test_all_nd_included_with_flag():
    records = build_max_result_dataset(_ROWS, include_nd=True)
    ids = [r.location_id for r in records]
    assert "MW-02" in ids


def test_exceedance_ratio_computed():
    records = build_max_result_dataset(_ROWS, screening_levels=_SL)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.exceedance_ratio == pytest.approx(12.0 / 5.0)
    assert mw01.has_exceedance is True


def test_date_filter():
    records = build_max_result_dataset(_ROWS, date_from="2026-01-01")
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.total_sample_count == 2  # S0 excluded


def test_analyte_filter():
    records = build_max_result_dataset(_ROWS, analytes=["Toluene"])
    assert len(records) == 0  # no Toluene rows


def test_first_last_detection_dates():
    records = build_max_result_dataset(_ROWS)
    mw01 = next(r for r in records if r.location_id == "MW-01")
    assert mw01.first_detection_date == "2026-01-15"
    assert mw01.last_detection_date == "2026-06-15"
