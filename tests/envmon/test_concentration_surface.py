"""Headless tests for concentration_surface (Phase-5 slice 2, ADR-0085)."""
import datetime as dt

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.concentration_surface import (
    NONDETECT_RULES,
    build_surface_registry_rows,
    collect_concentration_points,
    raster_names,
    resolve_result_value,
    slug,
)

NOW = dt.datetime(2026, 7, 16, 12, 0, 0)


def _row(**kw):
    base = {"LocationID": "MW-1", "AnalyteCanonicalName": "Benzene",
            "ResultNumeric": "5.0", "IsNonDetect": "0",
            "ReportingLimit": "1.0", "DetectionLimit": "0.5"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Nondetect policy (ADR-0085 decision 4)
# ---------------------------------------------------------------------------

def test_detected_value_ignores_rule():
    for rule in NONDETECT_RULES:
        assert resolve_result_value(_row(), rule, QACollector()) == 5.0


def test_nondetect_exclude():
    assert resolve_result_value(
        _row(IsNonDetect="1"), "exclude", QACollector()) is None


def test_nondetect_half_rl():
    assert resolve_result_value(
        _row(IsNonDetect="1"), "half_rl", QACollector()) == 0.5


def test_nondetect_use_rl():
    assert resolve_result_value(
        _row(IsNonDetect="1"), "use_rl", QACollector()) == 1.0


def test_nondetect_use_zero():
    assert resolve_result_value(
        _row(IsNonDetect="1"), "use_zero", QACollector()) == 0.0


def test_nondetect_falls_back_to_detection_limit():
    row = _row(IsNonDetect="1", ReportingLimit="")
    assert resolve_result_value(row, "use_rl", QACollector()) == 0.5
    assert resolve_result_value(row, "half_rl", QACollector()) == 0.25


def test_nondetect_no_limits_excluded_with_warning():
    qa = QACollector()
    row = _row(IsNonDetect="1", ReportingLimit="", DetectionLimit="")
    assert resolve_result_value(row, "use_rl", qa) is None
    assert any(r.category == "nondetect_no_limit" for r in qa.records)


def test_unknown_rule_raises():
    with pytest.raises(ValueError, match="nondetect_rule"):
        resolve_result_value(_row(), "half_dl", QACollector())


# ---------------------------------------------------------------------------
# Point collection
# ---------------------------------------------------------------------------

def _write_inputs(tmp_path, result_rows):
    import csv
    results = tmp_path / "results.csv"
    fields = sorted({k for r in result_rows for k in r})
    with results.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(result_rows)
    coords = tmp_path / "coords.csv"
    coords.write_text(
        "location_id,x,y\nMW-1,0,0\nMW-2,100,0\nMW-3,0,100\n",
        encoding="utf-8")
    return results, coords


def test_collect_filters_analyte_and_takes_max(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-1", ResultNumeric="9.0"),   # max wins
        _row(LocationID="MW-2", ResultNumeric="2.0"),
        _row(LocationID="MW-2", AnalyteCanonicalName="Toluene",
             ResultNumeric="99.0"),                     # wrong analyte
    ])
    qa = QACollector()
    pts = collect_concentration_points(
        results, coords, analyte="Benzene", qa=qa)
    assert sorted(pts) == [("MW-1", 0.0, 0.0, 9.0), ("MW-2", 100.0, 0.0, 2.0)]


def test_collect_applies_nondetect_rule(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-2", IsNonDetect="1", ResultNumeric=""),
    ])
    qa = QACollector()
    excl = collect_concentration_points(
        results, coords, analyte="Benzene", nondetect_rule="exclude", qa=qa)
    assert [p[0] for p in excl] == ["MW-1"]
    half = collect_concentration_points(
        results, coords, analyte="Benzene", nondetect_rule="half_rl", qa=qa)
    assert ("MW-2", 100.0, 0.0, 0.5) in half


