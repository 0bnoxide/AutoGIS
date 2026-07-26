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
    surface_tag,
)

NOW = dt.datetime(2026, 7, 16, 12, 0, 0)
SITE, EVENT = "H281", "2026-06-15"


def _row(**kw):
    base = {"SiteID": SITE, "SampleDate": EVENT, "Matrix": "GW",
            "LocationID": "MW-1", "AnalyteCanonicalName": "Benzene",
            "ResultNumeric": "5.0", "IsNonDetect": "0", "Units": "ug/L",
            "ReportingLimit": "1.0", "DetectionLimit": "0.5"}
    base.update(kw)
    return base


def _collect(results, coords, qa=None, **kw):
    kw.setdefault("site_id", SITE)
    kw.setdefault("event_date", EVENT)
    kw.setdefault("analyte", "Benzene")
    return collect_concentration_points(
        results, coords, qa=qa or QACollector(), **kw)


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
# Point collection: scoping, units, aggregation (#241 review)
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
    pts = _collect(results, coords)
    assert sorted(pts) == [("MW-1", 0.0, 0.0, 9.0), ("MW-2", 100.0, 0.0, 2.0)]


def test_collect_scopes_to_site_and_event(tmp_path):
    """#241 P1 regression: the same well across two events/sites must not
    leak a foreign value into the requested surface."""
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-1", SampleDate="2026-03-01",
             ResultNumeric="999.0"),                    # other event
        _row(LocationID="MW-2", SiteID="ZT42",
             ResultNumeric="888.0"),                    # other site
        _row(LocationID="MW-3", SampleDate=f"{EVENT} 00:00:00",
             ResultNumeric="3.0"),                      # datetime form OK
    ])
    pts = _collect(results, coords)
    assert sorted(pts) == [("MW-1", 0.0, 0.0, 5.0), ("MW-3", 0.0, 100.0, 3.0)]


def test_collect_matrix_filter(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-2", Matrix="SOIL", ResultNumeric="77.0",
             Units="mg/kg"),
    ])
    pts = _collect(results, coords, matrix="GW")
    assert [p[0] for p in pts] == ["MW-1"]


def test_collect_normalizes_mixed_units(tmp_path):
    """#241 P1 regression: 0.5 mg/L is 500 ug/L and must beat 100 ug/L."""
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="100", Units="ug/L"),
        _row(LocationID="MW-1", ResultNumeric="0.5", Units="mg/L"),
    ])
    pts = _collect(results, coords)
    assert pts == [("MW-1", 0.0, 0.0, 500.0)]


def test_collect_normalizes_nondetect_limits_too(tmp_path):
    """The RL a nondetect rule substitutes is in row units as well."""
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", IsNonDetect="1", ResultNumeric="",
             ReportingLimit="0.002", Units="mg/L"),
    ])
    pts = _collect(results, coords, nondetect_rule="use_rl")
    assert pts == [("MW-1", 0.0, 0.0, 2.0)]  # 0.002 mg/L = 2 ug/L


def test_collect_drops_unknown_and_cross_dimension_units(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-2", ResultNumeric="7.0", Units="furlongs"),
        _row(LocationID="MW-3", ResultNumeric="7.0", Units="mg/kg"),
    ])
    qa = QACollector()
    pts = _collect(results, coords, qa=qa)
    assert [p[0] for p in pts] == ["MW-1"]
    assert sum(1 for r in qa.records
               if r.category == "surface_unit_mismatch") == 2


def test_collect_rejects_unregistered_surface_unit(tmp_path):
    results, coords = _write_inputs(tmp_path, [_row()])
    with pytest.raises(ValueError, match="ADR-0022"):
        _collect(results, coords, surface_unit="ppb")


def test_collect_applies_nondetect_rule(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-1", ResultNumeric="5.0"),
        _row(LocationID="MW-2", IsNonDetect="1", ResultNumeric=""),
    ])
    excl = _collect(results, coords, nondetect_rule="exclude")
    assert [p[0] for p in excl] == ["MW-1"]
    half = _collect(results, coords, nondetect_rule="half_rl")
    assert ("MW-2", 100.0, 0.0, 0.5) in half


def test_collect_warns_missing_coords(tmp_path):
    results, coords = _write_inputs(tmp_path, [
        _row(LocationID="MW-9", ResultNumeric="7.0"),
    ])
    qa = QACollector()
    pts = _collect(results, coords, qa=qa)
    assert pts == []
    assert any(r.category == "missing_coords" for r in qa.records)


# ---------------------------------------------------------------------------
# Naming + registry rows (spec D3; #241 collision review)
# ---------------------------------------------------------------------------

def test_slug_gdb_legal():
    assert slug("H-281 site") == "H_281_site"
    assert slug("1,1-DCE").startswith("_")  # no leading digit
    assert slug("") == "X"


