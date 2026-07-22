"""GUI reachability policy (ADR-0062): the class-1 UNREACHABLE map lists the
LOCAL tools that only redirect to the .pyt (never execute via the CLI even
with arcpy present), so the window can grey them out instead of offering a
button that always HALTs. Drift guard: every label must be a real command."""

from autogis.adapters.gui.introspect import introspect_cli
from autogis.adapters.gui.reachability import UNREACHABLE


def test_unreachable_labels_resolve_to_real_commands():
    labels = {f.label for f in introspect_cli()}
    for label in UNREACHABLE:
        assert label in labels, f"UNREACHABLE references unknown command {label!r}"
        assert UNREACHABLE[label], f"{label} has an empty reason"


def test_class2_executable_local_tools_are_not_marked():
    # these DO run via the CLI when arcpy is present -> must stay runnable
    labels = {f.label for f in introspect_cli()}
    for label in ("envmon import-edd", "envmon validate-db",
                  "envmon upgrade-schema", "agol sync-to-gdb",
                  "envmon survey-to-well-elevation", "envmon update-layout-text",
                  "envmon manage-callout-overrides list",
                  "envmon manage-callout-overrides clear",
                  "envmon manage-callout-overrides lock",
                  "envmon manage-callout-overrides unlock"):
        # a mistyped label would vacuously pass "not in UNREACHABLE"
        # (sync-to-gdb sat here as "envmon sync-to-gdb" -- wrong group)
        assert label in labels, f"not a live command: {label!r}"
        assert label not in UNREACHABLE


def test_class1_redirect_only_tools_are_marked():
    for label in ("envmon import-gdb", "envmon build-event",
                  "envmon build-callouts", "envmon gw-contours",
                  "envmon export-figures", "envmon full-pipeline",
                  "envmon optimize-callouts",
                  "envmon build-cad-package",
                  # shipped without an entry, so the GUI offered an always-HALT
                  # button -- each _guard()s then unconditionally redirects.
                  "envmon run-gw-model-pipeline", "envmon condition-dem",
                  "envmon compare-drone-surfaces"):
        assert label in UNREACHABLE


def test_build_conc_surface_stays_reachable_via_dry_run():
    # build-conc-surface has a headless --dry-run leg, so it must NOT be marked
    # unreachable even though its arcpy write stage is Pro-only (cf. the module
    # docstring's export-civil3d rationale).
    assert "envmon build-conc-surface" not in UNREACHABLE
