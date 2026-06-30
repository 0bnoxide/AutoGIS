"""CLI tests for survey-to-well-elevation command."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis

_RTK = (
    "PointID,Northing,Easting,Elevation_ft,FeatureCode,Description,"
    "HRMS_ft,VRMS_ft,FixType,CollectedAt,Operator\n"
    "MW-01,4527893.12,293847.55,512.34,WELL,Mon Well,0.01,0.02,RTK_FIXED,2026-06-15,Alice\n"
    "MW-02,4527750.00,293900.00,509.12,WELL,Mon Well,0.15,0.20,AUTONOMOUS,2026-06-15,Alice\n"
    "INV-01,4527800.00,293870.00,510.00,INV,Inv Point,0.01,0.02,RTK_FIXED,2026-06-15,Alice\n"
)


def test_survey_to_well_elevation_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "survey-to-well-elevation" in result.output


def test_headless_wells_csv_plan(tmp_path):
    rtk = tmp_path / "rtk.csv"
    rtk.write_text(_RTK, encoding="utf-8")
    wells = tmp_path / "wells.csv"
    wells.write_text("LocationID\nMW-01\nMW-02\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "survey-to-well-elevation", str(rtk),
        "--site", "SITE-001", "--wells-csv", str(wells),
        "--batch-id", "TEST-BATCH-001", "--survey-date", "2026-06-28",
    ])
    assert result.exit_code == 0, result.output
    # MW-01 passes QA and matches a well → update planned (1 update)
    assert "Updates: 1" in result.output
    assert "MW-01" in result.output
    # MW-02 fails QA (AUTONOMOUS); INV-01 passes QA but is not a listed well
    assert "Failed QA: 1" in result.output
    assert "Skipped: 1" in result.output


def test_gdb_and_wells_csv_mutually_exclusive(tmp_path):
    rtk = tmp_path / "rtk.csv"
    rtk.write_text("PointID,Northing,Easting,Elevation_ft\nMW-01,0,0,100.0\n",
                   encoding="utf-8")
    wells = tmp_path / "wells.csv"
    wells.write_text("LocationID\nMW-01\n", encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "survey-to-well-elevation", str(rtk),
        "--site", "SITE-001", "--wells-csv", str(wells), "--gdb", "C:/fake/site.gdb",
    ])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_gdb_write_without_arcpy_is_clean(tmp_path):
    rtk = tmp_path / "rtk.csv"
    rtk.write_text(_RTK, encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "survey-to-well-elevation", str(rtk),
        "--site", "SITE-001", "--gdb", str(tmp_path / "fake.gdb"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
