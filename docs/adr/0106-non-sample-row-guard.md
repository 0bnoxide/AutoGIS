# ADR-0106: Skip non-sample rows (footnote/annotation) in the GW normalizers

**Status:** Accepted — bug fix surfaced by the issue #272 execute-body QA
campaign (Option-2 prototype) against the real H272 Havre workbooks.

**Date:** 2026-07-22

**Addresses:** Issue #272 (automated arcpy testing / real-data import gap);
closes the "NOT yet exercised: an actual import run against real data" gap in
`H272_Havre_GW_Elevation.yaml` and `H272_Havre_GW_Analytical.yaml`.

**Verification:** live import of both real H272 workbooks in the
`arcgispro-py3-autogis` env (throwaway scratch gdb); full arcpy-free suite green
(2413 passed). Details on issue #272 (comments 5054277827 + follow-up).

## Context

Real MDEQ groundwater report tables end with — and sometimes embed — rows that
are structurally shaped like data but carry **no measurement**:

- A `NOTES:` footnote/legend block whose label sits in the **ID column**. Being
  non-blank, the label *reset* the `consecutive_blank_ids:3` terminator in
  `ProfileWorkbookReader.iter_data_rows`, so the footnote row was yielded as a
  data row and its color-legend prose cells became records.
- Inline **event-marker** rows with a *real* well ID, a **blank** date, and a
  prose annotation in an analyte cell (H272 `GW Quality (2)`: `BOS 200 Pilot Test
  Injections Performed on October 23 and 24, 2025`). These sit **mid-block** with
  real data after them, so an end-detection terminator cannot address them.

Consequences on the real H272 data:
- Analytical: 2 bogus `Env_Samples` + 28 bogus `Env_AnalyticalResults`
  (`LocationID='NOTES:'`); a 66-char legend/annotation value exceeded
  `Env_AnalyticalResults.ResultRawText` **TEXT(64)** → `RuntimeError: Field
  length exceeded` on `insertRow`, aborting the whole import (default mode blocked
  it via 2 `invalid_sample_date` ERRORs; `allow_errors_override` reached the crash).
- Elevation: 1 bogus `Env_WaterLevels` row silently imported (no crash — the
  fields fit), inflating a real count of 827 to 828.

Both `# pragma: no cover` (arcpy insert) — invisible to the suite; only a real
import surfaced them. A trailing-colon end-detection heuristic was prototyped
first but rejected: it cannot touch the mid-block BOS rows, and widening
`ResultRawText` was rejected outright because it would convert the crash into
silently importing a well named `NOTES:` with a result of `"Purple = ..."`.

## Decision

Adopt one unifying invariant in the groundwater normalizers (`normalize_gw_table_2`
+ `normalize_matrix_table`, the single dispatch path for both water-level and
analytical sheets):

> A row with **no valid date AND no parseable result** is not a sample. Skip the
> whole row (emit no sample, no results, no water level) with a visible
> `skipped_non_sample_row` / `skipped_non_data_row` QA **warning**.

- **Analytical** (`normalize_matrix_table`): skip when `sample_date is None` and
  no analyte cell parses to a real result — i.e. every analyte cell's
  `parse_result_value(...).status_code` is `BLANK` or `UNPARSED` (numeric,
  non-detect, and recognized statuses NS/NM/NA/dry all count as real). The guard
  runs **before** the date-warning block so a non-sample row does not raise the
  blocking `invalid_sample_date` ERROR.
- **Water-level** (`normalize_gw_table_2`): skip a built `WaterLevelRecord` with
  no `EventDate`, no numeric MPE/DTW/GWE, and `MeasurementStatus == "UNKNOWN"`.

The invariant is inherently safe: any genuine row has a date **or** a numeric
result, so it survives. A real dateless-but-resultful row is kept (with the
existing `missing_sample_date` warning). The `consecutive_blank_ids:3` terminator
is unchanged; no field widths change.

## Consequences

- H272 (and same-family MDEQ reports) import end-to-end: elevation 827/827,
  analytical completes, zero `NOTES:`/annotation rows in any table, and the exact
  dropped rows (1 elevation + 5 analytical) are all confirmed footnotes/BOS
  markers — no real data lost.
- Dropped rows are surfaced as QA warnings, not silently discarded.
- Minor: for the rare dateless row, analyte cells are parsed twice (guard scan +
  main loop). Acceptable — dateless rows are rare.

## Alternatives rejected

- **Trailing-colon end-detection terminator** — a surface heuristic for one shape
  (`NOTES:`); cannot reach mid-block BOS annotation rows; fragile to label variants.
- **Widen `ResultRawText`** — masks the bug by importing garbage instead of crashing.

## Related decisions & out of scope

- **`GW Quality (2)` dropped from the H272 profile (user decision, 2026-07-22)** —
  it is a DRAFT variant annotated with BOS-200 pilot-injection results. Removing it
  from `H272_Havre_GW_Analytical.yaml` (this PR) also moots its BOS annotation rows
  and the cross-sheet dedup exposure below. Final analytical data lives on
  `GW Quality` only.
- **Resolved by issue #304:** the `Env_AnalyticalResults` idempotency key
  formerly used a bare `SourceCell` A1 ref (`"C9"`) with no sheet qualifier.
  `SourceSheet` now precedes `SourceCell` in the key, so row-aligned sibling
  sheets are distinct while same-sheet re-imports remain idempotent.
- The `IBIs` sheet (inorganic indicator params) is absent from the H272 analytical
  profile and is dropped with no sheet-coverage QA flag — user accepted this as a
  real-world durability datapoint (2026-07-22); left as-is.
- Parsed **values** are not ground-truth-verified; this closes the code-path +
  row-integrity gap only.
