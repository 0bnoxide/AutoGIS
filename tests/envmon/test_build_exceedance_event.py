"""Tests for build_exceedance_event (Tool 4.4) — arcpy-free.

Checklist mirrors the Approved design spec
docs/superpowers/specs/2026-06-28-build-analytical-exceedance-event-design.md
"""
from pathlib import Path

import yaml

from autogis.core.envmon.build_exceedance_event import (
    classify_exceedance_tier,
    build_exceedance_event,
    load_screening_levels_yaml,
    write_exceedance_event_csv,
    ExceedanceEventRecord,
)

# MW-01 Benzene: two events, SL=5 -> ratios 1.2 (Jan) and 2.4 (Apr).
# MW-01 Toluene: ND both events. MW-02 Benzene: 2.0 (Jan, ratio 0.4 below).
_ROWS = [
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "6.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15",
     "SampleID": "S1"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "12.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-04-15",
     "SampleID": "S2"},
    {"LocationID": "MW-01", "AnalyteName": "Toluene", "ResultValue": "ND",
     "ResultQualifier": "ND", "ReportedUnits": "ug/L", "SampleDate": "2026-04-15",
     "SampleID": "S2"},
    {"LocationID": "MW-02", "AnalyteName": "Benzene", "ResultValue": "2.0",
     "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15",
     "SampleID": "S3"},
]
_SL = {"Benzene": 5.0, "Toluene": 100.0}


def _rec(records, loc, analyte):
    for r in records:
        if r.location_id == loc and r.analyte_name == analyte:
            return r
    raise AssertionError(f"no record for {loc}/{analyte}")


def test_classify_tier_midrange():
    assert classify_exceedance_tier(1.5) == "1x-2x"


def test_classify_tier_none():
    assert classify_exceedance_tier(None) == "below"


def test_classify_tier_boundaries():
    assert classify_exceedance_tier(0.5) == "below"
    assert classify_exceedance_tier(1.0) == "1x-2x"
    assert classify_exceedance_tier(2.0) == "2x-5x"
    assert classify_exceedance_tier(5.0) == "5x-10x"
    assert classify_exceedance_tier(25.0) == ">10x"


def test_max_exceedance_selects_highest_ratio():
    recs = build_exceedance_event(_ROWS, _SL, rule="max_exceedance_per_location")
    benz = _rec(recs, "MW-01", "Benzene")
    assert benz.sample_date == "2026-04-15"   # ratio 2.4 beats 1.2
    assert benz.result_value == 12.0
    assert benz.exceedance_tier == "2x-5x"


def test_has_exceedance_flag():
    recs = build_exceedance_event(_ROWS, _SL, rule="max_exceedance_per_location")
    assert _rec(recs, "MW-01", "Benzene").has_exceedance is True
    assert _rec(recs, "MW-02", "Benzene").has_exceedance is False  # ratio 0.4


def test_nondetect_has_detection_false():
    recs = build_exceedance_event(_ROWS, _SL, rule="max_exceedance_per_location")
    tol = _rec(recs, "MW-01", "Toluene")
    assert tol.has_detection is False
    assert tol.has_exceedance is False
    assert tol.exceedance_tier == "below"


def test_specific_event_date_filter():
    recs = build_exceedance_event(_ROWS, _SL, rule="specific_event_date",
                                  event_date="2026-01-15")
    dates = {r.sample_date for r in recs}
    assert dates == {"2026-01-15"}
    # Toluene only exists on 2026-04-15 -> excluded.
    assert all(r.analyte_name != "Toluene" for r in recs)


def test_date_range_latest():
    recs = build_exceedance_event(_ROWS, _SL, rule="date_range_latest",
                                  date_range=("2026-01-01", "2026-12-31"))
    benz = _rec(recs, "MW-01", "Benzene")
    assert benz.sample_date == "2026-04-15"  # latest within window


def test_load_screening_levels_yaml(tmp_path):
    p = tmp_path / "sl.yaml"
    p.write_text(yaml.dump({"Benzene": 5.0, "Lead": 15.0}), encoding="utf-8")
    sl = load_screening_levels_yaml(p)
    assert sl["Benzene"] == 5.0 and sl["Lead"] == 15.0


def test_write_csv_roundtrips_columns(tmp_path):
    recs = build_exceedance_event(_ROWS, _SL)
    out = tmp_path / "exc.csv"
    write_exceedance_event_csv(recs, out)
    assert out.exists()
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert "exceedance_ratio" in header and "exceedance_tier" in header