def test_surface_tag_distinguishes_punctuation_collisions():
    """'Ben zene' and 'Ben/zene' slug identically — the hash must differ."""
    a = surface_tag("H281", "Ben zene")
    b = surface_tag("H281", "Ben/zene")
    assert a != b
    assert a.rsplit("_", 1)[0] == b.rsplit("_", 1)[0]  # same readable prefix


def test_surface_tag_bounded_and_stable():
    long_site = "S" * 100
    long_analyte = "2,2'-oxybis(1-chloropropane)-extremely-long-variant" * 3
    t1 = surface_tag(long_site, long_analyte)
    t2 = surface_tag(long_site, long_analyte)
    assert t1 == t2                      # stable across calls
    assert len(t1) <= 49                 # bounded: 40 prefix + '_' + 8 hash


def test_raster_names_ebk_adds_se_and_stays_bounded():
    idw = raster_names(SITE, EVENT, "Benzene", "IDW")
    ebk = raster_names(SITE, EVENT, "Benzene", "EBK")
    assert set(idw) == {"PREDICTION"}
    assert set(ebk) == {"PREDICTION", "STD_ERROR"}
    assert ebk["STD_ERROR"] == ebk["PREDICTION"] + "_SE"
    for n in list(idw.values()) + list(ebk.values()):
        assert n.startswith("Draft_Conc_")
        assert len(n) <= 90
    # distinct identities -> distinct names even when slugs collide
    other = raster_names(SITE, EVENT, "Ben/zene", "IDW")
    assert other["PREDICTION"] != \
        raster_names(SITE, EVENT, "Ben zene", "IDW")["PREDICTION"]


def test_registry_rows_shape():
    rows = build_surface_registry_rows(
        SITE, EVENT, "CONC", "Benzene", "EBK", "half_rl",
        raster_names(SITE, EVENT, "Benzene", "EBK"), NOW, units="ug/L")
    assert len(rows) == 2
    assert {r["RasterType"] for r in rows} == {"PREDICTION", "STD_ERROR"}
    for r in rows:
        assert r["ReviewStatus"] == "DRAFT"
        assert r["NondetectRule"] == "half_rl"
        assert r["Units"] == "ug/L"
        assert r["SurfaceKind"] == "CONC"
        assert set(r) == {"SiteID", "EventDate", "SurfaceKind",
                          "AnalyteFilter", "Method", "RasterType",
                          "NondetectRule", "Units", "RasterPath",
                          "ReviewStatus", "CreatedAt", "Notes"}


def test_registry_rows_gwe_kind():
    rows = build_surface_registry_rows(
        SITE, EVENT, "GWE", "", "EBK", "",
        {"STD_ERROR": "Draft_GWE_x_EBK_SE"}, NOW, units="ft")
    assert len(rows) == 1
    assert rows[0]["AnalyteFilter"] == "" and rows[0]["Units"] == "ft"


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
    results, coords = _write_inputs(tmp_path, [
        _row(ResultNumeric="0.005", Units="mg/L"),
    ])
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", SITE, "--event-date", EVENT, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "1 interpolation point(s)" in result.output
    assert "ug/L" in result.output
    assert "= 5.0" in result.output  # 0.005 mg/L normalized to 5 ug/L


def test_build_conc_surface_rejects_unregistered_unit(tmp_path):
    results, coords = _write_inputs(tmp_path, [_row()])
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", SITE, "--event-date", EVENT, "--unit", "ppb", "--dry-run",
    ])
    assert result.exit_code == 2
    assert "Invalid value for --unit" in result.output
    assert "'ppb'" in result.output
    assert "Traceback" not in result.output


def test_bad_coords_not_blamed_on_unit(tmp_path):
    """collect_concentration_points raises ValueError for malformed coords
    too; a blanket except that said 'Invalid value for --unit' sent the
    operator to fix the wrong option (codex review on #372). The unit here is
    valid -- the coords are not."""
    results, _ = _write_inputs(tmp_path, [_row()])
    coords = tmp_path / "bad_coords.csv"
    coords.write_text("location_id,x,y\nMW-1,not_a_number,0\n",
                      encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", SITE, "--event-date", EVENT, "--dry-run"])
    assert result.exit_code != 0
    assert "--unit" not in result.output
    assert "Traceback" not in result.output


def test_build_conc_surface_guard_without_arcpy(tmp_path):
    results, coords = _write_inputs(tmp_path, [_row()])
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", SITE, "--event-date", EVENT, "--gdb", "fake.gdb"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_build_conc_surface_requires_gdb_or_dry_run(tmp_path):
    results, coords = _write_inputs(tmp_path, [_row()])
    result = CliRunner().invoke(autogis, [
        "envmon", "build-conc-surface", "--results", str(results),
        "--coords", str(coords), "--analyte", "Benzene",
        "--site", SITE, "--event-date", EVENT])
    assert result.exit_code != 0
    assert "--gdb" in result.output
