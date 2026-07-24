"""Tests for Phase 8 outbound WQX submission mapping — arcpy-free.

The synthetic fixture verifies the mapping/validation rules. The gate's
"passes the agency validator" leg needs the real EPA WQX validator and is
recorded as a Proposed owner-sign-off item in ADR-0109 — not asserted here.
"""
import json
import csv
from pathlib import Path

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.records_csv import read_records_csv, write_records_csv
from autogis.core.envmon.wqx_outbound import (
    COL_ACTIVITY_DATE, COL_CHARACTERISTIC, COL_CONDITION, COL_DATUM, COL_LAT,
    COL_LIMIT_TYPE, COL_LIMIT_VALUE, COL_MEDIA, COL_METHOD, COL_RESULT,
    MonitoringLocation, WqxExportConfig, WqxSourceRow, map_to_wqx,
)


def _src(analyte, **k):
    base = dict(site_id="S", location_id="MW-1", event_date="2026-01-15",
                matrix="GW", sample_id="MW-1-A", method="8260")
    base.update(k)
    return WqxSourceRow(analyte=analyte, **base)


_LOC = [MonitoringLocation("MW-1", latitude=40.0, longitude=-105.0,
                           horizontal_datum="NAD83")]


# ── mapping ─────────────────────────────────────────────────────────────────

def test_detection_maps_all_fields():
    res = map_to_wqx([_src("Benzene", result=5.0, units="ug/L")], _LOC)
    row = res.submission[0]
    assert row[COL_CHARACTERISTIC] == "Benzene"
    assert row[COL_RESULT] == 5.0 and row[COL_MEDIA] == "Groundwater"
    assert row[COL_LAT] == 40.0 and row[COL_DATUM] == "NAD83"
    assert row[COL_CONDITION] == ""


def test_nondetect_uses_condition_and_limit():
    res = map_to_wqx([_src("Toluene", result=None, units="ug/L",
                           reporting_limit=1.0, is_nondetect=1)], _LOC)
    row = res.submission[0]
    assert row[COL_RESULT] == "" and row[COL_CONDITION] == "Not Detected"
    assert row[COL_LIMIT_VALUE] == 1.0 and row[COL_LIMIT_TYPE] == "Reporting Limit"


def test_default_datum_when_location_blank():
    loc = [MonitoringLocation("MW-1", latitude=40.0, longitude=-105.0)]
    res = map_to_wqx([_src("Benzene", result=5.0, units="ug/L")], loc,
                     WqxExportConfig.from_dict({"default_datum": "WGS84"}))
    assert res.submission[0][COL_DATUM] == "WGS84"


def test_unmapped_matrix_passes_through_with_warning():
    from autogis.core.common.qa import QACollector
    qa = QACollector()
    res = map_to_wqx([_src("Benzene", result=5.0, units="ug/L", matrix="Sludge")],
                     _LOC, qa=qa)
    assert res.submission[0][COL_MEDIA] == "Sludge"
    assert any(getattr(r, "category", "") == "wqx_out_unmapped_matrix"
               for r in qa.records)


# ── validation / rejections ─────────────────────────────────────────────────

def test_reject_missing_coordinates():
    rows = [_src("Lead", result=2.0, units="ug/L", location_id="MW-9")]
    res = map_to_wqx(rows, _LOC)
    assert not res.submission and len(res.rejections) == 1
    assert "coordinates" in res.rejections[0]["reason"]


def test_reject_detection_without_value_or_units():
    rows = [
        _src("A", result=None, units="ug/L", sample_id="s1"),   # no value
        _src("B", result=3.0, units="", sample_id="s2"),        # no units
    ]
    res = map_to_wqx(rows, _LOC)
    reasons = " ".join(r["reason"] for r in res.rejections)
    assert len(res.rejections) == 2
    assert "ResultMeasureValue" in reasons and "units" in reasons


def test_reject_nondetect_without_limit_or_units():
    rows = [
        _src("A", result=None, units="ug/L", reporting_limit=None,
             is_nondetect=1, sample_id="s1"),
        _src("B", result=None, units="", reporting_limit=1.0,
             is_nondetect=1, sample_id="s2"),
    ]
    res = map_to_wqx(rows, _LOC)
    reasons = " ".join(r["reason"] for r in res.rejections)
    assert len(res.rejections) == 2
    assert "limit" in reasons and "units" in reasons


def test_reject_invalid_calendar_dates():
    rows = [
        _src("A", result=1.0, units="ug/L", event_date="2026-99-99",
             sample_id="s1"),
        _src("B", result=1.0, units="ug/L", event_date="2026-01-15junk",
             sample_id="s2"),
    ]
    res = map_to_wqx(rows, _LOC)
    assert len(res.rejections) == 2
    assert all("ActivityStartDate" in r["reason"] for r in res.rejections)


def test_reject_missing_identifiers_and_method():
    rows = [
        _src("A", result=1.0, units="ug/L", location_id="", sample_id="s1"),
        _src("B", result=1.0, units="ug/L", sample_id=""),
        _src("C", result=1.0, units="ug/L", method="", sample_id="s3"),
        _src("D", result=1.0, units="ug/L", event_date="", sample_id="s4"),
    ]
    res = map_to_wqx(rows, _LOC)
    assert len(res.rejections) == 4 and not res.submission


def test_out_of_range_coordinates_rejected():
    loc = [MonitoringLocation("MW-1", latitude=999.0, longitude=-105.0)]
    res = map_to_wqx([_src("Benzene", result=5.0, units="ug/L")], loc)
    assert "latitude" in res.rejections[0]["reason"]


