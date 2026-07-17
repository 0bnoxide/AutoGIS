# EDD Step 3, Slice 2 — unique-key redesign + mining/epar4/NYSDEC dialects (design)

**Date:** 2026-07-12
**Status:** PR 2a section **superseded by ADR-0084** (see banner below); PR 2b
section (R1–R8) remains the approved, live design (user-approved in session;
slice 2 of the decomposed Step 3)
**Program:** Step 3 of the ADR-0075 lab analytical ingestion program. Slice 1 =
PR #229 / ADR-0082 (EQuIS WMRD + `Env_QCResults`). This slice opens with the
frozen-key redesign per **issue #230** — the recorded decision that the slice-2
spec leads with the key decision, since every additional EQuIS dialect
multiplies exposure to the same collision classes.
**Companion evidence:** `.superpowers/sdd/task-9-report.md` on branch
`spec/edd-step3-equis-wmrd` (real-file collision row values), ADR-0082 "Known
limitation" section.

> **⚠ SUPERSEDED IN PART — 2026-07-16.** This spec was written 2026-07-12 in a
> session that lost its remote connection before landing; while it sat
> unshipped, issue #230 was resolved on `main` by a different mechanism
> (PRs #234–#236, **ADR-0084**, 2026-07-15): the analytical method
> discriminator is folded into the per-reader `MethodDilutionKey` *value
> recipe* (the ADR-0075 §3 escape hatch) — the frozen key compositions were
> **not** widened, and ADR-0084 lists key-widening (this spec's K1/K2) as a
> rejected alternative. ADR-0084's post-merge revision further established
> (P1a/P1b) that **any within-file run-instance ordinal — including K2's
> value-tuple variant — is cohort-dependent and cannot satisfy cross-batch
> determinism**; the QC half of #230 is reopened as a known limitation pending
> a source-provided run identity or a DB-aware import strategy.
>
> Consequently the **"PR 2a decisions" section and the "Testing / 2a"
> paragraph below are superseded — do not implement them** (retained for the
> decision history; a partial implementation is archived on branch
> `spec/edd-step3-slice2-keys-dialects`). The **template facts, the
> "PR 2b decisions" (R1–R8), the 2b testing plan, and the deferred-slices
> record remain the live design** — none of them depend on the key redesign.
> One 2b-planning note: with the QC limitation open, dialect e2e fixtures must
> avoid QC rerun collisions (or expect the blocking `edd_key_collision`
> guard), per ADR-0084's fail-safe policy.

## Shape: one spec, two PRs

| PR | Content | Why split |
|---|---|---|
| **2a** | Unique-key redesign (analytical MethodID + QC RunInstance) | Small, high-value: real WMRD imports currently finalize ERROR on the within-file collision guard; 2a alone unblocks them |
| **2b** | `equis_reader` structural extensions + `mining.yaml` / `epar4.yaml` / `nysdec.yaml` | Larger reader+profile effort with no real filled EDD to verify against |

One new ADR covers the slice (number picked against origin/main **and open
PRs** at merge time — ADR-0083 is already claimed by the unmerged
`feat/report-template-system-163` branch).

## Template facts that drove the design (verified 2026-07-12)

Inspected the three blank templates + dictionaries in the client examples
folder (`Mining EDD Blank Template.xlsx` + `Mining EDD Description.xlsx` +
`MTDEQ_Mining-enum.xml`; `epar4_blank_edd.xlsx`;
`NYSDEC_v5_20260429_Blank_EDD_Template.xlsx` + description + valid-values
workbooks). Slice 2 is **not** the "YAML-only exercise" the slice-1 spec
hoped for:

- All three templates are **`.xlsx`** — the slice-1 reader is xlrd-only
  (legacy BIFF `.xls`).
- **NYSDEC v5** is the closest cousin: same Sample/TestResultQC/Batch trio
  (`Sample_v5` / `TestResultQC_v5` / `Batch_v5`), same lowercase EQuIS column
  vocabulary (66-col result sheet incl. `detect_flag`, qualifier trio,
  `qc_*` spike columns). Its `Batch_v5` composite adds `analysis_date` to the
  5 columns WMRD joins on.
- **epar4** splits Test and Result into `EPAR4_TST_v1` (30 cols: dilution,
  basis, prep, lab_name_code, lab_sample_id, …) + `EPAR4_RES_v1` (43 cols:
  analyte, result, flags, limits, `qc_*`), sharing a 7-column leading
  composite (`sys_sample_code, lab_anl_method_name, analysis_date,
  analysis_time, total_or_dissolved, column_number, test_type`). It has **no
  batch sheet** — `test_batch_type`/`test_batch_id` sit inline on the result
  sheet. It says `total_or_dissolved` where WMRD says `fraction`. Its `VI_*`
  sheets are slice 4.
- **Mining (MTDEQ)** is a two-sheet analytical shape (`LabCollection` sample
  sheet + `LabResult` 49-col result sheet) whose TitleCase headers mostly
  **casefold onto the EQuIS names** (`Detect_Flag` → `detect_flag`,
  `Interpreted_Qualifiers`, `Reportable_Result`, the `qc_*` columns are
  already lowercase). True renames: `Analytical_Method_ID`,
  `Sample_Fraction`, `Result_Value_Unit`, `Lower_Reporting_Limit`,
  `Lab_Name`, `Characteristic_ID`/`Characteristic_Name` (analyte),
  `Sample_ID`, `Station_ID`, `Parent_Sample_ID`, `Sample_Type`. Batch ids are
  inline (`Lab_Batch_ID`/`Batch_Type`); there is no `column_number`. Its
  `Location`/`FieldCollection`/`WellWaterLevel` sheets are out of scope.
- Templates mark the first header of each sheet with a leading `#`
  (documented as "not uploaded"); the real WMRD export carried plain headers.

## PR 2a decisions — the key redesign (issue #230)

- **K1 — `MethodID` becomes the 12th part of
  `UNIQUE_KEYS["Env_AnalyticalResults"]`.** Fixes the observed real-file
  collision (same analyte, same sample/date/fraction, two lab methods —
  second silently lost). No schema change: the column exists since
  SCHEMA_VERSION 2.2. **Additive-safe** because keys are never stored —
  `append_records_idempotent` recomputes them from live columns per import,
  and `_norm_key_part` collapses NULL/"" to the same part: pre-EDD legacy
  rows (NULL MethodID) re-key as `""` on both the GDB side and the fresh
  normalize side, so self-heal re-imports still dedup exactly. Rejected:
  folding method into `MethodDilutionKey` "for new imports only" — a
  format-conditional key recipe is precisely what ADR-0080's per-row
  determinism argument forbids.
- **K2 — `Env_QCResults` gains a `RunInstance` (SHORT, nullable) column,
  appended as the 10th key part.** SCHEMA_VERSION 2.3 → 2.4 (additive; the
  existing self-heal path appends the column). `normalize_qc_rows` groups its
  records by the current 9-part key; **singleton groups keep
  `RunInstance=NULL`** — so every existing GDB row re-keys identically
  (NULL → `""`, same `_norm_key_part` property as K1) — and collision groups
  are sorted by value tuple (`ResultRawText`, `ResultNumeric`,
  `PercentRecovery`; NULLs sort first via sentinel) and assigned NULL, 2,
  3, …. The value-tuple sort makes the ordinal deterministic across
  re-exports whose sheet row order differs; sheet row order is explicitly
  **not** the sort key. Rejected: value columns in the key (a corrected-value
  re-export would insert alongside the stale row instead of dedup-ing — a new
  silent-data bug); a value hash (same flaw, opaque).
- **K3 — true source duplicates import as instances + QA-WARN** (user
  decision). A collision group containing identical value tuples is a genuine
  duplicate in the deliverable; both rows import (ordinals by count) and a
  `qc_true_duplicate` WARN surfaces it for human review. The table faithfully
  mirrors the lab deliverable; nothing is silently edited.
- **K4 — `detect_within_file_key_collisions` stays, unrelaxed, as the
  blocking backstop.** Post-redesign it cannot fire on QC (ordinals
  disambiguate by construction) and fires on analytical only for a true
  analytical duplicate (identical sample/method/everything) — never observed;
  blocking ERROR remains the right conservative answer there, and the guard
  doc comment is updated to say so.
- **K5 — no `canonical_read` change.** Rerun grouping keys off
  `MethodDilutionKey`/`IsReportable` (ADR-0082 D9), not `UNIQUE_KEYS`;
  `RunInstance` is QC-table-only. Pinned by existing tests.
- **Acceptance:** re-run the real `B25030623` WMRD export → 243/243 and
  332/332 distinct keys, import finalizes PASS, the previously-lost
  second-method row and surrogate reruns all land. (Client file stays out of
  the repo; run recorded in the PR.)

## PR 2b decisions — reader extensions + dialect profiles

- **R1 — engine branch by extension.** `read_equis_xls` dispatches:
  `.xls` → xlrd (unchanged), `.xlsx` → openpyxl (existing dependency,
  read-only mode, lazy import). The openpyxl path normalizes cell text to the
  same contract as `_cell_text` (datetimes → `%m/%d/%Y %H:%M` / date-only
  form, int-valued floats without `.0`, everything else stripped str). The
  format id stays `equis_xls` (historical name; the profile key, not the
  extension, selects the reader).
- **R2 — header normalization at load:** casefold + strip one leading `#`.
  Casefolding maps Mining's TitleCase headers onto the EQuIS constants for
  free; `#` stripping makes blank-template-shaped exports readable. Both are
  no-ops for the real WMRD export (already-lowercase, plain headers) — pinned
  by the existing fixture tests. Profile `columns:` maps and `source_aliases`
  are written casefolded.
- **R3 — `source_aliases:` profile key** (new, optional,
  `dict[str, str]`): applied after R2, renames a dialect's outlier source
  columns onto the EQuIS canonical names **before** synthesis, so every
  `_COL_*`-driven rule (ND synthesis, qualifier precedence, dilution-key
  fold, limit routing, batch attach) works untouched. Mining:
  `analytical_method_id → lab_anl_method_name`, `sample_fraction → fraction`,
  `result_value_unit → result_unit`, `lower_reporting_limit →
  reporting_detection_limit`, `lab_batch_id → test_batch_id`, `batch_type →
  test_batch_type`, `lab_name → lab_name_code`. epar4: `total_or_dissolved →
  fraction`, `lab_prep_method_name → prep_method`. Renames of profile-mapped
  canonical fields (analyte = `characteristic_name`, cas_number =
  `characteristic_id`, sample_id, location_id, dates) do NOT need aliases —
  they resolve through the ordinary `columns:` map; `source_aliases` exists
  only for the reader's internal `_COL_*` synthesis inputs. Rejected: per-dialect
  `_COL_*` constant sets behind a `dialect:` knob (every future dialect
  becomes a reader edit; 80% duplication), routing Mining through
  `two_tab_xlsx` (duplicates the QC fork / ND synthesis / spike handling into
  a second reader — the D2 rejection re-confirmed).
- **R4 — optional `test_sheet:` profile key** (epar4's TST/RES split): when
  set, test-sheet rows are indexed by the 7-column shared composite
  (casefolded `test_type`, post-alias `fraction`) and merged under the result
  row (result columns win on collision — the existing join convention).
  Missing test-sheet entry → QA-WARN (`equis_missing_test`) + row imports
  with empty test-side fields (D10 fail-safe policy).
- **R5 — inline-batch fallback.** When `batch_sheet` is empty and the row
  carries `test_batch_type`/`test_batch_id` (natively or via aliases), the
  single per-row pair routes to `__equis_prep_batch` / `__equis_analysis_batch`
  by its type value (same Prep/Analysis vocabulary the batch sheet uses;
  unknown type → both empty + `equis_missing_batch`-style WARN). Covers
  Mining and epar4.
- **R6 — batch join composite extends with `analysis_date`** when both the
  batch sheet and result sheet carry the column (NYSDEC `Batch_v5`); WMRD's
  5-column join is byte-identical when the column is absent (pinned).
- **R7 — three DRAFT profiles, template-verified only.**
  `mining.yaml` (`sample_sheet: LabCollection`, `result_sheet: LabResult` —
  sheet names stay real-case; only *headers* are casefolded per R2),
  `epar4.yaml` (`EPAR4_FSample_v1`/`EPAR4_RES_v1` + `test_sheet:
  EPAR4_TST_v1`), `nysdec.yaml` (`Sample_v5`/`TestResultQC_v5`/`Batch_v5`).
  Vocabularies (`qc_sample_type`, `matrix_map`) extracted from
  `MTDEQ_Mining-enum.xml`, epar4's `rt_sample_type`/`rt_matrix`/`Enumerations`
  sheets, and the NYSDEC valid-values workbook. All three carry **DRAFT
  banners** (no real filled EDD exists — wqx.yaml precedent; do not remove
  until verified against a real deliverable). Every unmapped value still
  fails safe with a QA-WARN (ADR-0080/D10 policy).
- **R8 — zero CLI change.** `autogis import-edd --profile-path nysdec.yaml
  <file.xlsx> <gdb>` — dispatch entirely via `format: equis_xls`.

## Testing (arcpy-free)

**2a:** additive-safety pinning (NULL-collapse re-key equality for both K1
and K2 against synthetic "existing row" dicts), ordinal determinism under
row-order shuffle, K3 true-dup WARN with both rows imported and distinct
keys, schema-bump test (2.4, RunInstance in TABLE_SCHEMAS/UNIQUE_KEYS), and a
synthetic fixture reproducing **both** WMRD collision shapes (two-method
analytical pair; identical surrogate pair) passing the guard end-to-end.

**2b:** unit tests per structural extension (R1 xlsx engine incl. date/float
cell normalization, R2 casefold + `#` strip incl. WMRD no-op pinning, R3
alias application, R4 test-sheet join + miss path, R5 inline batch, R6
extended batch composite + WMRD 5-col pinning); one small committed `.xlsx`
fixture per dialect built by an openpyxl generator script under
`tests/fixtures/` (template headers + synthetic rows only — no client data,
no new dependency); per-dialect e2e: read → split → normalize both streams →
`compute_unique_key` distinctness on both tables.

## Explicitly deferred (recorded so later slices don't re-derive)

- sxsamp reader + BS1/BS2 QCType semantics; re-evaluate the D5
  dup-as-columns pivot there (slice 3, real data `B26052070.XLS`).
- VI paper mapping + `Env_VIBuildingSurveys`; epar4/NYSDEC `VI_*` sheets
  (slice 4 — VI confirmed on-roadmap).
- Mining `WellWaterLevel` sheet → `Env_WaterLevels` routing;
  `FieldCollection`/`Location` sheets; NYSDEC non-analytical sheets
  (WaterLevel_v5, SoilGas_v5, FieldResults_v5, …).
- `evaluate_rpd_qa` dual fix; legacy field-name island tripwire (ADR-0079
  follow-ups #1/#2).
- An analytical-table RunInstance (no observed need; K4's guard blocks the
  hypothetical true analytical dup loudly rather than absorbing it silently).
