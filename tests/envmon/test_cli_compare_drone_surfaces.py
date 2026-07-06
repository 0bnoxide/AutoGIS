"""CLI tests for envmon compare-drone-surfaces (guard + redirect, Tools 2-8 pattern)."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def test_compare_drone_surfaces_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "compare-drone-surfaces" in result.output


def test_compare_drone_surfaces_requires_one_baseline(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "compare-drone-surfaces",
        "--gdb", str(tmp_path / "fake.gdb"), "--primary-product-id", "P-1",
    ])
    assert result.exit_code != 0
    assert "exactly one baseline" in result.output


def test_compare_drone_surfaces_without_arcpy_is_clean_error(tmp_path):
    result = CliRunner().invoke(autogis, [
        "envmon", "compare-drone-surfaces",
        "--gdb", str(tmp_path / "fake.gdb"), "--primary-product-id", "P-1",
        "--baseline-product-id", "P-2",
    ])
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
