# ADR-0079: Close the canonical-read merge gate (ADR-0075 Step-2 prerequisite)

**Status:** Accepted

**Date:** 2026-07-10

**Parent:** [ADR-0075](0075-canonical-schema-expansion-step1.md)

## Context

ADR-0075 (EDD Step-1) widened `Env_AnalyticalResults` so one
`(SiteID, Matrix, LocationID, SampleID, SampleDate, AnalyteCanonicalName,
DepthIntervalText)` grain can legitimately hold multiple rows split by
`ResultFraction` (Total/Dissolved), `QCType` (QC-flagged rows), and
`MethodDilutionKey` (dilution reruns). It shipped the shared arcpy-free policy
helper `canonical_result_rows(rows, qa)` (drop QC rows; resolve each analyte
group to the preferred fraction), converted `build_current_event.py` as the
reference consumer, and **named ~11 analyte-pivoting consumers as a "merge
gate"** that had to be audited/converted before a real WQX (Step-2) import
could ship without silently double-counting fraction pairs or tallying QC rows.

Auditing the gate revealed the ADR-0075 list was both **incomplete and
imprecise**: a first pass keyed on the literal string `Env_AnalyticalResults`
under-identified consumers that receive rows via shared readers / passed-in
lists, and it named modules that read a *different* vocabulary entirely.

## Decision

**1. Record-aware adapter.** Add `canonical_records(records, qa)` to
`canonical_read.py` — an `asdict → canonical_result_rows → return the SAME
record objects in order` adapter — so consumers that hold `AnalyticalResultRecord`
dataclasses (from `read_records_csv`) convert in one line instead of a hand-rolled
`asdict` roundtrip repeated per site.

**2. A canonical consumer is defined by its VALUE/FLAG columns**, not by the
table name and not by the analyte column. The load-bearing columns are
`ResultNumeric`, `ExceedsScreeningLevel`, `IsNonDetect`, `QCType`,
`ResultFraction` (and `AnalyteCanonicalName`). `AnalyteName` exists in *both*
the canonical and the legacy vocabularies, so it does not distinguish them.

**3. Converted** (route raw result rows through the policy before any
analyte pivot/count/screen): `compare_events`, `history_report`,
`export_summary_tables`, `export_geojson`, `schedule_vs_actual`, `data_gaps`,
`export_summary`, `draft_plume_boundary`, `dashboard_data_mart`,
`event_changelog` — plus `build_current_event` (the ADR-0075 reference). For
`draft_plume_boundary` fraction resolution is load-bearing (a well exceeding
only on the non-preferred fraction must not seed a plume vertex).
`dashboard_data_mart` is arcpy-gated (`pragma: no cover`); it surfaces the
drop/resolve messages via the module logger. Every headless conversion has a
regression test in `tests/envmon/test_merge_gate_canonical.py`.

**4. Deliberately NOT converted (SPECIAL — must keep QC / all fractions):**
- `apply_screening` — a 1:1 restamp that writes the full system-of-record
  table back; dropping rows would delete QC/non-preferred rows from the
  persisted export (data loss). Policy: stamp truthfully everywhere,
  canonicalize where you *count*.
- `evaluate_rpd_qa` — RPD compares field duplicates whose result rows can carry
  `QCType="FIELD_DUP"`; dropping QC rows would silently starve it of pairs.
- `validate_database` — a per-row integrity validator that must see every raw
  row (QC and all fractions) to catch defects; canonicalizing would blind it.

**5. Out of this gate — the legacy field-name island.**
`build_exceedance_event`, `compliance_summary`, `max_result_dataset`,
`regulatory_table_builder`, `qc_sample_summary`, `report_appendix_builder`,
`soil_interval_selector`, `well_trend_charts`, `event_results_merger` pivot by
analyte but read the legacy report vocabulary (`AnalyteName` / `ResultValue` /
`ReportedUnits` / `ResultQualifier`), which no canonical/widened producer emits.
The widened grain cannot reach them through their current contract, so they are
out of scope here. **Failure signature if a canonical export is ever wired into
one:** it does *not* cleanly no-op — because `ResultValue` is absent every row
parses as non-detect, yielding a clean-looking but wrong "no exceedances"
report. This is a latent hazard the moment someone bridges the two vocabularies;
see Follow-ups.

## Consequences

- The canonical-read policy is applied at every point where the widened grain is
  pivoted/counted/screened, so a Step-2 WQX import cannot silently double-count
  Total/Dissolved pairs or tally QC rows through any current consumer.
- The policy is a no-op on today's/legacy data (empty or absent discriminators),
  so nothing changes until real fractions arrive.
- **Completeness evidence (the closure check):** every consumer of the
  value/flag columns (`ResultNumeric` / `ExceedsScreeningLevel` / `QCType`) in
  `autogis/` is accounted for in the classification above. That value-column
  sweep — not a table-name or analyte-name grep — is the check that catches
  contract-only consumers; it is what caught `event_changelog`.

## Follow-ups (Step-2 / Step-3 backlog — not done here)

1. `evaluate_rpd_qa`: two coupled defects to fix together — (a) `result_idx` is
   last-wins across `ResultFraction`, and (b) duplicate detection keys only on
   `SampleRecord.IsDuplicate==1`, which EDD-derived records never set (they carry
   `QCType="FIELD_DUP"` instead), so EDD field-dups find zero pairs today.
2. Legacy-field island: before any canonical→legacy bridge is built, add a
   header tripwire (hard-error when input carries `AnalyteCanonicalName`/`QCType`/
   `ResultNumeric` but lacks `ResultValue`) or migrate the tool's vocabulary +
   insert the policy. Do not wire a canonical export into an island tool without
   one of these.
3. `MethodDilutionKey` / `IsReportable` rerun disambiguation remains deferred to
   Step 3 (already noted in `canonical_read.py`).

## Related decisions

- [ADR-0075](0075-canonical-schema-expansion-step1.md) — canonical schema
  expansion Step 1, which opened this gate.
