from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_validate_db_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "validate-db" in result.output


def test_validate_db_shows_analytes_option():
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "--help"])
    assert "--analytes" in result.output


def test_validate_db_shows_report_option():
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "--help"])
    assert "--report" in result.output


def test_validate_db_guard_without_arcpy():
    """Without arcpy, validate-db must error cleanly (no unhandled exception)."""
    result = CliRunner().invoke(autogis, ["envmon", "validate-db", "fake.gdb"])
    assert result.exit_code in (0, 1)
    assert result.exception is None or isinstance(result.exception, SystemExit)
