from autogis.runtime.capabilities import Runtime, TOOLS, _REGISTRY_SEED, requires_arcpy


def test_harvester_is_hybrid():
    assert TOOLS["harvest"] is Runtime.HYBRID


def test_local_tools_require_arcpy():
    assert requires_arcpy("import-gdb") is True
    assert requires_arcpy("harvest") is False


def test_cloud_ok_tools_do_not_require_arcpy():
    for name in ("inspect", "parser-profile", "figure-spec"):
        assert requires_arcpy(name) is False


# ---------------------------------------------------------------------------
# Registration-drift guard (issue #106/H3): a tool can exist in up to four
# hand-maintained places (click command, TOOLS guard registry, discovery
# _REGISTRY_SEED, .pyt). Nothing checked agreement, so batches routinely
# forgot the discovery registry (issue #98). These two tests turn that
# per-batch memory obligation into CI.
# ---------------------------------------------------------------------------

def test_every_envmon_command_registered_for_discovery():
    """Every live envmon click command has a capabilities._REGISTRY_SEED
    entry -- otherwise it's invisible to `envmon list-tools`."""
    from autogis.adapters.cli import envmon

    registered = {command for (command, *_rest) in _REGISTRY_SEED}
    live = set(envmon.commands.keys())
    missing = sorted(live - registered)
    assert not missing, (
        f"envmon commands missing from capabilities._REGISTRY_SEED "
        f"(invisible to `envmon list-tools`): {missing}")


def test_every_guarded_command_is_in_tools():
    """Every name passed to cli._guard(...) must resolve in capabilities.TOOLS,
    or the guard raises a KeyError at runtime instead of a clean click error
    (the exact failure class behind issue #62)."""
    import inspect
    import re

    from autogis.adapters import cli

    guarded = set(re.findall(r'_guard\("([^"]+)"\)', inspect.getsource(cli)))
    assert guarded, "expected at least one _guard(...) call in cli.py"
    missing = sorted(name for name in guarded if name not in TOOLS)
    assert not missing, (
        f"names passed to _guard() missing from capabilities.TOOLS: {missing}")


def test_pyt_redirect_targets_exist():
    """Every CLI redirect message that says "Use the <X> tool in the .pyt
    toolbox" must name a class that actually exists in toolbox.pyt.

    This drift class is real, not hypothetical: the 2026-07-01 architecture
    review (docs/reviews/fable-architecture-review.md, H2) found two
    redirect messages pointing at wrong/nonexistent .pyt classes and fixed
    them by hand, and 5.2/5.3 shipped pointing at classes that never existed
    (ADR-0039 / issue #161). This is the .pyt leg of the four-surface
    consistency guard above.

    Ceiling: matches the current message phrasing only -- a rephrased
    redirect drops out of the check silently (the non-empty assert below
    catches wholesale rot, not one-off rewording).
    """
    import ast
    import inspect
    import re
    from pathlib import Path

    import autogis
    from autogis.adapters import cli

    # Implicit string-literal concatenation is folded at parse time, so the
    # split message literals in cli.py appear as single ast.Constant values.
    cli_strings = [
        node.value for node in ast.walk(ast.parse(inspect.getsource(cli)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    targets = set()
    for s in cli_strings:
        targets.update(re.findall(r"Use the (\w+)\s+tool in the \.pyt toolbox", s))
    assert targets, "expected at least one '.pyt toolbox' redirect message in cli.py"

    pyt = Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
    tree = ast.parse(pyt.read_text(encoding="utf-8"), filename=str(pyt))
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}

    missing = sorted(targets - classes)
    assert not missing, (
        f"cli.py redirect messages point at .pyt tool classes that do not "
        f"exist in toolbox.pyt: {missing}")


def test_qa_report_commands_share_fail_on_contract():
    """Every envmon command that declares BOTH --report and --fail-on must
    use the shared contract (choices error/warning, default "error"), except
    an explicit, named exemption. Locks issue #66's QA-reporting consistency
    finding as a regression test -- the #82 bug class (a command declaring
    --fail-on but not honoring it, or diverging silently on its default)
    can't recur on any command this test covers.

    Deliberately does NOT require every --report-only command to gain a
    --fail-on option: ~13 report-producing commands
    (build-max-result-dataset, generate-qc-summary, build-compliance-table,
    generate-reg-tables, export-geopackage, generate-site-narrative,
    build-report-package, export-lab-request, build-report-appendix,
    build-exceedance-event, build-dashboard-data-mart,
    generate-arcade-labels, generate-python-labels) currently hardcode their
    fail_on severity instead of exposing it. Most default to "warning", not
    the shared contract's "error" -- adding the option requires a per-command
    call on the right default (a real behavior decision, not a mechanical
    rename), so it's left as a tracked follow-up rather than guessed here."""
    import click

    from autogis.adapters.cli import envmon

    # Intentional divergence: validate-rtk-survey defaults --fail-on to
    # "warning" (RTK precision warnings are routinely expected). See the
    # comment at its @click.option("--fail-on", ...) call site in cli.py.
    exemptions = {"validate-rtk-survey"}

    def walk(group, prefix=()):
        for name, cmd in group.commands.items():
            path = prefix + (name,)
            if isinstance(cmd, click.Group):
                yield from walk(cmd, path)
            else:
                yield path, cmd

    violations = []
    for path, cmd in walk(envmon):
        label = " ".join(path)
        params = {p.name: p for p in cmd.params}
        if "report" not in params or "fail_on" not in params:
            continue
        if label in exemptions:
            continue
        fail_on = params["fail_on"]
        choices = list(getattr(fail_on.type, "choices", []) or [])
        if choices != ["error", "warning"]:
            violations.append(
                f"{label}: --fail-on choices are {choices!r}, expected "
                f"['error', 'warning']")
        if fail_on.default != "error":
            violations.append(
                f"{label}: --fail-on default is {fail_on.default!r}, "
                f"expected 'error'")

    assert not violations, "QA-reporting contract violations:\n" + "\n".join(violations)
