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
from autogis.runtime.capabilities import (
    _REGISTRY_SEED, RUNTIME_CLASSES, TOOLS, Runtime)

PYT_PATH = Path(autogis.__file__).parent / "adapters" / "toolbox.pyt"
ROADMAP_PATH = Path(__file__).resolve().parents[1] / "docs" / \
    "envmon-feature-roadmap.md"


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
    must agree on runtime class. Group-qualified seed commands
    ("agol sync-to-gdb") map to their bare TOOLS key (last token) so agol
    entries stay covered. Was LOCAL-ness-only until issue #346 (seed said
    CLOUD for the HYBRID reconcile-locations).

    Until #468 this test carved out `seed_rt == "DRAFT"` as "a documented
    display state", which is what let manage-screening-levels sit in the
    runtime column with a value that is not a runtime class -- invisible to
    `list-tools --runtime CLOUD` while RUNTIME_MAP said CLOUD. Draft-ness is
    the `status` field's job; the carve-out is gone."""
    seed_rt = {c.split()[-1]: rt for (c, _n, _rid, rt, *_rest) in _REGISTRY_SEED}
    conflicts = [
        f"{c}: TOOLS={TOOLS[c].value} seed={seed_rt[c]}"
        for c in sorted(set(seed_rt) & set(TOOLS))
        if seed_rt[c] != TOOLS[c].value.upper()
    ]
    assert not conflicts, (
        "runtime class drift between capabilities.TOOLS and _REGISTRY_SEED:\n"
        + "\n".join(conflicts))


def test_seed_runtime_values_are_real_runtime_classes():
    """The runtime column may only hold a Runtime enum name (#468). A row
    holding anything else is silently dropped by `filter_tools`, which
    compares `t.runtime.upper()` against the requested class -- so
    `list-tools --runtime CLOUD`, the question "what runs without ArcGIS
    Pro", answers with every CLOUD tool but that one. The sibling test above
    only covers commands present in TOOLS; this one covers all 130 rows."""
    off_vocab = sorted(f"{c}: {rt!r}"
                       for (c, _n, _rid, rt, *_rest) in _REGISTRY_SEED
                       if rt not in RUNTIME_CLASSES)
    assert not off_vocab, (
        f"_REGISTRY_SEED runtime values outside {sorted(RUNTIME_CLASSES)}: "
        f"{off_vocab}")


def test_runtime_filter_choice_offers_exactly_the_real_classes():
    """`list-tools --runtime` must not offer a value no row can legally hold.
    DRAFT was an explicit Choice, which is what made the bad seed row read as
    intentional rather than as the typo it was (#468)."""
    opt = next(p for p in cli.envmon.commands["list-tools"].params
               if p.name == "runtime_filter")
    assert set(opt.type.choices) == set(RUNTIME_CLASSES)


def test_seed_status_values_match_the_documented_vocabulary():
    """`ToolCapability.status` documents 'stable | draft | planned | deprecated'
    and `list-tools --status` offers exactly those four. The seed is plain
    tuples, so nothing enforced it: export-wqx shipped 'DRAFT' (uppercase),
    the only row of 130 off-vocabulary. `filter_tools` lowercases both sides,
    so the row was still findable -- but it rendered a status no other row
    used. The runtime column's own stray 'DRAFT' (#468) is what made that
    spelling easy to mistake for intent; both are pinned now."""
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


# ---------------------------------------------------------------------------
# roadmap_id <-> the 79-tool catalog (issue #458)
# ---------------------------------------------------------------------------
# `docs/envmon-feature-roadmap.md` is the authority for `Tool N.N` numbers;
# each catalog section declares its owner with a `**Tool name:**` line. Six
# shipped tools carried a number the catalog assigns to a *different* tool,
# and the wrong value was mirrored into the cli.py docstring (so it reached
# users via --help), the core module docstring and the README -- all four
# surfaces agreeing, none contradicting.

def _catalog_sections() -> dict[str, set[str]]:
    """{'10.3': {'UpgradeEnvMonitoringGDBSchema'}} from the roadmap catalog."""
    sections: dict[str, set[str]] = {}
    num = None
    for line in ROADMAP_PATH.read_text(encoding="utf-8").splitlines():
        head = re.match(r'^#{2,4}\s+(\d+\.\d[0-9A-Za-z]*)\s+\S', line)
        if head:
            num = head.group(1)
            sections.setdefault(num, set())
            continue
        tool = re.match(r'\*\*Tool name:\*\*\s*`?([A-Za-z0-9_]+)`?', line.strip())
        if tool and num:
            sections[num].add(tool.group(1))
    assert len(sections) > 50, f"catalog parse found only {len(sections)} sections"
    return sections


