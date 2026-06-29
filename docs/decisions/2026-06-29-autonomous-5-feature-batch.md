# Autonomous 5-Feature Batch — Decision Log

**Date:** 2026-06-29
**Branch:** `feat/headless-envmon-batch-2026-06-28`
**Context:** User requested 5 features implemented autonomously, "use best
judgment and log those decisions accordingly." User unavailable for questions.

This file records each judgment call made during the run: what was chosen, what
was rejected, and why. One section per feature plus cross-cutting decisions.

---

## Cross-cutting decisions

### D0.1 — Feature selection criteria
**Chosen:** Implement 5 headless (arcpy-free) tools that already have an
**Approved** design spec under `docs/superpowers/specs/` but **no implementation
module** in `autogis/core/envmon/`.
**Why:** Headless tools are fully testable in the existing arcpy-free pytest
suite (clean 698-test baseline). Approved specs mean requirements are settled, so
no clarifying questions are needed — appropriate for an autonomous run. Picking
already-spec'd gaps avoids inventing scope.
**Rejected:** Tackling LOCAL (arcpy) tools (2–8) — can't be exercised headless,
so I couldn't verify them. Also rejected the open Guard KeyError bug (#62) and
Lab EDD Importer rework — those are fixes/reworks, not the "5 features" asked for
(though export-lab-request is adjacent and chosen).

### D0.2 — Selected features
1. `build-monitoring-report-appendix` (Tool 9.2) — multi-sheet Excel appendix
2. `list-available-env-tools` (Tool 10.1) — CLI tool registry/discoverability
3. `build-analytical-exceedance-event` (Tool 4.4) — exceedance selectors + tiers
4. `export-lab-request` (Tool 2.11) — lab analytical request workbook
5. `build-dashboard-data-mart` — denormalized `Dash_*` mart tables

### D0.3 — Record / I/O convention
**Chosen:** Follow the *lightweight* convention used by the most recent headless
batch on this branch (`max_result_dataset.py`, `compliance_summary.py`,
`qc_sample_summary.py`): a small `@dataclass` with snake_case fields, input as
raw `csv.DictReader` dict rows (keys `LocationID`, `AnalyteName`, `ResultValue`,
`ResultQualifier`, `ReportedUnits`, `SampleDate`, `SampleID`), screening levels
as a `{analyte: level}` dict, and a module-local CSV/Excel writer.
**Why:** Consistency with the sibling tools committed on this very branch matters
more than matching the older canonical `AnalyticalResultRecord`/`records_csv`
path. New CLI commands and tests will look identical to the existing batch.
**Rejected:** The canonical `gdb_schema.AnalyticalResultRecord` + `records_csv`
round-trip — heavier, and the new analytical tools don't need GDB field-name
fidelity.

### D0.4 — Sequencing for durability
One feature at a time: tests first (TDD), then module, then CLI wiring, then run
the **full** suite, then commit. Committed features survive a session
interruption; half-built ones don't.

---
<!-- per-feature sections appended as each feature lands -->

## Feature 1 — build-monitoring-report-appendix (Tool 9.2)

**Status:** DONE — `report_appendix_builder.py` + `build-report-appendix` CLI +
9 tests (8 unit + 1 CLI smoke). Full suite 707 passed.

### D1.1 — Sheet layout orientation
**Chosen:** rows = analytes, columns = (well × event-date), per the spec's
explicit "Sheet Layout" / Public-API docstring ("rows = analytes, cols = wells
then date sub-cols").
**Why:** The spec's prose "Approach" bullet ("Columns: Well ID, then one date
column per event") and its concrete layout table agree once you read the table:
each well heads a block of its event-date columns. Followed the concrete table.

### D1.2 — Summary rows are per-column
**Chosen:** "Detects" (d/n frequency) and "Max" summary rows computed **per
(well,date) column**, not per well aggregate.
**Why:** The spec's layout shows six summary values for six well-date columns
(`1/2 2/2 1/2 0/2 ...`), i.e. one per column. Detection frequency = detected
analytes / analytes-present in that column.

### D1.3 — Non-detect / detection / exceedance classification
**Chosen:** ND = qualifier in {ND,U,BDL} OR non-numeric ResultValue. Detected =
numeric & not ND. Exceedance = numeric value > screening level (strict `>`).
Yellow fill = detected ≤ SL; red = detected > SL; ND = no fill.
**Why:** Matches sibling `max_result_dataset.py` ND set and the spec's
conditional-format rules. Strict `>` so a value exactly at the SL is not flagged
an exceedance (conservative; the regulatory convention here treats SL as the
"not-to-exceed" ceiling — equal is compliant). Logged because `>=` is a
defensible alternative the reviewer may prefer.
