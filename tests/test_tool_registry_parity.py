"""Cross-adapter tool-registry parity (H3, issue #106 follow-through).

A tool is enumerated by hand in up to five places: the click tree (``cli.py``),
the guard registry (``capabilities.TOOLS``), the discovery registry
(``capabilities._REGISTRY_SEED`` behind ``envmon list-tools``), the ``.pyt``
toolbox, and the GUI reachability policy (``gui/reachability.py``). Existing
guards cover three directions (``test_capabilities.py``: envmon commands are
in the seed, guarded names resolve in TOOLS; ``test_gui_reachability.py``:
UNREACHABLE labels are live). This file closes the *remaining* directions so
no registry can drift without a red test:

- ghost entries (seed/TOOLS keys naming commands that no longer exist),
- LOCAL tools registered in TOOLS but missing their ``_guard`` call,
- runtime-class disagreement between TOOLS (enum) and the seed (string),
- ``.pyt`` tool classes defined but not registered in ``Toolbox.tools``,
- CLI redirect messages naming a nonexistent ``.pyt`` class (the exact bug
  class hand-fixed in docs/reviews/fable-architecture-review.md, previously
  unpinned),
- UNREACHABLE entries for tools that are not LOCAL.

Deliberately NOT asserted: full CLI<->.pyt membership parity. Per ADR-0006
tools 2-8 live primarily in the .pyt; per ADR-0039 generation-2 LOCAL tools
have no .pyt entry *by design*. The .pyt is inspected via ``ast`` only -- it
imports arcpy at module top and can never be imported headless.
"""
import ast
import inspect
import re
from collections import Counter
from pathlib import Path

import click

import autogis
from autogis.adapters import cli
from autogis.adapters.gui.reachability import UNREACHABLE
from autogis.runtime.capabilities import _REGISTRY_SEED, TOOLS, Runtime

PYT_PATH = Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"


# --- shared fixtures (plain helpers; cheap enough to recompute) -------------

def _all_command_names() -> set[str]:
    """Every subcommand name anywhere in the click tree, groups included
    (TOOLS keys are bare subcommand names, e.g. root 'harvest', agol
    'sync-to-gdb', and the 'manage-callout-overrides' envmon group)."""
    names: set[str] = set()

    def walk(group: click.Group) -> None:
        for name, cmd in group.commands.items():
            names.add(name)
            if isinstance(cmd, click.Group):
                walk(cmd)

    walk(cli.autogis)
    return names


def _guarded_names() -> set[str]:
    return set(re.findall(r'_guard\("([^"]+)"\)', inspect.getsource(cli)))


def _pyt_classes() -> tuple[dict[str, ast.ClassDef], list[str]]:
    """(top-level classes, class names registered in Toolbox.tools) via ast."""
    tree = ast.parse(PYT_PATH.read_text(encoding="utf-8"), filename=str(PYT_PATH))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    registered: list[str] = []
    for node in ast.walk(classes["Toolbox"]):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == "tools"
                        for t in node.targets)):
            registered = [e.id for e in node.value.elts
                          if isinstance(e, ast.Name)]
    return classes, registered


# --- ghost entries ----------------------------------------------------------

def test_no_ghost_seed_entries():
    """Reverse of test_every_envmon_command_registered_for_discovery: a seed
    entry whose command was renamed/removed makes `envmon list-tools`
    advertise a command that doesn't exist. Seed commands are bare envmon
    names or group-qualified "agol <name>" entries (ADR-0092)."""
    live = set(cli.envmon.commands.keys())
    live |= {f"agol {name}" for name in cli.agol.commands}
    ghosts = sorted({c for (c, *_rest) in _REGISTRY_SEED} - live)
    assert not ghosts, (
        f"_REGISTRY_SEED entries with no live envmon command "
        f"(`envmon list-tools` advertises dead commands): {ghosts}")


def test_no_duplicate_seed_commands():
    dupes = sorted(c for c, n in
                   Counter(c for (c, *_rest) in _REGISTRY_SEED).items() if n > 1)
    assert not dupes, f"duplicate _REGISTRY_SEED commands: {dupes}"


def test_no_ghost_tools_keys():
    """Every capabilities.TOOLS key must name a live CLI subcommand."""
    ghosts = sorted(set(TOOLS) - _all_command_names())
    assert not ghosts, (
        f"capabilities.TOOLS keys with no live CLI command: {ghosts}")


# --- guard coverage ---------------------------------------------------------

def test_every_local_tool_is_guarded():
    """Reverse of test_every_guarded_command_is_in_tools: a tool registered
    LOCAL whose command body never calls _guard() would skip the runtime gate
    and die on a deep `import arcpy` traceback instead (issue #62's class)."""
    local = {name for name, rt in TOOLS.items() if rt is Runtime.LOCAL}
    unguarded = sorted(local - _guarded_names())
    assert not unguarded, (
        f"LOCAL tools in capabilities.TOOLS whose CLI body never calls "
        f"_guard(): {unguarded}")


