# ADR-0075: Canonical envmon schema expansion — Step 1 frozen decisions

**Status:** Accepted

**Date:** 2026-07-09

**Amended:** 2026-07-24 by issue #304. `SourceSheet` now qualifies
`SourceCell`, widening the analytical idempotency key from 11 to 12
components. This is the narrow correction to the original freeze described
below; no other discriminator was added.

## Context

The canonical GDB schema (`Env_Samples` / `Env_AnalyticalResults`,
`autogis/core/envmon/gdb_schema.py`) cannot represent data present in real-world
lab-EDD formats (EPA WQX, Montana Mining, Montana WMRD/EQuIS, EPA Region 4,
NYSDEC v5, a proprietary flat PFAS export). Worse, the current
`Env_AnalyticalResults` dedup key — `SiteID, Matrix, LocationID, SampleID,
SampleDate, AnalyteCanonicalName, DepthIntervalText, SourceCell` — cannot
distinguish rows that legitimately share every one of those fields but differ
by **fraction** (WQX Total vs. Dissolved), **QC type** (field duplicate vs.
parent), or **method/dilution** (a diluted rerun). This already breaks on WQX
data, the very next format this program plans to ingest (Step 2): a WQX sample
with both a Total and a Dissolved result for the same analyte silently loses
one today.

`create_or_update_gdb_schema` is additive-only (never rename/retype/drop —
ADR-0018 precedent), so every field/table name and `UNIQUE_KEYS` composition
frozen here gets exactly one shot. A required pre-implementation paper mapping
— a column-by-column reconciliation of 5 of 6 cataloged real formats (NYSDEC
v5 deferred to Step 3 on read-volume) — was completed and is recorded in
[`2026-07-09-edd-paper-mapping-outcome.md`](../superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md),
which amends the original design in
[`2026-07-08-canonical-schema-expansion-design.md`](../superpowers/specs/2026-07-08-canonical-schema-expansion-design.md).
The user then set the Step-1 freeze boundary to **minimal**: freeze only what
Step 2 (WQX) needs; defer anything with no Step-1/Step-2 producer to Step 3,
where real EQuIS data verifies it (additive-only means a new table or a
nullable column carries zero rename/rekey risk). This ADR is the durable
record of that frozen scope — every later task's names and keys must match it
verbatim.

## Decision

1. **New `Env_AnalyticalResults` columns (12, all optional/nullable):**
   `ResultFraction`, `QCType`, `MethodDilutionKey`, `MethodID`, `MethodName`,
   `AnalysisDate`, `LimitType`, `LabName`, `PrepMethodID`, `PrepDate`,
   `ResultBasis`, `MethodSpeciation`. Text/code key parts default `""`, never
   `None`; dates default `None`.

2. **The source-qualified 12-component unique key:** `SiteID, Matrix,
   LocationID, SampleID, SampleDate, AnalyteCanonicalName,
   DepthIntervalText, SourceSheet, SourceCell, ResultFraction, QCType,
   MethodDilutionKey`.

   The original accepted decision froze an 11-component key:
   `SiteID, Matrix, LocationID, SampleID, SampleDate, AnalyteCanonicalName,
   DepthIntervalText, SourceCell, ResultFraction, QCType, MethodDilutionKey`.
   Issue #304 supersedes that freeze narrowly after live H272 evidence showed
   that a bare A1 reference is not a source identity: the same cell on a
   corrected sibling sheet collided across runs and the later result was
   silently dropped. Both production analytical normalizers already populate
   `SourceSheet`; the column already exists in stored GDB rows, so this changes
   key computation without a schema or `SCHEMA_VERSION` migration.
   Canonical-read then compares rows that share the same semantic grain,
   fraction, and `MethodDilutionKey` across source sheets. Exact duplicates
   collapse with INFO; conflicting payloads emit blocking ERROR and none reach
   canonical consumers. Sheet names do not encode correction precedence, so
   the policy never guesses which conflicting row is authoritative.

