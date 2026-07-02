# ADR-0039: Generation-2 LOCAL tools are CLI-first; scope the two callout dead ends

**Status:** Accepted

**Date:** 2026-07-02

## Context

ADR-0006 established `.pyt` toolbox as the primary UI for LOCAL (arcpy-requiring)
tools, with the CLI guarding then redirecting: "Run it in the .pyt toolbox inside
Pro." That convention correctly describes tools 2-8 (harvest, `import-gdb` through
`validate-db`) — each has a real `.pyt` entry and the CLI intentionally never
executes their logic directly (`cli.py`'s tools-2-8 block, "No rich ergonomics
here; the .pyt is their primary UI").

Roughly 12 LOCAL tools added since ADR-0006 follow the opposite convention: guard,
then execute the real work in the CLI via lazy arcpy (`import-edd`,
`import-rtk-survey`, `route-survey123`, `build-dashboard-data-mart`,
`register-drone-flight`, `import-drone-products`, `import-boring-logs`,
`survey-to-well-elevation`, `upgrade-schema`, `export-snapshot`,
`update-well-elevations`, `draft-plume-boundary`, `build-cad-package`,
`export-civil3d`) — and have **no `.pyt` entry at all**. For these, the old guard
message ("Run it in the .pyt toolbox inside Pro") was actively wrong: there is no
toolbox entry to run.

Two tools were also found unreachable in *every* environment: `optimize-callouts`
(Tool 5.2) and the `manage-callout-overrides` subcommands (Tool 5.3) guard, then
unconditionally raise, pointing at `OptimizeCalloutPlacement` /
`ManageCalloutPlacementOverrides` `.pyt` classes that do not exist in
`toolbox.pyt`. (Originally flagged as finding H2 in the independent architecture
review, `docs/reviews/fable-architecture-review.md`, merged in #103.)

## Decision

**ADR-0006 is refined, not superseded.** It still correctly governs tools 2-8: the
`.pyt` toolbox remains their primary UI, and the CLI's guard-then-redirect for them
is intentional, not a bug.

**Generation-2 LOCAL tools (everything added since ADR-0006 without a `.pyt`
entry) are CLI-first**: they run directly inside a cloned `arcgispro-py3` conda
env via the CLI. A `.pyt` GUI is added for a generation-2 tool only when it
specifically needs interactive map context (selecting features, previewing
placement, etc.) that a headless CLI invocation can't provide.

**`guard.py`'s message is now generic instead of one-size-wrong**: it no longer
claims every LOCAL tool has a `.pyt` entry. Rather than add a new
`has_pyt_entry: bool` field to the tool registry (which would be a fourth
hand-maintained registration surface — exactly the drift class fixed in #106/H3,
now with no CI guard of its own), the message states both real options
(arcgispro-py3 env, or the `.pyt` toolbox *if* an entry exists for this tool)
without asserting which applies to a given tool name.

**The two callout dead ends are scoped, not built:**

- **`optimize-callouts` (5.2):** its function was already superseded by a
  different, more detailed design before this ADR — `docs/superpowers/plans/
  2026-06-27-optimize-callout-placement.md` extends `assemble_callouts`
  (`build_figure_dataset.py`) with a `use_hull_collision` flag and specifies
  adding `--use-hull-collision` to the existing `build-callouts` command, not a
  standalone `optimize-callouts` command. `assemble_callouts` already implements
  `use_hull_collision` (Task 3 of that plan shipped); the CLI flag (Task 4) was
  never added, and `build-callouts` itself is a tools-2-8 guard-then-`.pyt`-only
  stub, so the flag would currently have nowhere to take effect even if added.
  Building a standalone `optimize-callouts` CLI command now would both invent
  scope beyond any current design and directly contradict the newer plan.
  **Decision: the CLI command's error message states this history plainly instead
  of pointing at a nonexistent `.pyt` class.** Wiring `--use-hull-collision` into
  `build-callouts`'s `.pyt` `execute()` is a legitimate follow-up but is untestable
  here (no arcpy) and out of scope for this ADR.
- **`manage-callout-overrides` (5.3):** the core CRUD
  (`autogis/core/envmon/manage_callout_overrides.py` — `load_overrides`,
  `save_override`, `clear_unlocked_overrides`) exists and is unit-tested
  (`tests/envmon/test_manage_callout_overrides.py`, arcpy mocked). Wiring `list`
  and `clear` to it is mechanical. Wiring `lock` is mechanical. Wiring `unlock`
  is **not**: `unlock` must read the existing override, flip `locked=False`, and
  re-save, but `load_overrides` returns only `{origin, preferred_quadrant,
  locked}` — it drops `anchor_x/y`, `offset`, `map_type`, `sample_id`, `notes`,
  so there is no way to reconstruct the full `CalloutOverride` `save_override`
  requires. `unlock` also takes no `--map-type`, while `save_override`'s upsert
  key includes `MapType` — so even with a full record, `unlock` cannot identify
  which row to update when a location has overrides for more than one map type.
  **Decision: leave `manage-callout-overrides` fully deferred rather than ship a
  CLI that wires 3 of 4 subcommands and silently mis-behaves (or crashes) on the
  4th.** A correct fix needs a new "read one full override" core function plus a
  CLI signature change (`--map-type` on `unlock`) — a small but real design
  decision, tracked as a follow-up rather than done under this ADR. Any code
  written for this would also be arcpy-only and untestable in this environment,
  same risk class as the deferred write side in ADR-0017/#104.

## Consequences

### Positive consequences

- `guard.py`'s error message is now truthful for every LOCAL tool, generation-1
  or -2, without adding a new hand-maintained field.
- The two callout dead ends now tell a user (or the next batch) the real reason
  and the real follow-up instead of sending them to look for a `.pyt` tool that
  doesn't exist.
- No arcpy-only code was added that this environment can't exercise, keeping the
  same discipline applied to ADR-0017/#104.

### Negative consequences

- `optimize-callouts` and `manage-callout-overrides` remain non-functional CLI
  commands. Acceptable: they were already non-functional; this ADR makes that
  honest instead of fixing it, and the actual fixes (small but real) are better
  done as their own reviewed change than folded into an architecture-drift
  cleanup batch.
- The generic guard message is less specific per-tool than a `has_pyt_entry`
  field would allow. Accepted as the right trade against a fourth
  hand-maintained registration surface with no test coverage of its own.

## Alternatives considered

1. **Add `has_pyt_entry: bool` to the tool registry:** More precise guard
   messages. Rejected without a paired consistency test (AST-parsing
   `toolbox.pyt` for its `class` list and cross-checking, mirroring
   `test_pyt_toolbox_parses` from #108) — adding untested hand-maintained state
   is exactly the pattern #106/H3 exists to stop repeating. Worth doing later as
   its own change with that test, not bundled here.
2. **Wire `manage-callout-overrides list/clear/lock` now, leave `unlock`
   raising:** Rejected — three working subcommands and one silently-different
   dead end is a worse user experience than a consistently honest "not wired"
   message on the whole group, and the guard already blocks all four in this
   arcpy-free environment, so none of the wiring is testable here regardless.
3. **Build a standalone `optimize-callouts` CLI command per ADR-0020's original
   two-command sketch:** Rejected — contradicted by the later, more detailed
   `2026-06-27-optimize-callout-placement.md` plan, which folds the same
   capability into `build-callouts` instead. Building both would create two
   placement authorities exactly as ADR-0020 itself warned against.

## Related decisions

- [ADR-0006: .pyt toolbox as primary UI for LOCAL tools](0006-pyt-toolbox-as-primary-ui.md)
  — refined, not superseded, by this ADR.
- [ADR-0020: Callout placement — extend assemble_callouts, add
  manage_callout_overrides](0020-callout-placement-extend-assemble-callouts.md) —
  its two-command CLI sketch is superseded by the later hull-collision plan; its
  `manage_callout_overrides.py` core design stands.
- [ADR-0017: CSV-based append-only run history log](0017-run-history-csv-log.md) —
  same "don't build untestable arcpy-only plumbing under an architecture-cleanup
  ADR" discipline applied to its deferred write side.
- `docs/superpowers/plans/2026-06-27-optimize-callout-placement.md` — the plan
  that actually supersedes 5.2's standalone-command design.
- `docs/reviews/fable-architecture-review.md` — finding H2, source of this ADR.
