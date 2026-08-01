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


def _command_labels(tree: ast.Module) -> list[tuple[str, ast.FunctionDef]]:
    """(GUI label, body) for every module-level Click command/group def.

    Labels are built from the full group path so nested leaves match
    introspect/UNREACHABLE labels: a command decorated `@coc_group.command`
    yields "envmon coc <name>", not "coc_group <name>". Groups are always
    defined before the commands that reference them, so one source-order
    pass resolves every prefix.
    """
    prefixes: dict[str, tuple[str, ...]] = {"autogis": ()}  # root name dropped
    out: list[tuple[str, ast.FunctionDef]] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.attr in ("command", "group")):
                continue
            parent = dec.func.value.id
            if parent == "click":  # @click.group() defines a root; its name
                prefixes[node.name] = ()  # is dropped from GUI labels
                continue
            name = (dec.args[0].value
                    if dec.args and isinstance(dec.args[0], ast.Constant)
                    else node.name)  # @autogis.group() -> Click's default name
            path = prefixes.get(parent, (parent,)) + (name,)
            if dec.func.attr == "group":
                prefixes[node.name] = path
            out.append((" ".join(path), node))
    return out


def _unconditional_pyt_redirects(tree: ast.Module | None = None) -> dict[str, int]:
    """Command label -> line, for every cli.py body that *always* redirects.

    A class-1 body guards, then raises "use the .pyt" with nothing gating the
    raise. A raise nested under an `if` is a hybrid leg (reconcile-locations'
    `--gdb`), a `.pyt` mention in a docstring is just a pointer at a sibling
    tool (export-civil3d), and a body containing a `return` has a completing
    headless leg (`if dry_run: ...; return` then redirect) -- none of these
    makes the command unreachable.
    """
    if tree is None:
        tree = ast.parse(Path(cli_module.__file__).read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for label, node in _command_labels(tree):
        # ponytail: any `return` counts as a headless leg; a dead return
        # after an unconditional raise would false-pass -- no such shape
        # exists in cli.py, revisit if one appears.
        if any(isinstance(s, ast.Return) for s in ast.walk(node)):
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


def test_detector_handles_nested_groups_and_early_return_hybrids():
    # Pins the two shapes cli.py doesn't have yet (codex P2s on PR #404): a
    # redirect-only leaf under a nested group must derive the GUI label
    # ("envmon coc x", not "coc_group x"), and an early-return hybrid
    # (`if dry_run: ...; return` then a top-level redirect) must not be
    # classified as redirect-only.
    detected = _unconditional_pyt_redirects(ast.parse(
        'import click\n'
        '@click.group()\n'
        'def autogis(): pass\n'
        '@autogis.group("envmon")\n'
        'def envmon(): pass\n'
        '@envmon.group("coc")\n'
        'def coc_group(): pass\n'
        '@coc_group.command("fake-redirect")\n'
        'def fake_redirect():\n'
        '    raise click.UsageError("use the .pyt tool")\n'
        '@envmon.command("fake-hybrid")\n'
        'def fake_hybrid(dry_run):\n'
        '    if dry_run:\n'
        '        return\n'
        '    raise click.UsageError("use the .pyt tool")\n'))
    assert detected == {"envmon coc fake-redirect": 10}


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
