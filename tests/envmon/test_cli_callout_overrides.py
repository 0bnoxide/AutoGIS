"""CLI guard tests for optimize-callouts and manage-callout-overrides."""
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon.manage_callout_overrides import CalloutOverride

_CORE = "autogis.core.envmon.manage_callout_overrides"


def _pass_guard():
    """Neutralize the arcpy runtime guard for wiring tests."""
    return patch("autogis.adapters.cli.require_runtime")


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


# ------------------------------------------------------------- wiring tests
# Guard is mocked out; core CRUD is mocked at its source module (the CLI
# imports it lazily inside each command). These verify the CLI actually
# calls the core — issue #161's gap — not arcpy behavior.

def test_build_callouts_has_hull_flag():
    result = CliRunner().invoke(autogis, ["envmon", "build-callouts", "--help"])
    assert result.exit_code == 0
    assert "--use-hull-collision" in result.output


def test_optimize_callouts_redirects_to_build_callouts(fake_files):
    """5.2 redirect must name the real .pyt tool + flag, not a phantom."""
    with _pass_guard():
        result = CliRunner().invoke(
            autogis,
            ["envmon", "optimize-callouts",
             str(fake_files["site"]), str(fake_files["spec"])],
        )
    assert result.exit_code != 0
    assert "--use-hull-collision" in result.output
    assert "BuildCallouts" in result.output
    assert "OptimizeCalloutPlacement" not in result.output


def test_list_calls_core_and_prints_rows(fake_files):
    overrides = {
        "MW-1": {"origin": (101.5, 202.5), "preferred_quadrant": None,
                 "locked": True},
        "MW-2": {"origin": None, "preferred_quadrant": "NE", "locked": False},
    }
    with _pass_guard(), \
         patch(f"{_CORE}.load_overrides", return_value=overrides) as lo:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "list",
             str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1"],
        )
    assert result.exit_code == 0, result.output
    lo.assert_called_once_with(str(fake_files["gdb"]), "SITE1", "SPEC1", "")
    assert "MW-1" in result.output and "LOCKED" in result.output
    assert "MW-2" in result.output and "NE" in result.output
    assert "2 override(s)" in result.output


def test_list_scopes_by_map_type(fake_files):
    """list --map-type must forward the map type to the core scope."""
    with _pass_guard(), \
         patch(f"{_CORE}.load_overrides", return_value={}) as lo:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "list",
             str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1",
             "--map-type", "GW"],
        )
    assert result.exit_code == 0, result.output
    lo.assert_called_once_with(str(fake_files["gdb"]), "SITE1", "SPEC1", "GW")


def test_list_empty_says_so(fake_files):
    with _pass_guard(), patch(f"{_CORE}.load_overrides", return_value={}):
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "list",
             str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1"],
        )
    assert result.exit_code == 0, result.output
    assert "No overrides" in result.output


def test_clear_calls_core_and_reports_count(fake_files):
    with _pass_guard(), \
         patch(f"{_CORE}.clear_unlocked_overrides", return_value=3) as cu:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "clear",
             str(fake_files["gdb"]), "--site", "SITE1", "--spec", "SPEC1",
             "--map-type", "GW"],
        )
    assert result.exit_code == 0, result.output
    cu.assert_called_once_with(str(fake_files["gdb"]), "SITE1", "SPEC1", "GW")
    assert "3 unlocked override(s)" in result.output
    assert "SITE1/SPEC1/GW" in result.output


def test_lock_new_override_sets_anchor_and_locks(fake_files):
    with _pass_guard(), \
         patch(f"{_CORE}.get_override", return_value=None), \
         patch(f"{_CORE}.save_override") as sv:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "lock",
             str(fake_files["gdb"]),
             "--site", "SITE1", "--spec", "SPEC1", "--location", "MW-1",
             "--anchor-x", "100.0", "--anchor-y", "200.0"],
        )
    assert result.exit_code == 0, result.output
    saved = sv.call_args[0][1]
    assert saved.locked is True
    assert (saved.anchor_x, saved.anchor_y) == (100.0, 200.0)
    assert (saved.offset_x, saved.offset_y) == (0.0, 0.0)
    assert saved.location_id == "MW-1"


def test_lock_existing_override_preserves_notes_zeroes_offsets(fake_files):
    existing = CalloutOverride(
        site_id="SITE1", location_id="MW-1", figure_spec_id="SPEC1",
        anchor_x=1.0, anchor_y=2.0, offset_x=9.0, offset_y=9.0,
        preferred_quadrant="SW", locked=False, notes="keep me",
    )
    with _pass_guard(), \
         patch(f"{_CORE}.get_override", return_value=existing), \
         patch(f"{_CORE}.save_override") as sv:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "lock",
             str(fake_files["gdb"]),
             "--site", "SITE1", "--spec", "SPEC1", "--location", "MW-1",
             "--anchor-x", "100.0", "--anchor-y", "200.0"],
        )
    assert result.exit_code == 0, result.output
    saved = sv.call_args[0][1]
    assert saved.locked is True
    assert (saved.anchor_x, saved.anchor_y) == (100.0, 200.0)
    assert (saved.offset_x, saved.offset_y) == (0.0, 0.0)
    assert saved.notes == "keep me"
    assert saved.preferred_quadrant == "SW"


def test_unlock_round_trips_full_row(fake_files):
    existing = CalloutOverride(
        site_id="SITE1", location_id="MW-1", figure_spec_id="SPEC1",
        map_type="GW", anchor_x=100.0, anchor_y=200.0,
        preferred_quadrant="NE", locked=True, notes="hand placed",
    )
    with _pass_guard(), \
         patch(f"{_CORE}.get_override", return_value=existing) as go, \
         patch(f"{_CORE}.save_override") as sv:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "unlock",
             str(fake_files["gdb"]),
             "--site", "SITE1", "--spec", "SPEC1", "--location", "MW-1",
             "--map-type", "GW"],
        )
    assert result.exit_code == 0, result.output
    go.assert_called_once_with(str(fake_files["gdb"]), "SITE1", "SPEC1",
                               "MW-1", map_type="GW")
    saved = sv.call_args[0][1]
    assert saved.locked is False
    assert saved.notes == "hand placed"          # nothing else touched
    assert (saved.anchor_x, saved.anchor_y) == (100.0, 200.0)


def test_unlock_missing_override_errors_cleanly(fake_files):
    with _pass_guard(), \
         patch(f"{_CORE}.get_override", return_value=None), \
         patch(f"{_CORE}.save_override") as sv:
        result = CliRunner().invoke(
            autogis,
            ["envmon", "manage-callout-overrides", "unlock",
             str(fake_files["gdb"]),
             "--site", "SITE1", "--spec", "SPEC1", "--location", "MW-9"],
        )
    assert result.exit_code != 0
    assert "No override found" in result.output
    sv.assert_not_called()
