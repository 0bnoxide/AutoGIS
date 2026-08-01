# ADR-0020: Callout placement optimization — extend assemble_callouts, add manage_callout_overrides module

**Status:** Accepted

**Date:** 2026-06-26

## Context

Wave 3 work includes Tool 5.2 (`OptimizeCalloutPlacement`) and Tool 5.3
(`ManageCalloutPlacementOverrides`). The initial design proposed a new
`optimize_callouts.py` orchestrator module.

Codebase review (2026-06-26) found that `build_figure_dataset.py:assemble_callouts`
already orchestrates the full placement pipeline — it imports and calls
`build_callout_rows`, `build_callout_geometry`, `place_callouts`, and handles a
Python-level overrides dict. A new `optimize_callouts.py` would replicate this
function nearly in full.

`Env_CalloutPlacementOverrides` has no GDB-table implementation anywhere in the
codebase. The existing `overrides` parameter of `assemble_callouts` accepts a plain
Python dict keyed by location ID.

## Decision

### Tool 5.2 — numpy_geom integration into assemble_callouts

Extend `assemble_callouts` in `build_figure_dataset.py` rather than adding a new
module:

- Add an optional `use_hull_collision: bool = False` parameter
- When True, call `convex_hull` from `autogis.core.common.numpy_geom` on rotated
  box corner arrays to produce accurate polygon bounds before scoring candidates
- When False (default), retain existing axis-aligned rect scoring — zero behavioral
  change for callers that don't opt in
- The numpy integration is additive and cannot break existing tests

No new `optimize_callouts.py` module is created.

### Tool 5.3 — new manage_callout_overrides.py

Create `autogis/core/envmon/manage_callout_overrides.py`:

- `CalloutOverride` dataclass: `callout_id`, `location_id`, `figure_spec_id`,
  `origin_x`, `origin_y`, `locked`, `notes`
- `load_overrides(gdb_path, site_id, figure_spec_id) → dict[str, dict]` — returns
  in the format `assemble_callouts` already expects for its `overrides` parameter
- `save_override(gdb_path, override: CalloutOverride) → None`
- `clear_unlocked_overrides(gdb_path, site_id, figure_spec_id) → int`
- arcpy used lazily (same pattern as `build_figure_dataset.py`)

The `Env_CalloutPlacementOverrides` table schema is defined here and added to the
GDB schema upgrade path (Tool 10.3, in-flight — coordinate with that branch).

### CLI

Two commands added to `autogis/adapters/cli.py` under the `envmon` group:
- `optimize-callouts` — reads event data, runs `assemble_callouts`, writes results
- `manage-callout-overrides` — subcommands: `list`, `lock`, `unlock`, `clear`

## Consequences

### Positive consequences

- No code duplication — `assemble_callouts` remains the single placement authority
- numpy_geom hull integration is isolated behind a flag; existing behavior unchanged
- `load_overrides` returns a dict already shaped for `assemble_callouts` — no adapter needed
- `manage_callout_overrides.py` is independently testable (mock the GDB calls)

### Negative consequences

- `build_figure_dataset.py` grows one more parameter (`use_hull_collision`) — minor
- `Env_CalloutPlacementOverrides` table schema must be coordinated with the in-flight
  GDB schema upgrade branch (Tool 10.3) to avoid conflicts

## Alternatives considered

1. **New optimize_callouts.py orchestrator:** Redundant with `assemble_callouts`.
   Creates two placement authorities that diverge over time. Rejected.

2. **Inline overrides management inside build_figure_dataset.py:** Would make that
   module responsible for GDB table management, mixing I/O concerns with assembly.
   Rejected in favor of a dedicated module.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  `manage_callout_overrides.py` must import arcpy lazily
- [ADR-015: npg vendoring pattern](0015-npg-vendoring-pattern.md) — numpy_geom
  convex_hull sourced from npg/ via the public wrapper
