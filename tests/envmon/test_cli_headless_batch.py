"""
test_cli_headless_batch.py

In-process CLI tests for the 10 new headless envmon commands added on
feat/headless-envmon-batch-2026-06-28.  Each test:

  1. Builds minimal valid input file(s) under tmp_path.
  2. Invokes the command via CliRunner (catch_exceptions=False so real bugs
     surface as pytest tracebacks, not hidden in result.exception).
  3. Asserts exit_code == 0 and that the expected --out / --output file was
     created.

Constraints:
  - No arcpy, no arcgis.
  - Only touches tests/envmon/.
  - Does NOT modify cli.py or core modules.
  - Fixtures are designed to be warnings-clean (most commands hardcode
    fail_on="warning").  Clean fixtures do NOT mask transcription bugs —
    a wrong kwarg name throws before any QA check.
"""
import csv
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from autogis.adapters.cli import autogis

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _run(*args):
    """Invoke autogis CLI; re-raises real bugs (catch_exceptions=False).

    SystemExit is still captured into result.exit_code by CliRunner even
    with catch_exceptions=False — so _render_qa exit-1 paths work correctly.
    """
    return CliRunner().invoke(autogis, list(args), catch_exceptions=False)


# ---------------------------------------------------------------------------
# Shared minimal fixture data
# ---------------------------------------------------------------------------

# Minimal analytical result rows (subset of AnalyticalResultRecord columns).
# These are the CSV-dict keys the command-body DictReaders expect.
_RESULT_ROWS = [
    {
        "LocationID": "MW-01", "AnalyteName": "Benzene",
        "ResultValue": "12.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
        "SampleDate": "2026-01-15", "SampleID": "S1",
    },
    {
        "LocationID": "MW-01", "AnalyteName": "Benzene",
        "ResultValue": "5.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
        "SampleDate": "2025-06-15", "SampleID": "S0",
    },
    {
        "LocationID": "MW-02", "AnalyteName": "Toluene",
        "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
        "SampleDate": "2026-01-15", "SampleID": "S2",
    },
]

# Wells with valid lat/lon (avoids geopackage WARNING for missing coords).
_WELLS_ROWS = [
    {"LocationID": "MW-01", "Latitude": "34.1234", "Longitude": "-118.4567",
     "WellType": "monitoring well"},
    {"LocationID": "MW-02", "Latitude": "34.2345", "Longitude": "-118.5678",
     "WellType": "monitoring well"},
]

# QC-only rows (no "primary" sample type) for generate-qc-summary.
# Using SampleType field + suffix-based inference as fallback.
_QC_ROWS = [
    {
        "SampleID": "S1-MB", "SampleType": "method_blank", "LocationID": "",
        "AnalyteName": "Benzene", "ResultValue": "ND", "ResultQualifier": "ND",
        "ReportedUnits": "ug/L", "SampleDate": "2026-06-15",
    },
    {
        "SampleID": "S1-LD-A", "SampleType": "lab_duplicate", "LocationID": "MW-01",
        "AnalyteName": "Benzene", "ResultValue": "5.0", "ResultQualifier": "",
        "ReportedUnits": "ug/L", "SampleDate": "2026-06-15",
    },
]

# Plan rows with hold times; matching results that don't exceed hold time.
_PLAN_ROWS = [
    {
        "SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
        "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
        "CollectionDate": "2026-06-15",
    },
    {
        "SampleID": "H281-MW02-20260615-GW", "LocationID": "MW-02",
        "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
        "CollectionDate": "2026-06-15",
    },
]
_RESULTS_FC = [
    {"SampleID": "H281-MW01-20260615-GW", "AnalysisDate": "2026-06-20"},  # 5 days
    {"SampleID": "H281-MW02-20260615-GW", "AnalysisDate": "2026-06-22"},  # 7 days
]

