"""CLI tests for validate-drone-products and import-drone-products."""
import csv

from click.testing import CliRunner

from autogis.adapters.cli import autogis

_MANIFEST_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
orthomosaic,/data/ortho.tif,EPSG:32612,NAVD88,0.05
DSM,/data/dsm.tif,EPSG:32612,NAVD88,0.05
DEM,/data/dem.tif,EPSG:32612,NAVD88,0.10
point_cloud,/data/cloud.las,EPSG:32612,NAVD88,
"""

_MANIFEST_BAD_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
badtype,,,,
"""


def test_validate_drone_products_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-drone-products" in result.output


def test_import_drone_products_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-drone-products" in result.output


def test_validate_drone_products_valid_manifest_exits_zero(tmp_path):
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "validate-drone-products",
        "--manifest", str(p), "--flight-id", "FLT-001",
    ])
    assert result.exit_code == 0, result.output
    assert "Status: PASS" in result.output


def test_validate_drone_products_bad_manifest_exits_nonzero(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text(_MANIFEST_BAD_CSV, encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "validate-drone-products",
        "--manifest", str(p), "--flight-id", "FLT-002",
    ])
    assert result.exit_code != 0, result.output
    assert "invalid_product_type" in result.output


def test_validate_drone_products_report_csv(tmp_path):
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    report = tmp_path / "qa.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "validate-drone-products",
        "--manifest", str(p), "--flight-id", "FLT-001", "--report", str(report),
    ])
    assert result.exit_code == 0, result.output
    assert report.exists()
    rows = list(csv.DictReader(report.open(encoding="utf-8")))
    assert any(r["category"] == "manifest_parsed" for r in rows)


def test_import_drone_products_missing_arcpy_exits_clean(tmp_path):
    """Without arcpy, import-drone-products should print a clean ClickException."""
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    result = CliRunner().invoke(autogis, [
        "envmon", "import-drone-products",
        "--manifest", str(p), "--flight-id", "FLT-001",
        "--site-id", "SITE-001", "--gdb", str(tmp_path / "fake.gdb"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