def _dotted_seed_ids() -> list[tuple[str, str, str]]:
    """(command, name, roadmap_id) for seed rows using catalog N.N numbering.

    Bare integers ('2') are the original ten-tool numbering and 'S123-*' is
    the Survey123 add-on's own vocabulary -- neither indexes this catalog.
    """
    return [(c, n, rid) for (c, n, rid, *_r) in _REGISTRY_SEED
            if re.fullmatch(r'\d+\.\d[0-9A-Za-z]*', rid or "")]


def test_every_roadmap_id_resolves_to_a_catalog_section():
    """A dotted roadmap_id that resolves to nothing is a dangling citation:
    `list-tools --verbose` prints a spec section the reader cannot open.
    Caught upgrade-schema='1.4', export-lab-request='2.11' and
    fieldmaps-preflight='7.5'. A trailing letter marks a sub-tool of a real
    section (2.3a, 5.4b, 8.0b), so it is stripped before lookup."""
    sections = _catalog_sections()
    dangling = [f"{c}: {rid!r}" for c, _n, rid in _dotted_seed_ids()
                if rid.rstrip("abc") not in sections and rid not in sections]
    assert not dangling, (
        "roadmap_id values with no matching '### N.N' heading in "
        f"{ROADMAP_PATH.name}: {dangling}")


def test_no_two_tools_claim_one_catalog_section():
    """Two tools under one number means at least one is pointing at another
    tool's spec. `run-history-report` and `list-tools` both claimed 10.1;
    `list-tools` is the catalog's ListAvailableEnvTools, so the report tool
    was the wrong one -- and `envmon list-tools --verbose` printed both under
    10.1 with no indication either was wrong.

    Rows sharing a *name* are one tool reached by a command pair (the
    validate+import boring-log and drone-product pairs) and are fine.
    """
    claims: dict[str, set[str]] = {}
    for _c, name, rid in _dotted_seed_ids():
        claims.setdefault(rid, set()).add(name)
    collisions = {rid: sorted(ns) for rid, ns in claims.items()
                  if len(ns) > 1}
    assert not collisions, f"multiple tools claim one catalog section: {collisions}"


def test_catalog_section_numbers_are_unique():
    """The catalog is the declared authority for `Tool N.N` numbers, so one
    number must head exactly one section. It carried duplicate 8.2/8.3/8.4
    headings for months (#476) and every id built on them was ambiguous."""
    nums = re.findall(r'^#{2,4}\s+(\d+\.\d[0-9A-Za-z]*)\s',
                      ROADMAP_PATH.read_text(encoding="utf-8"), re.M)
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert not dupes, f"duplicate section numbers in {ROADMAP_PATH.name}: {dupes}"


def test_post_roadmap_extras_claim_no_catalog_number():
    """The seven tools of #458 appear nowhere in the 79-tool catalog -- they
    are post-roadmap extras, and every number they carried belonged to a
    named catalog tool that ships separately. Empty is the honest value.

    Curated by necessity: the catalog and the registry use different names
    for the same tool in eleven legitimate cases (BuildCalloutsHullCollision
    vs OptimizeCalloutPlacement, and so on), so no name-matching rule can
    separate a wrong number from a renamed tool. This pins the seven that
    were verified absent from the catalog.
    """
    extras = {
        "ApplyScreening", "ExportComparisonResultsToExcel",
        "BuildGroundwaterLevelSummary", "RunHistorySummaryReport",
        "RunHistoryQuery", "ValidateScheduleYAML", "ExportGeoJSON",
        "GenerateMonitoringEventReport",
    }
    catalog = ROADMAP_PATH.read_text(encoding="utf-8")
    still_absent = sorted(n for n in extras if n in catalog)
    assert not still_absent, (
        "these are listed as post-roadmap extras but now appear in the "
        f"catalog -- give them their number instead: {still_absent}")
    numbered = sorted(f"{c}: {rid!r}" for (c, n, rid, *_r) in _REGISTRY_SEED
                      if n in extras and rid)
    assert not numbered, (
        f"post-roadmap extras must carry roadmap_id='': {numbered}")


