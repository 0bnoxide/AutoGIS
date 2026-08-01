"""GUI reachability policy (ADR-0062): the class-1 UNREACHABLE map lists the
LOCAL tools that only redirect to the .pyt (never execute via the CLI even
with arcpy present), so the window can grey them out instead of offering a
button that always HALTs. Drift guard: every label must be a real command,
and every redirect-only body in cli.py must have an entry."""

import ast
from pathlib import Path

import autogis.adapters.cli as cli_module
from autogis.adapters.gui.introspect import introspect_cli
from autogis.adapters.gui.reachability import UNREACHABLE


def _unconditional_pyt_redirects() -> dict[str, int]:
    """Command label -> line, for every cli.py body that *always* redirects.

    A class-1 body guards, then raises "use the .pyt" with nothing gating the
    raise. A raise nested under an `if` is a hybrid leg (reconcile-locations'
    `--gdb`), and a `.pyt` mention in a docstring is just a pointer at a
    sibling tool (export-civil3d) -- neither makes the command unreachable.
    """
    tree = ast.parse(Path(cli_module.__file__).read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        label = None
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ("command", "group")
                    and dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.func.value, ast.Name)):
                label = f"{dec.func.value.id} {dec.args[0].value}"
        if label is None:
            continue
        gated = {id(r) for branch in ast.walk(node)
                 if isinstance(branch, ast.If)
                 for r in ast.walk(branch) if isinstance(r, ast.Raise)}
        for stmt in ast.walk(node):
            if (isinstance(stmt, ast.Raise) and stmt.exc is not None
                    and id(stmt) not in gated
                    and ".pyt tool" in ast.unparse(stmt.exc)):
                found[label] = stmt.lineno
    return found


def test_every_redirect_only_command_is_marked_unreachable():
    # The bug this guards: three class-1 bodies (run-gw-model-pipeline,
    # condition-dem, compare-drone-surfaces) shipped with no UNREACHABLE entry,
    # so the GUI offered buttons that always HALT. The sibling tests below are
    # hardcoded allowlists -- they pin what is already known and stay green when
    # a *new* redirect-only command is added, which is exactly how that shipped.
    # This one derives the set from cli.py instead, so the next one fails here.
    missing = {label: line for label, line in _unconditional_pyt_redirects().items()
               if label not in UNREACHABLE}
    assert not missing, (
        "cli.py bodies redirect to the .pyt unconditionally but have no "
        f"reachability.UNREACHABLE entry, so the GUI would offer an "
        f"always-HALT button: {missing} (label -> cli.py line)")


def test_redirect_detector_separates_conditional_and_docstring_mentions():
    # Pins the detector itself: a false positive here would force a bogus
    # UNREACHABLE entry and grey out a command that really does run.
    detected = _unconditional_pyt_redirects()
    assert "envmon import-gdb" in detected          # class-1, top-level raise
    assert "envmon reconcile-locations" not in detected  # raise gated by --gdb
    assert "envmon export-civil3d" not in detected      # docstring mention only


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
