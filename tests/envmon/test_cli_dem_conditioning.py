"""CLI tests for envmon condition-dem (guard + redirect, Tools 2-8 pattern)."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_condition_dem_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "condition-dem" in result.output


def test_condition_dem_without_arcpy_is_clean_error(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "condition-dem",
        "--gdb", str(tmp_path / "fake.gdb"), "--flight-id", "F01",
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