# ---------------------------------------------------------------------------
# roadmap_id <-> the README's `Roadmap #` column (issue #477)
# ---------------------------------------------------------------------------
# #458 was six tools carrying the *wrong* number. This is the inverse and the
# last direction of the same drift: thirteen tools whose number the README
# already knew while `list-tools --verbose` -- the in-product answer to "which
# spec section describes this tool" -- printed a blank. A blank is honest, so
# nothing misled, but the two surfaces disagreed in the direction of silence
# and nothing pinned it.

# Rows where the README column and the seed use different vocabularies, or
# where the catalog itself cannot answer. Each needs a reason, not a shrug:
_ROADMAP_COLUMN_EXEMPT = {
    # README cites the catalog section, the seed carries the original
    # ten-tool number (the "Tool 8:"/"Tool 5:" in the same row's description).
    # Both are right in their own vocabulary; which one the column should
    # speak is an owner call about the README, not a registry fix.
    "validate-db": "README 3.1 = catalog section; seed 8 = ten-tool number",
    "gw-contours": "README 4.2 = catalog section; seed 5 = ten-tool number",
    # Same split, and the README's '4' resolves to no `### 4.x` section at all
    # -- BuildCurrentEvent has no catalog entry (only a passing mention at
    # roadmap L2060). Populating it would invent a citation.
    "build-event": "README 4 heads no catalog section; seed 3 = ten-tool number",
    # Blocked on the catalog carrying two `### 8.3` / `### 8.4` headings
    # each (#476). The *tool name* disambiguates -- only L1372/L1408 name
    # these two -- but the number a reader would resolve from
    # `list-tools --verbose` still means two things, so populating it would
    # hand out an ambiguous citation. Delete these two once #476 renumbers.
    "import-rtk-survey": "catalog has two `### 8.3` headings (#476)",
    "validate-rtk-survey": "catalog has two `### 8.4` headings (#476)",
}


def _readme_roadmap_numbers() -> dict[str, str]:
    """{command: README `Roadmap #` cell} for rows that carry a number."""
    readme = (Path(autogis.__file__).resolve().parents[1] / "README.md")
    rows: dict[str, str] = {}
    for m in re.finditer(
            r'^\|[^|]*\|\s*([0-9][0-9./a-zA-Z]*)\s*\|\s*`envmon ([a-z0-9-]+)`',
            readme.read_text(encoding="utf-8"), re.M):
        rows.setdefault(m.group(2), m.group(1))
    assert len(rows) > 50, f"README parse found only {len(rows)} numbered rows"
    return rows


def test_readme_roadmap_number_implies_a_registry_roadmap_id():
    """A number the README knows must not be blank in the registry (#477).

    `envmon list-tools --verbose` exists to tie a shipped tool back to its
    spec section; thirteen of its rows under-reported while a second
    hand-maintained surface had the answer.
    """
    seed = {c: rid for (c, _n, rid, *_r) in _REGISTRY_SEED}
    blank = sorted(f"{c} (README {num})"
                   for c, num in _readme_roadmap_numbers().items()
                   if c in seed and not seed[c]
                   and c not in _ROADMAP_COLUMN_EXEMPT)
    assert not blank, (
        "README carries a Roadmap # but TOOL_REGISTRY.roadmap_id is empty; "
        "verify the number against docs/envmon-feature-roadmap.md and "
        f"populate _REGISTRY_SEED: {blank}")


def test_readme_and_registry_agree_on_the_number_they_both_carry():
    """The forward direction of the same parity: where both surfaces name a
    number, it must be the same number. This is #458's failure mode, pinned
    against the README rather than against the catalog."""
    seed = {c: rid for (c, _n, rid, *_r) in _REGISTRY_SEED}
    # A '2/3' cell is one tool spanning two ten-tool numbers (import-gdb);
    # the registry names one of them, which is agreement, not drift.
    disagree = sorted(f"{c}: README {num!r} vs registry {seed[c]!r}"
                      for c, num in _readme_roadmap_numbers().items()
                      if seed.get(c) and seed[c] not in num.split("/")
                      and c not in _ROADMAP_COLUMN_EXEMPT)
    assert not disagree, (
        f"README `Roadmap #` disagrees with TOOL_REGISTRY: {disagree}")


def test_roadmap_column_exemptions_are_still_live():
    """An exemption that outlives its reason is how the next #458 hides.
    Every exempted command must still exist and still be exempt-worthy --
    i.e. actually appear in the README's numbered rows."""
    numbered = _readme_roadmap_numbers()
    stale = sorted(c for c in _ROADMAP_COLUMN_EXEMPT if c not in numbered)
    assert not stale, (
        f"exempted commands no longer carry a README Roadmap #: {stale}")