# --- metadata agreement -----------------------------------------------------

def test_runtime_class_agrees_between_tools_and_seed():
    """TOOLS (drives the guard) and the seed (drives `list-tools` display)
    must agree on runtime class. Seed 'DRAFT' is a documented display state
    (capabilities.py: 'may differ in spelling from the Runtime enum').
    Group-qualified seed commands ("agol sync-to-gdb") map to their bare
    TOOLS key (last token) so agol entries stay covered. Was LOCAL-ness-only
    until issue #346 (seed said CLOUD for the HYBRID reconcile-locations)."""
    seed_rt = {c.split()[-1]: rt for (c, _n, _rid, rt, *_rest) in _REGISTRY_SEED}
    conflicts = [
        f"{c}: TOOLS={TOOLS[c].value} seed={seed_rt[c]}"
        for c in sorted(set(seed_rt) & set(TOOLS))
        if seed_rt[c] != "DRAFT"
        and seed_rt[c] != TOOLS[c].value.upper()
    ]
    assert not conflicts, (
        "runtime class drift between capabilities.TOOLS and _REGISTRY_SEED:\n"
        + "\n".join(conflicts))


def test_seed_status_values_match_the_documented_vocabulary():
    """`ToolCapability.status` documents 'stable | draft | planned | deprecated'
    and `list-tools --status` offers exactly those four. The seed is plain
    tuples, so nothing enforced it: export-wqx shipped 'DRAFT' (uppercase),
    the only row of 130 off-vocabulary. `filter_tools` lowercases both sides,
    so the row was still findable -- but it rendered a status no other row
    used, and the runtime column's separate, *deliberate* 'DRAFT' spelling
    (see the test above) is what makes that easy to mistake for intent."""
    allowed = {"stable", "draft", "planned", "deprecated"}
    off_vocab = sorted(f"{c}: {st!r}"
                       for (c, _n, _rid, _rt, st, *_rest) in _REGISTRY_SEED
                       if st not in allowed)
    assert not off_vocab, (
        f"_REGISTRY_SEED status values outside {sorted(allowed)}: {off_vocab}")


def test_unreachable_tools_are_local():
    """UNREACHABLE greys out LOCAL tools that never execute via the CLI; an
    entry for a CLOUD/HYBRID tool would contradict the guard registry."""
    for label in UNREACHABLE:
        name = label.split()[1]  # "envmon <name> [sub]" -> <name>
        assert name in TOOLS, f"UNREACHABLE entry {label!r} not in TOOLS"
        assert TOOLS[name] is Runtime.LOCAL, (
            f"UNREACHABLE entry {label!r} is {TOOLS[name].value}, not local")


# --- .pyt toolbox (ast only; never importable headless) ----------------------

def test_every_pyt_tool_class_is_registered():
    """A tool class added to toolbox.pyt but left out of Toolbox.tools is
    invisible inside Pro -- only discoverable by a user missing it."""
    classes, registered = _pyt_classes()
    tool_like = {
        name for name, node in classes.items()
        if name != "Toolbox"
        and any(isinstance(n, ast.FunctionDef) and n.name == "execute"
                for n in node.body)
    }
    assert registered, "could not locate Toolbox.tools assignment"
    missing = sorted(tool_like - set(registered))
    assert not missing, (
        f"toolbox.pyt classes with execute() not listed in Toolbox.tools: "
        f"{missing}")
    unknown = sorted(set(registered) - set(classes))
    assert not unknown, f"Toolbox.tools references undefined classes: {unknown}"


def test_cli_redirect_messages_name_real_pyt_tools():
    """ADR-0006 redirect-only commands tell the user 'Use the <Class> tool in
    the .pyt toolbox'. Two of these named wrong/nonexistent classes until the
    architecture review hand-fixed them (fable-architecture-review.md, 'no
    tests pinned the corrected strings'). Pin them: every class named in a
    redirect must be registered in Toolbox.tools."""
    _classes, registered = _pyt_classes()
    named: set[str] = set()
    # walk joined string constants (implicit concatenation is already merged
    # by the parser, so multi-line messages match)
    for node in ast.walk(ast.parse(inspect.getsource(cli))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            named.update(re.findall(
                r"Use the (\w+)\s+tool in the \.pyt toolbox", node.value))
    assert named, "expected at least one .pyt redirect message in cli.py"
    missing = sorted(named - set(registered))
    assert not missing, (
        f"cli.py redirect messages point at .pyt tools that are not "
        f"registered in Toolbox.tools: {missing}")