def test_collect_warns_missing_coords(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-9", ResultNumeric="7.0"),
    ])
    qa = QACollector()
    pts = collect_concentration_points(
        results, coords, analyte="Benzene", qa=qa)
    assert pts == []
    assert any(r.category == "missing_coords" for r in qa.records)


# ---------------------------------------------------------------------------
# Naming + registry rows (spec D3)
# ---------------------------------------------------------------------------

def test_slug_gdb_legal():
    assert slug("H-281 site") == "H_281_site"
    assert slug("1,1-DCE").startswith("_")  # no leading digit
    assert slug("") == "X"


def test_raster_names_ebk_adds_se():
    idw = raster_names("H281", "2026-06-15", "Benzene", "IDW")
    assert idw == {"PREDICTION": "Draft_Conc_H281_20260615_Benzene_IDW"}
    ebk = raster_names("H281", "2026-06-15", "Benzene", "EBK")
    assert ebk["STD_ERROR"] == "Draft_Conc_H281_20260615_Benzene_EBK_SE"
    assert all(n.startswith("Draft_") for n in ebk.values())


def test_registry_rows_shape():
    rows = build_surface_registry_rows(
        "H281", "2026-06-15", "CONC", "Benzene", "EBK", "half_rl",
        raster_names("H281", "2026-06-15", "Benzene", "EBK"), NOW)
    assert len(rows) == 2
    assert {r["RasterType"] for r in rows} == {"PREDICTION", "STD_ERROR"}
    for r in rows:
        assert r["ReviewStatus"] == "DRAFT"
        assert r["NondetectRule"] == "half_rl"
        assert r["SurfaceKind"] == "CONC"
        assert set(r) == {"SiteID", "EventDate", "SurfaceKind",
                          "AnalyteFilter", "Method", "RasterType",
                          "NondetectRule", "RasterPath", "ReviewStatus",
                          "CreatedAt", "Notes"}


def test_registry_rows_gwe_kind():
    rows = build_surface_registry_rows(
        "H281", "2026-06-15", "GWE", "", "EBK", "",
        {"STD_ERROR": "Draft_GWE_H281_20260615_EBK_SE"}, NOW)
    assert len(rows) == 1 and rows[0]["AnalyteFilter"] == ""


# ---------------------------------------------------------------------------
# CLI smoke tests (no arcpy in this suite)
# ---------------------------------------------------------------------------
from click.testing import CliRunner  # noqa: E402
from autogis.adapters.cli import autogis  # noqa: E402


def test_build_conc_surface_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "build-conc-surface" in result.output


def test_build_conc_surface_dry_run_headless(tmp_path):
    import csv
    results = tmp_path / "r.csv"
    with results.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "LocationID", "AnalyteCanonicalName", "ResultNumeric",
            "IsNonDetect", "ReportingLimit", "DetectionLimit"])
        w.writeheader()
        w.writerow({"LocationID": "MW-1", "AnalyteCanonicalName": "Benzene",
                    "ResultNumeric": "5.0", "IsNonDetect": "0",
                    "ReportingLimit": "1", "DetectionLimit": "0.5"})
    coords = tmp_path / "c.csv"
    coords.write_text("location_id,x,y\nMW-1,0,0\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", "H281", "--event-date", "2026-06-15", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "1 interpolation point(s)" in result.output
    assert "MW-1" in result.output


def test_build_conc_surface_guard_without_arcpy(tmp_path):
    coords = tmp_path / "c.csv"
    coords.write_text("location_id,x,y\n", encoding="utf-8")
    results = tmp_path / "r.csv"
    results.write_text("LocationID\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", "H281", "--event-date", "2026-06-15",
        "--gdb", "fake.gdb"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_build_conc_surface_requires_gdb_or_dry_run(tmp_path):
    coords = tmp_path / "c.csv"
    coords.write_text("location_id,x,y\n", encoding="utf-8")
    results = tmp_path / "r.csv"
    results.write_text("LocationID\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", "H281", "--event-date", "2026-06-15"])
    assert result.exit_code != 0
    assert "--gdb" in result.output
