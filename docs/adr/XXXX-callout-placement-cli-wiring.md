# ADR-XXXX: Wire callout-placement tools 5.2 / 5.3 (folded hull-collision flag; override CRUD with a full-row read)

> Placeholder number — the orchestrator assigns the real ADR number at merge to
> avoid collisions with parallel branches.

**Status:** Accepted

**Date:** 2026-07-07

## Context

Tools 5.2 (`optimize-callouts`) and 5.3 (`manage-callout-overrides`) were
dead-ends (issue #161). Both CLI commands passed their arcpy guard, then
unconditionally redirected to `OptimizeCalloutPlacement` /
`ManageCalloutPlacementOverrides` `.pyt` classes that **do not exist** — so both
were unreachable from the CLI *and* from inside ArcGIS Pro. The underlying logic
already existed and was proven:

- **5.2** was superseded by a `use_hull_collision` design (ADR-0020). The core
  seam already shipped: `assemble_callouts(..., use_hull_collision=False)` in
  `build_figure_dataset.py`, covered by `test_rules_and_callouts.py`. It just
  wasn't reachable — `generate_callout_features` (the arcpy writer the `.pyt`
  calls) never accepted or forwarded the flag, and neither the CLI nor the `.pyt`
  exposed it.
- **5.3** had a complete, arcpy-tested override CRUD
  (`manage_callout_overrides.py`: `load_overrides`, `save_override`,
  `clear_unlocked_overrides`). The CLI subcommands raised instead of calling it,
  blocked (per the honest error text) on a missing **read-one-full-override**
  function needed for a lossless `unlock` round-trip.

## Decision

### 5.2 — expose the existing flag; keep one placement authority

- Add `use_hull_collision: bool = False` to `generate_callout_features` and
  forward it to `assemble_callouts`. No new module, no second optimizer — ADR-0020
  already rejected a standalone `optimize_callouts.py`.
- CLI `build-callouts` gains `--use-hull-collision` (mirrors the `.pyt`
  parameter). Both LOCAL commands still redirect to the `.pyt` for actual
  execution (arcpy), so the flag rides through in the redirect message.
- `.pyt` `BuildCallouts` gains a `use_hull_collision` GPBoolean parameter, wired
  into its `generate_callout_features` call.
- `optimize-callouts` stays as a thin, honest alias: it now explains 5.2 was
  folded into `build-callouts --use-hull-collision` and points at the real
  `BuildCallouts` `.pyt` tool + parameter — no longer naming a phantom class.

**Rejected:** removing `optimize-callouts` entirely. A parallel lane ships a
tool-registry parity test and a `.pyt`-redirect-target test; the command name is
referenced from `capabilities.py` and covered by existing help/guard tests.
Keeping it as an alias is the smaller, non-breaking diff.

### 5.3 — add `get_override`, wire the four subcommands

- New arcpy-gated `get_override(gdb, site, spec, location, map_type="")` reads
  **one full row** by its logical key and rebuilds a complete `CalloutOverride`.
  `save_override` rewrites the entire row, so any partial mutation (lock, unlock)
  must first read every field or silently drop the untouched ones. This is the
  one function #161 named as the blocker.
- The key is `(SiteID, FigureSpecID, MapType, LocationID)`. A **blank** map_type
  matches both `''` and `NULL` (`_key_where`), because a file GDB may store an
  empty text value either way. `unlock` gains `--map-type` so it addresses the
  same row `lock` wrote.
- All four subcommands now call the core:
  - `list` → `load_overrides`, prints origin/quadrant/lock state.
  - `clear` → `clear_unlocked_overrides`, reports the count.
  - `lock` → `get_override` (or a fresh one) → set anchor, **zero the offsets**
    (the anchor *is* the box lower-left; a stale offset would shift it), lock,
    `save_override`.
  - `unlock` → `get_override` → flip `locked` → `save_override`; clean
    `ClickException` if the row is absent.
- All SQL literals now go through `sql_quote` (reused from
  `survey_to_well_elevation.py`) — the previous f-string `where` clauses were
  apostrophe-unsafe (e.g. `O'Brien Site`).

### `load_overrides` MapType-collapse fix (pre-existing bug)

`load_overrides` keyed its returned dict by `LocationID.upper()` and filtered
only on `SiteID`/`FigureSpecID` — **no MapType**. Two override rows for one
LocationID under different MapTypes collapsed into that location-keyed dict
(last-read-wins, one silently dropped). Overrides are stored per
`(SiteID, FigureSpecID, MapType, LocationID)`, and a figure render targets one
MapType (`generate_callout_features` already scopes its own delete/insert by
`map_type`), so the fix is to **scope `load_overrides` to a single map_type**,
not to re-key the dict — `assemble_callouts` looks up by LocationID only and is
never multi-map_type, so a composite key would buy nothing and force churn
there. Shared `_scope_where(site, spec, map_type)` (blank ⇒ `'' OR NULL`) now
backs both `load_overrides` and `_key_where`, guaranteeing identical MapType
semantics.

- **Caller `generate_callout_features`** now passes its `map_type` (was the
  latent bug: it loaded every map_type collapsed).
- **CLI `list`** gains `--map-type` (default blank), consistent with
  lock/unlock; each listing is one map_type.
- **Behavior change:** `load_overrides(gdb, site, spec)` with no map_type now
  returns only blank-MapType rows, not an all-map_types collapse. Every real
  caller passes its map_type. Covered by a WHERE-aware-mock behavioral test
  (two MapTypes, same LocationID, both survive across scoped calls) confirmed
  red against the pre-fix unscoped WHERE.

### Capability catalog honesty

`capabilities.py`'s discovery rows for both tools described phantom behavior.
Updated to state 5.2 is folded into `build-callouts`/`BuildCallouts` and 5.3 is
the override CRUD (list/lock/unlock/clear). `TOOLS`/`requires_arcpy` (the runtime
guard) are unchanged.

## Arcpy-free boundary (ADR-002)

- **arcpy-free + pytest-covered:** the `use_hull_collision` plumbing through
  `assemble_callouts`; `get_override`'s field-mapping, blank-map_type SQL, and
  apostrophe quoting (via mocked cursors); `_scope_where`/`_key_where` MapType
  scoping and the `load_overrides` no-collapse behavior (WHERE-aware mock); the
  get→save round-trip; every CLI subcommand's *wiring* (core mocked at its source
  module, guard patched) — verifies the CLI calls the core with the right args
  and shapes output, which is exactly the gap #161 reported.
- **arcpy-only + review-only (human runs in ArcGIS Pro):** the actual cursor
  I/O inside `get_override` / `save_override` / `clear_unlocked_overrides` /
  `generate_callout_features`, and the `.pyt` `BuildCallouts.execute` path. These
  are not unit-tested here and were not fake-tested; they are verified by reading
  and require a Pro smoke test.

## Consequences

- Both tools are reachable end-to-end; `.pyt` and CLI stay in sync on the hull
  flag.
- `get_override` + `save_override` is a read-modify-write with no transaction —
  acceptable for an interactive, single-user override edit. `# ponytail:` a
  concurrent editor could clobber; add row versioning only if that ever happens.
- Residual uncertainty is confined to the untestable arcpy layer: real GDB field
  names/types for `Env_CalloutPlacementOverrides` must match `_WRITE_FIELDS`, and
  the blank-vs-NULL map_type behavior should be confirmed against a real GDB.

## Related decisions

- [ADR-0020](0020-callout-placement-extend-assemble-callouts.md) — the
  fold-into-`assemble_callouts` decision this completes.
- [ADR-002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md).
