# ADR-XXXX: Consolidate the hand-maintained tool registries behind one table (PROPOSAL)

**Status:** Proposed (not executed — see Decision)

**Date:** 2026-07-06

> Numbering: placeholder `XXXX` on purpose; assign the next free number at
> merge time after checking every open PR's files (ADR-0034/0061/0062
> collision pattern).

## Context

A tool is enumerated by hand in up to five places (finding H3,
`docs/reviews/fable-architecture-review.md`, PR #103):

1. the click command tree (`autogis/adapters/cli.py`) — ground truth;
2. the guard registry `capabilities.TOOLS` (84 entries, drives
   `requires_arcpy`/`_guard`);
3. the discovery registry `capabilities._REGISTRY_SEED` (95 entries, drives
   `envmon list-tools`) — overlapping metadata, different shape, LOCAL-ness
   duplicated as a display string;
4. the `.pyt` toolbox (`Toolbox.tools`, 14 classes) — membership is policy
   (ADR-0006: tools 2-8 .pyt-first; ADR-0039: gen-2 LOCAL tools deliberately
   have no entry), plus free-floating class names inside CLI redirect
   message strings;
5. the GUI reachability policy (`gui/reachability.py::UNREACHABLE`,
   hand-curated per ADR-0062). The GUI introspector itself
   (`gui/introspect.py`) derives from the live click tree and cannot drift.

An audit on 2026-07-06 (this branch) found **zero live enumeration drift**:
the 2026-07-01 guards (`test_capabilities.py`, #98/#106) stopped the active
"every batch forgets list-tools" class. The remaining unguarded directions
(ghost entries after rename/removal, LOCAL-without-guard, TOOLS/seed runtime
disagreement, unregistered `.pyt` classes, redirect strings naming
nonexistent `.pyt` tools) are now locked by
`tests/test_tool_registry_parity.py`. Root cause remains: **no single source
of truth** — five surfaces, each updated by hand.

## Decision (proposed)

Merge registries 2 and 3 into one table and derive the rest:

- Extend `ToolCapability` with `runtime_class: Runtime` (the enum, replacing
  the seed's display string as authority) and `pyt_tool: str | None` (the
  registered `.pyt` class name, or None — carrying H2's "one boolean in the
  registry" recommendation, upgraded to the class name so redirect messages
  and reachability reasons can be generated instead of hand-written).
- `TOOLS` / `requires_arcpy()` become views over that table (kept as
  functions with identical signatures; no caller changes).
- `envmon list-tools` keeps reading the same table (already does via
  `TOOL_REGISTRY`).
- `gui/reachability.UNREACHABLE` *reasons* stay hand-curated policy
  (ADR-0062), but each entry's tool must exist in the table (already
  test-enforced).

Out of scope: the click tree stays ground truth for command existence and
parameters; the `.pyt` stays a hand-maintained Esri artifact (only its
*references* are checked).

## Why not executed now

The parity tests deliver the drift protection at ~1/20th the diff. The
consolidation touches `capabilities.py`, `cli.py` (redirect strings),
`tool_registry.py`, and every test that imports `TOOLS`/`_REGISTRY_SEED`
(~10 files) for zero user-visible behavior change. That is a deliberate
refactor batch needing its own review — not a drive-by. If/when executed,
`tests/test_tool_registry_parity.py` is the safety net: several of its
tests (ghost keys, runtime agreement) become tautological afterwards and
should be pruned in the same PR.

## Consequences

- Until executed: five surfaces remain, but every known drift direction is
  CI-red within one test run.
- If executed: adding a tool means one table row + the click command; the
  guard, list-tools, and (partially) reachability derive from it.
