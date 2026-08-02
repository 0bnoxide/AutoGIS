# ADR-0037: Real-data verification of H281-family screening levels and parser profile

**Status:** Accepted

**Date:** 2026-07-02

## Context

Two of README's `## Caveats` existed purely for lack of real data: the H281 parser
profile (`autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml`) was authored
from a written spec only (ADR-011), and `autogis/config/screening_levels/screening_levels.yaml`
shipped every value as `null`.

A user-supplied pair of real client workbooks — same H281-style table family, a
different real site (Holiday Stationstore #272 / Circle K Store 2746272, Havre, MT) —
made both addressable without ever needing the actual Glasgow file. The workbooks
themselves never entered the repo; only structural facts (sheet names, row/column
anchors, header label text) and public regulatory constants (the site's own Montana
DEQ Tier 1 RBSL table, and its citation) crossed over.

The question: how far can "verified against real data" be pushed without (a) the
literal Glasgow workbook, (b) copying client data into the repo, or (c) touching the
arcpy-gated GDB-import path (explicitly out of scope this round)?

## Decision

1. **Screening levels**: populate `screening_levels.yaml`'s `GW` section for the 12
   VPH/EPH fraction analytes with real values from a real, cited regulatory table
   (Montana DEQ, 2018 — Tier 1 Risk-Based Corrective Action Guidance for Petroleum
   Releases). TPH/TEH stay `value: null` — Montana sets no bulk criterion for those,
   only the fractions — with a source note distinguishing "confirmed not applicable"
   from "not yet sourced." This is the verification bar for a `_TODO` clearance under
   the existing tri-state contract: a real regulatory citation, cross-checked against
   a real workbook carrying the same table — not a full production import run.
2. **Parser profile**: do not clear `H281_Glasgow_DataTables.yaml`'s DRAFT status —
   the literal Glasgow workbook still hasn't been seen, and ADR-011's gate stays.
   Instead: correct its `_TODO`-marked row anchors where a real, structurally-identical
   workbook proves the spec's row spacing wrong (no blank row between the group-header
   and analyte-header rows), and ship two new, fully anchor-verified sibling profiles
   for the real site — `H272_Havre_GW_Elevation.yaml` (verified and dispatchable) and
   `H272_Havre_GW_Analytical.yaml` (verified, but not yet dispatchable — see below).
3. **Scope boundary**: do not add a new `SheetProfile.data_type` / `normalize_*_table`
   wrapper to make the analytical profile dispatchable, even though the real site's
   split-workbook layout (water level and analytical results in separate files,
   unlike Glasgow's single combined sheet) genuinely has no home in the current
   `GW_ANALYTICAL_AND_WATER_LEVEL` / `GW_WATER_LEVEL_ONLY` / `METALS` / `SOIL` / `IBI`
   set. That gap's only production caller is `import_to_gdb.py` (arcpy-gated), so
   there is no reachable, testable caller for the new code this round — document the
   gap in the profile's own banner instead of building unreachable scaffolding.

## Consequences

### Positive consequences

- Two caveats move from "no real data ever seen" to "verified against real data,
  with the exact scope of that verification stated in-file" — a stronger, more
  honest position than either leaving them null/DRAFT or overclaiming full
  verification.
- The real Montana DEQ RBSL table (public, cited) is now load-bearing config,
  reducing `manage-screening-levels` warnings from 71 to 47 with zero invented
  numbers.
- A concrete, previously-invisible gap (no data_type for GW-analytical-only sheets)
  is now documented where the next person doing GDB-import work on this site will
  find it, instead of being discovered mid-import.
- No client-confidential data (sample results, well IDs, dates) entered the repo at
  any point — confirmed by an envmon-spec-checker pass.

### Negative consequences

- `H272_Havre_GW_Analytical.yaml` is verified but inert — it cannot be run through
  any existing import path until someone builds the missing normalizer, which this
  ADR deliberately did not do.
- The H281_Glasgow_DataTables.yaml row-anchor corrections are inferred from a
  different site's file, not Glasgow's own — still a guess, just a better-informed
  one. The DRAFT banner says so explicitly.
- `H272_Havre_GW_Elevation.yaml` drops LNAPL-specific columns (depth to product,
  product thickness, corrected GWE) via `ignored_columns` rather than modeling them —
  a real domain choice (raw GWE vs. corrected GWE matters at LNAPL sites) flagged for
  human decision, not resolved.

## Alternatives considered

1. **Wait for the literal Glasgow workbook before touching anything:** rejected —
   leaves both caveats permanently blocked on an asset that may never arrive, when a
   same-template real file was available and usable within a strict data-handling
   boundary.
2. **Build the missing `GW_ANALYTICAL` normalizer now, since it's a ~15-line mirror
   of `normalize_metals_table`:** rejected on review (see PR) — its only caller is
   the arcpy-gated GDB-import path, so it would be untestable, unreachable
   scaffolding-for-later; YAGNI holds until GDB-import work for this site is actually
   in scope.
3. **Clear the H281_Glasgow DRAFT banner since the general layout is now
   cross-checked:** rejected — cross-checking against a different site's file is not
   the same as verifying the actual named workbook; ADR-011's gate is about that
   specific asset, not the table family in the abstract.

## Related decisions

- [ADR-011: H281 profile draft status and pre-production gate](0011-h281-profile-draft-status.md)
- [ADR-022: Unit-conversion gate for screening-level evaluation](0022-screening-unit-conversion-invariant.md)

## Issues/PRs

- Precedes: fix/inspector-chartsheet-crash (#122) — the chartsheet crash that
  motivated re-running Tool 1 against these same real files was found and fixed
  first, in the same investigation thread.
