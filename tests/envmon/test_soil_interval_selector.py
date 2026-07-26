from pathlib import Path
import csv
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon.soil_interval_selector import (
    SoilInterval, IntervalTier,
    assign_tier, select_intervals, load_soil_results_csv,
)


def _interval(
    *,
    result_value=1.0,
    is_detect=True,
    exceeds_screening=False,
    screening_level=5.0,
    analyte_name="Benzene",
    location_id="B-01",
    top_depth_ft=0.0,
    bottom_depth_ft=2.0,
    units="mg/kg",
):
    return SoilInterval(
        location_id=location_id, top_depth_ft=top_depth_ft,
        bottom_depth_ft=bottom_depth_ft, analyte_name=analyte_name,
        result_value=result_value, is_detect=is_detect,
        exceeds_screening=exceeds_screening, screening_level=screening_level,
        units=units,
    )


# --- assign_tier ------------------------------------------------------------

def test_assign_tier_hotspot():
    iv = _interval(result_value=10.0, is_detect=True, exceeds_screening=True)
    assert assign_tier(iv) == IntervalTier.HOTSPOT


def test_assign_tier_detect():
    iv = _interval(result_value=1.0, is_detect=True, exceeds_screening=False)
    assert assign_tier(iv) == IntervalTier.DETECT


def test_assign_tier_nd():
    iv = _interval(result_value=None, is_detect=False, exceeds_screening=False,
                   screening_level=None)
    assert assign_tier(iv) == IntervalTier.ND


def test_assign_tier_no_data():
    iv = _interval(result_value=None, is_detect=False, exceeds_screening=False,
                   screening_level=5.0)
    assert assign_tier(iv) == IntervalTier.NO_DATA


# --- select_intervals -------------------------------------------------------

_BASE = [
    _interval(location_id="B-01", analyte_name="Benzene",
              result_value=10.0, is_detect=True, exceeds_screening=True,
              top_depth_ft=0.0, bottom_depth_ft=2.0),
    _interval(location_id="B-01", analyte_name="TPH",
              result_value=50.0, is_detect=True, exceeds_screening=False,
              top_depth_ft=0.0, bottom_depth_ft=2.0),
    _interval(location_id="B-02", analyte_name="Benzene",
              result_value=None, is_detect=False, exceeds_screening=False,
              top_depth_ft=0.0, bottom_depth_ft=2.0, screening_level=5.0),
    _interval(location_id="B-01", analyte_name="Benzene",
              result_value=2.0, is_detect=True, exceeds_screening=False,
              top_depth_ft=10.0, bottom_depth_ft=12.0),
]


def test_select_intervals_returns_all_when_no_filters():
    assert len(select_intervals(_BASE)) == 4


def test_select_intervals_output_has_display_tier():
    assert all("display_tier" in row for row in select_intervals(_BASE))


def test_select_intervals_filter_by_tier_hotspot():
    out = select_intervals(_BASE, tiers=["HOTSPOT"])
    assert all(row["display_tier"] == "HOTSPOT" for row in out)
    assert len(out) == 1


def test_select_intervals_filter_by_analyte():
    out = select_intervals(_BASE, analytes=["Benzene"])
    assert {row["analyte_name"] for row in out} == {"Benzene"}
    assert len(out) == 3


def test_select_intervals_filter_by_max_depth():
    out = select_intervals(_BASE, max_depth_ft=5.0)
    assert all(row["top_depth_ft"] <= 5.0 for row in out)
    assert len(out) == 3


def test_select_intervals_output_fields():
    row = select_intervals(_BASE[:1])[0]
    required = {
        "location_id", "top_depth_ft", "bottom_depth_ft", "analyte_name",
        "result_value", "is_detect", "exceeds_screening", "screening_level",
        "units", "display_tier",
    }
    assert required.issubset(row.keys())


# --- load_soil_results_csv --------------------------------------------------

def _write_soil_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "LocationID", "TopDepthFt", "BottomDepthFt",
            "AnalyteName", "ResultValue", "ResultQualifier",
            "ReportedUnits", "ScreeningLevel", "ExceedsScreeningLevel",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_load_soil_results_csv_basic(tmp_path):
    csv_path = tmp_path / "soil.csv"
    _write_soil_csv(csv_path, [
        {"LocationID": "B-01", "TopDepthFt": "0", "BottomDepthFt": "2",
         "AnalyteName": "Benzene", "ResultValue": "10.5",
         "ResultQualifier": "", "ReportedUnits": "mg/kg",
         "ScreeningLevel": "5.0", "ExceedsScreeningLevel": "True"},
        {"LocationID": "B-02", "TopDepthFt": "2", "BottomDepthFt": "4",
         "AnalyteName": "Benzene", "ResultValue": "",
         "ResultQualifier": "ND", "ReportedUnits": "mg/kg",
         "ScreeningLevel": "5.0", "ExceedsScreeningLevel": "False"},
    ])
    intervals = load_soil_results_csv(csv_path)
    assert len(intervals) == 2
    assert intervals[0].exceeds_screening is True
    assert intervals[0].is_detect is True
    assert intervals[0].result_value == pytest.approx(10.5)


def test_load_soil_results_csv_nd_qualifier(tmp_path):
    csv_path = tmp_path / "soil.csv"
    _write_soil_csv(csv_path, [
        {"LocationID": "B-03", "TopDepthFt": "0", "BottomDepthFt": "2",
         "AnalyteName": "TPH", "ResultValue": "50",
         "ResultQualifier": "U", "ReportedUnits": "mg/kg",
         "ScreeningLevel": "", "ExceedsScreeningLevel": "False"},
    ])
    assert load_soil_results_csv(csv_path)[0].is_detect is False


# --- CLI --------------------------------------------------------------------

def test_select_soil_intervals_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "select-soil-intervals" in result.output


def test_cli_select_soil_intervals_end_to_end(tmp_path):
    src = tmp_path / "soil.csv"
    _write_soil_csv(src, [
        {"LocationID": "B-01", "TopDepthFt": "0", "BottomDepthFt": "2",
         "AnalyteName": "Benzene", "ResultValue": "10.5",
         "ResultQualifier": "", "ReportedUnits": "mg/kg",
         "ScreeningLevel": "5.0", "ExceedsScreeningLevel": "True"},
    ])
    out = tmp_path / "tiered.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--results-csv", str(src), "--out", str(out), "--tiers", "HOTSPOT",
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["display_tier"] == "HOTSPOT"


def test_cli_select_soil_intervals_rejects_unknown_tier(tmp_path):
    src = tmp_path / "soil.csv"
    _write_soil_csv(src, [])
    out = tmp_path / "tiered.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "select-soil-intervals",
        "--results-csv", str(src), "--out", str(out), "--tiers", "HOTSPT",
    ])
    assert result.exit_code == 2
    assert "Invalid value for --tiers" in result.output
    assert "HOTSPT" in result.output
    assert not out.exists()