# GW wells: non-collinear (flow-east scenario, azimuth 90°).
_GW_WELLS_ROWS = [
    {"well_id": "MW-01", "easting": "0.0",   "northing": "0.0",   "gwe_ft": "100.0"},
    {"well_id": "MW-02", "easting": "100.0", "northing": "0.0",   "gwe_ft": "99.0"},
    {"well_id": "MW-03", "easting": "0.0",   "northing": "100.0", "gwe_ft": "100.0"},
]


# ===========================================================================
# 1. merge-event-results
# ===========================================================================

def test_merge_event_results(tmp_path):
    """Two valid CSVs merged; output file created; exit 0."""
    f1 = tmp_path / "Env_Results_20260115.csv"
    f2 = tmp_path / "Env_Results_20260615.csv"
    _write_csv(f1, [_RESULT_ROWS[0]])
    _write_csv(f2, [_RESULT_ROWS[1]])
    out = tmp_path / "merged.csv"

    result = _run(
        "envmon", "merge-event-results",
        "--results", str(f1),
        "--results", str(f2),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"merge-event-results exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected merged output CSV was not created"


# ===========================================================================
# 2. build-max-result-dataset
# ===========================================================================

def test_build_max_result_dataset(tmp_path):
    """Max-detected dataset built from result rows; output CSV created; exit 0."""
    results_csv = tmp_path / "results.csv"
    _write_csv(results_csv, _RESULT_ROWS)
    out = tmp_path / "max_results.csv"

    result = _run(
        "envmon", "build-max-result-dataset",
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"build-max-result-dataset exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected max-result output CSV was not created"


# ===========================================================================
# 3. generate-qc-summary
# ===========================================================================

def test_generate_qc_summary(tmp_path):
    """QC XLSX workbook generated from QC rows; output file created; exit 0."""
    results_csv = tmp_path / "qc_results.csv"
    _write_csv(results_csv, _QC_ROWS)
    out = tmp_path / "qc_summary.xlsx"

    result = _run(
        "envmon", "generate-qc-summary",
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"generate-qc-summary exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected QC summary XLSX was not created"


# ===========================================================================
# 4. build-compliance-table
# ===========================================================================

def test_build_compliance_table(tmp_path):
    """Compliance XLSX workbook built from result rows; output file created; exit 0."""
    results_csv = tmp_path / "results.csv"
    _write_csv(results_csv, _RESULT_ROWS)
    out = tmp_path / "compliance.xlsx"

    result = _run(
        "envmon", "build-compliance-table",
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"build-compliance-table exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected compliance XLSX was not created"


# ===========================================================================
# 5. generate-reg-tables
# ===========================================================================

def test_generate_reg_tables(tmp_path):
    """Regulatory pivot XLSX workbook built from result rows; output file created; exit 0."""
    results_csv = tmp_path / "results.csv"
    _write_csv(results_csv, _RESULT_ROWS)
    out = tmp_path / "reg_tables.xlsx"

    result = _run(
        "envmon", "generate-reg-tables",
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"generate-reg-tables exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected regulatory tables XLSX was not created"


# ===========================================================================
# 6. validate-field-completeness
# ===========================================================================

def test_validate_field_completeness(tmp_path):
    """All samples matched, no hold-time violations; completeness CSV created; exit 0."""
    plan_csv = tmp_path / "plan.csv"
    results_csv = tmp_path / "results.csv"
    _write_csv(plan_csv, _PLAN_ROWS)
    _write_csv(results_csv, _RESULTS_FC)
    out = tmp_path / "completeness.csv"

    result = _run(
        "envmon", "validate-field-completeness",
        "--plan", str(plan_csv),
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"validate-field-completeness exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected completeness report CSV was not created"


# ===========================================================================
# 7. estimate-gw-flow-direction
# ===========================================================================

def test_estimate_gw_flow_direction(tmp_path):
    """Flow-east 3-point scenario; azimuth 90 in stdout; output CSV created; exit 0."""
    wells_csv = tmp_path / "wells.csv"
    _write_csv(wells_csv, _GW_WELLS_ROWS)
    out_csv = tmp_path / "gw_flow.csv"

    result = _run(
        "envmon", "estimate-gw-flow-direction",
        "--wells-csv", str(wells_csv),
        "--site-id", "TEST",
        "--event-date", "2026-06-28",
        "--output", str(out_csv),
    )
    assert result.exit_code == 0, (
        f"estimate-gw-flow-direction exited {result.exit_code}:\n{result.output}"
    )
    assert "90.0" in result.output, (
        f"Expected azimuth '90.0' in stdout:\n{result.output}"
    )
    assert "DRAFT_REVIEW_REQUIRED" in result.output
    assert out_csv.exists(), "Expected GW flow output CSV was not created"


# ===========================================================================
# 8. export-geopackage
# ===========================================================================

def test_export_geopackage(tmp_path):
    """GeoPackage exported from well+result CSVs; .gpkg file created; exit 0.

    Uses wells with valid lat/lon to avoid the missing-coords WARNING that
    triggers exit 1 under the hardcoded fail_on='warning'.
    """
    wells_csv = tmp_path / "wells.csv"
    results_csv = tmp_path / "results.csv"
    _write_csv(wells_csv, _WELLS_ROWS)
    _write_csv(results_csv, _RESULT_ROWS)
    out = tmp_path / "site.gpkg"

    result = _run(
        "envmon", "export-geopackage",
        "--wells", str(wells_csv),
        "--results", str(results_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"export-geopackage exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected GeoPackage file was not created"


# ===========================================================================
# 9. generate-site-narrative
# ===========================================================================

def test_generate_site_narrative_minimal(tmp_path):
    """Narrative with no optional inputs; output .md file created with site_id; exit 0."""
    out = tmp_path / "narrative.md"

    result = _run(
        "envmon", "generate-site-narrative",
        "--site", "H281",
        "--event-label", "Q1-2026",
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"generate-site-narrative exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected narrative output file was not created"
    content = out.read_text(encoding="utf-8")
    assert "H281" in content, "Site ID not found in narrative output"


def test_generate_site_narrative_with_max_results(tmp_path):
    """Narrative with a max-results CSV (path-based read path); exit 0."""
    # MaxResultRecord fields are lowercase (matches csv DictReader keys).
    max_csv = tmp_path / "max_results.csv"
    _write_csv(max_csv, [
        {
            "location_id": "MW-01", "analyte_name": "Benzene",
            "max_result_value": "12.0", "max_result_qualifier": "",
            "reported_units": "ug/L", "max_sample_date": "2026-06-15",
            "max_sample_id": "S1", "detection_count": "2",
            "total_sample_count": "3", "screening_level": "",
            "exceedance_ratio": "", "has_exceedance": "False",
            "first_detection_date": "2026-01-15", "last_detection_date": "2026-06-15",
        },
    ])
    out = tmp_path / "narrative.md"

    result = _run(
        "envmon", "generate-site-narrative",
        "--site", "H281",
        "--event-label", "Q1-2026",
        "--max-results", str(max_csv),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"generate-site-narrative (with max-results) exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected narrative output file was not created"
    content = out.read_text(encoding="utf-8")
    assert "MW-01" in content


# ===========================================================================
# 10. build-report-package
# ===========================================================================

def test_build_report_package(tmp_path):
    """Deliverable folder assembled from a spec referencing an existing file; exit 0."""
    src_pdf = tmp_path / "Fig-1A.pdf"
    src_pdf.write_bytes(b"PDF content")

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(
        yaml.dump({"files": [{"path": str(src_pdf), "role": "figure_pdf"}]}),
        encoding="utf-8",
    )
    out_dir = tmp_path / "deliverable"

    result = _run(
        "envmon", "build-report-package",
        "--spec", str(spec_path),
        "--out-dir", str(out_dir),
        "--site", "H281",
        "--event-label", "Q1-2026",
    )
    assert result.exit_code == 0, (
        f"build-report-package exited {result.exit_code}:\n{result.output}"
    )
    assert out_dir.exists(), "Expected deliverable output directory was not created"
    assert (out_dir / "figures" / "Fig-1A.pdf").exists(), (
        "Copied figure PDF not found in deliverable/figures/"
    )


# ===========================================================================
# 11. build-report-appendix (Tool 9.2)
# ===========================================================================

def test_build_report_appendix(tmp_path):
    """Long-format results + group map -> multi-sheet xlsx; exit 0."""
    results = tmp_path / "results.csv"
    _write_csv(results, [
        {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "12.0",
         "ResultQualifier": "", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
        {"LocationID": "MW-02", "AnalyteName": "Lead", "ResultValue": "ND",
         "ResultQualifier": "ND", "ReportedUnits": "ug/L", "SampleDate": "2026-01-15"},
    ])
    sl = tmp_path / "sl.yaml"
    sl.write_text(yaml.dump({"Benzene": 5.0, "Lead": 15.0}), encoding="utf-8")
    gm = tmp_path / "groups.yaml"
    gm.write_text(yaml.dump({"Benzene": "VOC", "Lead": "Metals"}), encoding="utf-8")
    out = tmp_path / "appendix.xlsx"

    result = _run(
        "envmon", "build-report-appendix",
        "--results", str(results),
        "--screening-levels", str(sl),
        "--group-map", str(gm),
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"build-report-appendix exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected appendix workbook was not created"


# ===========================================================================
# 12. list-tools (Tool 10.1)
# ===========================================================================

def test_list_tools_default(tmp_path):
    """list-tools renders a table; exit 0."""
    result = _run("envmon", "list-tools")
    assert result.exit_code == 0, (
        f"list-tools exited {result.exit_code}:\n{result.output}"
    )
    assert "command" in result.output and "runtime" in result.output


def test_list_tools_search():
    result = _run("envmon", "list-tools", "--search", "edd")
    assert result.exit_code == 0, result.output
    assert "import-edd" in result.output  # the EDD importer matches "edd"


def test_list_tools_filter_local_only():
    result = _run("envmon", "list-tools", "--runtime", "LOCAL")
    assert result.exit_code == 0, result.output
    assert "CLOUD" not in result.output  # only LOCAL rows rendered


# ===========================================================================
# 13. build-exceedance-event (Tool 4.4)
# ===========================================================================

def test_build_exceedance_event(tmp_path):
    """Results + screening levels -> exceedance dataset CSV; exit 0."""
    results = tmp_path / "results.csv"
    _write_csv(results, [
        {"LocationID": "MW-01", "AnalyteName": "Benzene", "ResultValue": "12.0",
         "ResultQualifier": "", "ReportedUnits": "ug/L",
         "SampleDate": "2026-01-15", "SampleID": "S1"},
    ])
    sl = tmp_path / "sl.yaml"
    sl.write_text(yaml.dump({"Benzene": 5.0}), encoding="utf-8")
    out = tmp_path / "exc.csv"

    result = _run(
        "envmon", "build-exceedance-event",
        "--results", str(results),
        "--screening-levels", str(sl),
        "--rule", "max_exceedance_per_location",
        "--out", str(out),
    )
    assert result.exit_code == 0, (
        f"build-exceedance-event exited {result.exit_code}:\n{result.output}"
    )
    assert out.exists(), "Expected exceedance-event CSV was not created"
    assert "Exceedances: 1" in result.output
# ===========================================================================
# 14. build-dashboard-data-mart (Tool 6.7) — LOCAL; guard must fire cleanly
# ===========================================================================

def test_build_dashboard_data_mart_guards_without_arcpy(tmp_path):
    """LOCAL tool: headless invocation must error cleanly via the runtime guard,
    not raise an internal KeyError/traceback."""
    result = _run(
        "envmon", "build-dashboard-data-mart", str(tmp_path / "x.gdb"),
        "--site", "H281", "--event", "2026Q2",
    )
    # require_runtime raises RuntimeUnavailable -> ClickException -> exit 1.
    assert result.exit_code != 0
    assert "not registered" not in result.output  # registry KeyError would say this