3. **`MethodDilutionKey` composite convention:** a deterministic load-time
   composite built by each reader from its format's run discriminators —
   Step-1/flat-profile composition is the mapped `dilution_factor` column
   verbatim; Step 2/WQX adds `StatisticalBaseCode` and folds `ResultBasis` when
   dual-reported; Step 3 extends with EQuIS `test_type`/`column_number`.
   **`ResultBasis` (wet/dry) is folded into this composite, NOT a 13th key
   component** (user decision, open-Q#5). Extending the per-reader *value
   recipe* later is safe — the frozen things are the key composition and
   column names, not the recipe.

4. **`Qualifier` = final/interpreted qualifier** where the format distinguishes
   lab vs. validator, else the lab qualifier (user decision, open-Q#4);
   `IsEstimated` derivation reads it. A separate `InterpretedQualifier` may be
   added later, additively.

5. **Limit-units policy:** convert detection/reporting limits to result units
   at load, QA-WARN on unconvertible mismatch; no `DetectionLimitUnits` column
   (deferrable additively — open-Q#6). Convention only in Step 1; first
   enforcing code is Step 2's WQX reader.

6. **`SCHEMA_VERSION` 2.1 → 2.2** covers exactly this frozen set, via the
   existing `upgrade_schema.py` / `Env_SchemaVersion` machinery — no new
   migration framework (ADR-0018 precedent).

7. **The three frozen reader-seam boundaries** (spec §8 + Read-side impact —
   documented explicitly so Step 3 doesn't change them):
   - The flat-row-dict list returned by `read_edd_file` is the **permanent
     reader contract**; `normalize_edd_rows` never changes for a new format —
     relational flattening happens inside per-dialect reader modules (readers
     may inject synthetic composed columns, e.g. a precomposed
     `MethodDilutionKey`, into row dicts).
   - **`LabEDDProfile` stays flat and 2-sheet-shaped permanently**; Step 3's
     richer draft-time model is a separate type that projects down to a flat
     profile at runtime.
   - **The canonical-read policy**: consumers of `Env_AnalyticalResults` must
     read through the shared canonical-read helper (QC-exclusion + fraction
     resolution); `build_current_event.py` is the reference implementation.
     Rerun disambiguation via `IsReportable` defers to Step 3.

8. **The Step-2 merge gate:** these ~11 analyte-pivoting consumers are NOT
   converted in Step 1 and MUST be audited/converted to the canonical-read
   helper before Step 2 ships a real WQX import: `dashboard_data_mart.py`,
   `export_summary.py`, `export_summary_tables.py`, `generate_event_report.py`,
   `compare_events.py`, `history_report.py`, `schedule_vs_actual.py`,
   `data_gaps.py`, `apply_screening.py`, `export_geojson.py`,
   `draft_plume_boundary.py`. (Safe interim: discriminators stay `""` until
   WQX data arrives.)

9. **Deferred to Step 3** (recorded so nobody re-derives them): `Env_QCResults`
   (full field list + proposed key live in the paper-mapping doc), VI fields /
   `Env_VIBuildingSurveys`, `CASNumber`, `QuantitationLimit`, `IsReportable`,
   EQuIS composite extension, NYSDEC.

10. `compute_unique_key()` extraction, `value_maps` generalization,
    `run_edd_import` schema-ensure fix, and `record_to_row` deletion as the
    accompanying code decisions.

## Consequences

### Positive consequences

- WQX Step 2 can ship its first real import without silently dropping
  Total/Dissolved fraction pairs or QC-flagged rows — the collision this ADR
  exists to close.
- Corrected or duplicate workbook sheets no longer collide merely because
  their results occupy the same A1 cell; same-sheet re-imports remain
  idempotent. Conflicting sibling-sheet values remain stored for provenance
  but are blocked from canonical consumers pending adjudication.
- Every name and key composition frozen here was verified against 5 real
  formats before being written down, so Step 2 and Step 3 build on a
  paper-mapped foundation instead of a first-pass guess.
- The additive-only migration model (ADR-0018) is preserved — no new
  migration framework, one `SCHEMA_VERSION` bump covers the whole set.
- Deferring `Env_QCResults`, VI fields, and EQuIS-only columns to Step 3 costs
  nothing: new tables and nullable columns carry zero rename/rekey risk under
  the additive-only model.

### Negative consequences

- The 12-component key remains closed to further widening. `SourceSheet` is
  the one evidence-backed correction to the original freeze; future run
  discriminators still fold into `MethodDilutionKey` or require a new table.
- The ~11 analyte-pivoting consumers named in decision 8 remain unconverted
  until Step 2's merge gate; until then they are only safe because
  discriminators stay `""`.

## Alternatives considered

- **Freeze the full original design (`Env_QCResults` + VI fields + EQuIS-only
  columns) now, in Step 1.** Rejected — none of those have a Step-1/Step-2
  producer, and the additive-only model means deferring them to Step 3 (where
  real EQuIS data verifies the field list) carries no rename risk, unlike the
  `Env_AnalyticalResults` key and column names that WQX will populate
  immediately.
- **Add `ResultBasis` as a 13th key component** instead of folding it into
  `MethodDilutionKey`. Rejected (user decision, open-Q#5) — the key is frozen
  permanently, and the rare dual-reported wet+dry pair is adequately
  disambiguated via the composite fold without widening the key further.
- **Keep bare `SourceCell` and fold sheet name into `MethodDilutionKey`.**
  Rejected by issue #304: sheet and cell together are the existing source
  locator, while `MethodDilutionKey` is reserved for analytical run identity.
  Qualifying the locator is deterministic across batches and does not require
  format-specific composition.
- **`Qualifier` = raw lab qualifier, add `InterpretedQualifier` now.** Rejected
  (user decision, open-Q#4) — `IsEstimated` derivation needs one authoritative
  qualifier picked now; `InterpretedQualifier` can be added additively later
  if a validated-data workflow needs it.
- **Add a `DetectionLimitUnits` column now.** Rejected (open-Q#6) — a
  convert-at-load + QA-WARN policy handles it without a schema change;
  deferrable additively if real data ever breaks the assumption.

## Related decisions

- [ADR-0018](0018-upgrade-gdb-schema-tool.md) — the additive-only
  migration model (`create_or_update_gdb_schema`, `upgrade_schema.py`,
  `Env_SchemaVersion`) this ADR's `SCHEMA_VERSION` 2.1 → 2.2 bump follows,
  with no new migration framework.
- `docs/superpowers/specs/2026-07-08-canonical-schema-expansion-design.md` —
  the original Step-1 design (schema changes, reader-seam boundaries,
  canonical-read policy, testing plan).
- `docs/superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md` — the
  6-format paper-mapping verification that amended the design to this
  minimal Step-1 freeze and resolved open-Q#3–6.
- [Issue #304](https://github.com/0bnoxide/AutoGIS/issues/304) — live
  cross-run data-loss evidence and the owner-filed decision to qualify
  `SourceCell` with `SourceSheet`.