def test_qualifier_validation_opt_in():
    rows = [_src("Benzene", result=5.0, units="ug/L", qualifier="ZZ")]
    # permissive by default → accepted
    assert len(map_to_wqx(rows, _LOC).submission) == 1
    # enforced set → rejected
    cfg = WqxExportConfig.from_dict({"allowed_qualifiers": ["U", "J"]})
    res = map_to_wqx(rows, _LOC, cfg)
    assert len(res.rejections) == 1 and "Qualifier" in res.rejections[0]["reason"]


def test_deterministic_submission_order():
    rows = [_src("Xylene", result=1.0, units="ug/L", sample_id="s2"),
            _src("Benzene", result=1.0, units="ug/L", sample_id="s1")]
    res = map_to_wqx(rows, _LOC)
    keys = [(r["MonitoringLocationIdentifier"], r["ActivityIdentifier"],
             r[COL_CHARACTERISTIC]) for r in res.submission]
    assert keys == sorted(keys)


# ── CLI round-trip ──────────────────────────────────────────────────────────

def test_command_in_help():
    res = CliRunner().invoke(autogis, ["envmon", "export-wqx", "--help"])
    assert res.exit_code == 0
    assert "--results" in res.output and "--locations" in res.output


def _write_canonical_results(path, rows):
    fieldnames = [
        "SiteID", "LocationID", "SampleDate", "Matrix", "SampleID",
        "AnalyteName", "AnalyteCanonicalName", "ResultNumeric", "Units",
        "Qualifier", "ReportingLimit", "MethodGroup", "MethodID",
        "MethodName", "IsNonDetect",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_cli_produces_three_files(tmp_path):
    results = tmp_path / "results.csv"
    _write_canonical_results(results, [
        {
            "SiteID": "S", "LocationID": "MW-1", "SampleDate": "2026-01-15",
            "Matrix": "GW", "SampleID": "MW-1-A",
            "AnalyteCanonicalName": "Benzene", "ResultNumeric": 5.0,
            "Units": "ug/L", "MethodID": "8260", "IsNonDetect": 0,
        },
        {
            "SiteID": "S", "LocationID": "MW-9", "SampleDate": "2026-01-15",
            "Matrix": "GW", "SampleID": "MW-9-A",
            "AnalyteCanonicalName": "Lead", "ResultNumeric": 2.0,
            "Units": "ug/L", "MethodID": "6020", "IsNonDetect": 0,
        },
    ])
    locs = tmp_path / "locations.csv"
    write_records_csv(_LOC, locs, record_class=MonitoringLocation)
    out = tmp_path / "wqx"

    res = CliRunner().invoke(autogis, [
        "envmon", "export-wqx", "--results", str(results),
        "--locations", str(locs), "--out-dir", str(out)])
    assert res.exit_code == 0, res.output

    sub = out / "wqx_submission.csv"
    rej = out / "wqx_rejections.csv"
    prov = out / "wqx_provenance.json"
    assert sub.exists() and rej.exists() and prov.exists()

    # one submitted (Benzene), one rejected (Lead, no coords)
    sub_rows = list(csv.DictReader(sub.open(encoding="utf-8")))
    rej_rows = list(csv.DictReader(rej.open(encoding="utf-8")))
    assert len(sub_rows) == 1 and sub_rows[0][COL_CHARACTERISTIC] == "Benzene"
    assert sub_rows[0][COL_ACTIVITY_DATE] == "2026-01-15"
    assert sub_rows[0][COL_METHOD] == "8260"
    assert sub_rows[0][COL_RESULT] == "5.0"
    assert len(rej_rows) == 1 and "coordinates" in rej_rows[0]["reason"]

    provenance = json.loads(prov.read_text(encoding="utf-8"))
    assert provenance["counts"] == {"input": 2, "submitted": 1, "rejected": 1}
    assert provenance["locations_source"] == str(locs)
    assert "DRAFT" in provenance["status"]


def test_cli_multi_event(tmp_path):
    e1 = tmp_path / "e1.csv"
    e2 = tmp_path / "e2.csv"
    _write_canonical_results(e1, [{
        "SiteID": "S", "LocationID": "MW-1", "SampleDate": "2026-01-15",
        "Matrix": "GW", "SampleID": "a", "AnalyteCanonicalName": "Benzene",
        "ResultNumeric": 1.0, "Units": "ug/L", "MethodID": "8260",
        "IsNonDetect": 0,
    }])
    _write_canonical_results(e2, [{
        "SiteID": "S", "LocationID": "MW-1", "SampleDate": "2026-04-15",
        "Matrix": "GW", "SampleID": "b", "AnalyteCanonicalName": "Toluene",
        "ResultNumeric": 2.0, "Units": "ug/L", "MethodID": "8260",
        "IsNonDetect": 0,
    }])
    locs = tmp_path / "loc.csv"
    write_records_csv(_LOC, locs, record_class=MonitoringLocation)
    out = tmp_path / "wqx"
    res = CliRunner().invoke(autogis, [
        "envmon", "export-wqx", "--results", str(e1), "--results", str(e2),
        "--locations", str(locs), "--out-dir", str(out)])
    assert res.exit_code == 0, res.output
    sub = list(csv.DictReader((out / "wqx_submission.csv").open(encoding="utf-8")))
    assert len(sub) == 2
