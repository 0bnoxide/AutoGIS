"""CLI guard tests for optimize-callouts and manage-callout-overrides."""
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


@pytest.fixture
def fake_files(tmp_path):
    site = tmp_path / "site.yaml"
    site.write_text("site_id: X\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text("figure_spec_id: F1\n", encoding="utf-8")
    gdb = tmp_path / "test.gdb"
    gdb.mkdir()
    return {"site": site, "spec": spec, "gdb": gdb}


def test_optimize_callouts_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "optimize-callouts" in result.output


def test_optimize_callouts_guard(fake_files):
    """Without arcpy, optimize-callouts errors cleanly — no traceback."""
    result = CliRunner().invoke(
        autogis,
        ["envmon", "optimize-callouts",
         str(fake_files["site"]), str(fake_files["spec"])],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_manage_callout_overrides_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "manage-callout-overrides" in result.output


def test_manage_callout_overrides_list_guard(fake_files):
    result = CliRunner().invoke(
        autogis,
        ["envmon", "manage-callout-overrides", "list",
         str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1"],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_manage_callout_overrides_clear_guard(fake_files):
    result = CliRunner().invoke(
        autogis,
        ["envmon", "manage-callout-overrides", "clear",
         str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1"],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_manage_callout_overrides_lock_guard(fake_files):
    result = CliRunner().invoke(
        autogis,
        ["envmon", "manage-callout-overrides", "lock",
         str(fake_files["gdb"]),
         "--site", "SITE1", "--spec", "SPEC1",
         "--location", "MW-1",
         "--anchor-x", "100.0", "--anchor-y", "200.0"],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_manage_callout_overrides_unlock_guard(fake_files):
    result = CliRunner().invoke(
        autogis,
        ["envmon", "manage-callout-overrides", "unlock",
         str(fake_files["gdb"]),
         "--site", "SITE1", "--spec", "SPEC1", "--location", "MW-1"],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_manage_callout_overrides_subcommand_help():
    result = CliRunner().invoke(
        autogis, ["envmon", "manage-callout-overrides", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "lock" in result.output
    assert "unlock" in result.output
    assert "clear" in result.output
