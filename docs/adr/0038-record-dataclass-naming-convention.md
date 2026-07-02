# ADR-0038: Record-dataclass field naming — PascalCase iff GDB-mirroring

**Status:** Accepted

**Date:** 2026-07-02

## Context

Two field-naming conventions coexist across `envmon` record dataclasses, and the
rule separating them was never written down:

- **GDB-mirroring records** use PascalCase fields matching GDB columns 1:1 —
  `AnalyticalResultRecord` et al. (`gdb_schema.py:345-389`). This 1:1 match is what
  makes `records_csv` round-trips produce deliverable-ready column names without a
  translation step.
- **Internal records** use snake_case with an explicit mapping to GDB column names
  where one is needed — `QARecord` (`common/qa.py:29-57`), whose `as_gdb_row()`
  method does the snake_case → PascalCase translation explicitly.

Without a documented rule, batches guess, and guess inconsistently: `sampling_plan.py`'s
`PlannedSample` uses PascalCase (`SiteID`, `EventDate`, `LocationID`, ...) despite never
touching a GDB, while its same-PR sibling `field_lab_reconciler.py`'s `FieldSampleRecord`
uses snake_case (`sample_id`, `location_id`, ...) for an equally GDB-free record. Neither
choice is wrong in isolation, but the inconsistency means a reader can't predict a new
dataclass's casing from its purpose, and `git grep`-based refactors that assume one
casing miss the other. (Originally flagged as finding M4 in the independent
architecture review, `docs/reviews/fable-architecture-review.md`, merged in #103.)

## Decision

**PascalCase iff the dataclass mirrors a GDB table or a deliverable CSV schema whose
column names are contractually fixed (client-facing exports, lab EDD formats, etc.).
snake_case otherwise.**

Concretely:

- If a dataclass's fields are read from or written to an ArcGIS geodatabase table via
  `gdb_schema.py`, or its `records_csv` output is a deliverable handed to a client/lab
  with fixed column names, use PascalCase field names that match those columns
  verbatim. This keeps `common/records_csv.py`'s generic dataclass↔CSV round-tripper
  from needing a translation layer for the common case.
- Every other record dataclass (intermediate computation results, internal
  reconciliation records, anything without an external fixed-schema consumer) uses
  ordinary Python snake_case. If it later needs to produce a GDB-shaped row, add an
  explicit `as_gdb_row()`-style method (per `QARecord`) rather than renaming the
  dataclass's own fields.

This is a documentation-only decision — it does not require renaming any existing
dataclass. `sampling_plan.PlannedSample` is retroactively out of convention (it never
touches a GDB) but is left as-is; fixing it would be a breaking rename for CSV
consumers of a shipped tool for no functional gain. New dataclasses should follow the
rule above.

## Consequences

### Positive consequences

- The next batch has a rule to look up instead of guessing from the nearest example
  (which might itself be the wrong example, as `sampling_plan.py` demonstrates).
- `common/records_csv.py` stays a true zero-config round-tripper for the GDB-mirroring
  case, which is the case it was built for.

### Negative consequences

- One pre-existing inconsistency (`PlannedSample`) remains uncorrected. Acceptable:
  correctness and shipped-tool stability outrank retroactive cosmetic consistency.

## Alternatives considered

1. **Force one casing convention everywhere:** Would require either adding a
   translation layer to every GDB-mirroring dataclass (defeating the point of
   `records_csv`'s zero-config round-trip) or accepting non-Pythonic PascalCase on
   purely internal records. Rejected.
2. **Rename `PlannedSample` to snake_case now:** Breaks any existing CSV consumer of
   `create-sampling-plan`'s output for a purely cosmetic fix. Rejected; not worth the
   compatibility break for a shipped headless tool.

## Related decisions

- `docs/reviews/fable-architecture-review.md` — finding M4, source of this ADR.
- `autogis/core/common/records_csv.py` — the generic round-tripper this convention
  keeps zero-config for the common case.
