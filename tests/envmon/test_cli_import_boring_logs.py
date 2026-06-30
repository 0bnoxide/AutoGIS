"""CLI tests for validate-boring-logs and import-boring-logs."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis

_LOC = ("BoringID,SiteID,LocationType,Northing,Easting,GroundElevation_ft,Status\n"
        "B-01,H281,Monitoring Well,4527893.12,293847.55,512.34,Complete\n")
_LITH = ("BoringID,TopDepth_ft,BottomDepth_ft,USCS,PrimaryMaterial,Color,Moisture,Description\n"
         "B-01,0.0,5.0,SM,Sandy loam,Brown,Moist,Fill\n"
         "B-01,5.0,12.0,CL,Clay,Gray,Wet,Native\n")
_LITH_OVERLAP = ("BoringID,TopDepth_ft,BottomDepth_ft,USCS,PrimaryMaterial,Color,Moisture,Description\n"
                 "B-01,0.0,6.0,SM,Sandy loam,Brown,Moist,Fill\n"
                 "B-01,5.0,12.0,CL,Clay,Gray,Wet,Native\n")


def _pkg(tmp_path, lith=_LITH):
    (tmp_path / "boring_locations.csv").write_text(_LOC, encoding="utf-8")
    (tmp_path / "lithology.csv").write_text(lith, encoding="utf-8")
    return tmp_path


def test_validate_boring_logs_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-boring-logs" in result.output


def test_import_boring_logs_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-boring-logs" in result.output


def test_validate_boring_logs_clean_package_passes(tmp_path):
    d = _pkg(tmp_path)
    result = CliRunner().invoke(autogis, ["envmon", "validate-boring-logs", str(d)])
    assert result.exit_code == 0, result.output
    assert "Status: PASS" in result.output


def test_validate_boring_logs_overlap_fails(tmp_path):
    d = _pkg(tmp_path, lith=_LITH_OVERLAP)
    result = CliRunner().invoke(autogis, ["envmon", "validate-boring-logs", str(d)])
    assert result.exit_code != 0
    assert "overlapping_intervals" in result.output


def test_import_boring_logs_without_arcpy_is_clean(tmp_path):
    d = _pkg(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "import-boring-logs", str(d), "--gdb", str(tmp_path / "fake.gdb"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
