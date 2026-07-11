# ADR-0082: EDD Step 3 slice 1 — EQuIS WMRD import + Env_QCResults

**Status:** Accepted

**Date:** 2026-07-10

**Parents:** [ADR-0075](0075-canonical-schema-expansion-step1.md) (frozen schema/key/seam,
`Env_QCResults`/VI deferred here to Step 3), [ADR-0079](0079-close-canonical-read-merge-gate.md)
(canonical-read consumer gate, IsReportable-reruns follow-up #3 closed by this ADR),
[ADR-0080](0080-wqx-step2-import.md) (Step 2 — the `__format_*` synthesized-column pattern and
unconditional-fold determinism argument this ADR reuses). See also
[ADR-0081](0081-lab-edd-profile-drafter.md) (adjacent EDD-profile-drafting tooling; not a
dependency of this slice).

## Context

Step 3 as originally named (EQuIS dialects mining/wmrd/epar4/NYSDEC + `Env_QCResults` +
CASNumber/QuantitationLimit/IsReportable) is several subsystems. It was decomposed in-session
into 4 slices; this ADR covers **slice 1 only** — the WMRD dialect (the only EQuIS format with a
real filled EDD to verify against) plus the additive schema both it and future slices need.
Design spec (advisor-reviewed pre-implementation, 3 blockers caught before code):
`docs/superpowers/specs/2026-07-10-edd-step3-equis-wmrd-design.md` (decisions D1-D12); plan:
`docs/superpowers/plans/2026-07-10-edd-step3-equis-wmrd.md`. Companion:
`docs/superpowers/specs/2026-07-09-edd-paper-mapping-outcome.md` (finalized the `Env_QCResults`
field list; consumed verbatim, not re-derived).

Real-file verification target: `B25030623-MT-WMRD (EQUIS).XLS`, a legacy binary BIFF `.xls`
(OLE2 magic — openpyxl cannot open it) with three relational sheets (Sample_v1 44 samples,
TestResultQC_v1 575 result rows, Batch_v1 89 rows). Client data; never copied into the repo.

## Decision

1. **D1 — xlrd becomes a required dependency.** xlrd 2.x is pure-Python, ~100 KB, zero
   transitive deps, reads exactly legacy `.xls`. Lazy-imported inside `equis_reader.py` only, so
   the rest of the codebase doesn't pay for it. Rejected: an optional `[equis]` extra (worse UX
   on a core import path), forced `.xlsx` conversion (a permanent manual step on every lab
   deliverable).

2. **D2 — one parameterized family reader**, `equis_reader.py`, format id `equis_xls`. Knows the
   EQuIS v1 *shape* (sample sheet + result/QC sheet + batch sheet joined on composite keys);
   sheet names come from the profile's existing `sample_sheet`/`result_sheet` keys (the
   `two_tab_xlsx` precedent) plus one new `batch_sheet` key. Every field mapping stays in the
   standard `columns:` map pointing at real or synthesized `__equis_*` keys — the ADR-0080
   synthesized-column pattern reused, not reinvented. Rejected: per-dialect readers (known
   duplication — 3 more dialects already on the roadmap), a declarative join engine (the new
   abstraction layer ADR-0075 explicitly rejected), a new `equis:` profile section (the
   sheet-name keys already exist).

3. **D3 — QC rows ride the same read, then fork.** The reader tags flattened rows with
   `__equis_stream = "qc"` when the parent sample is `sample_source=LAB` (casefold) **or** the
   row is `result_type_code=SUR` (surrogate recoveries sit on field samples but are QC). QC
   routing is decided on the sample sheet. `run_edd_import` splits tagged rows before
   `normalize_edd_rows`, so the analytical path never sees QC rows and `read_edd_file`'s
   signature is unchanged.

4. **D4 — `Env_QCResults` ships the paper-mapping's 33-column list verbatim** (see Schema below)
   with a 9-part unique key. New `QCResultRecord` dataclass + `normalize_qc_rows(...)`; **no new
   writer** — the existing table-generic `append_records_idempotent(gdb, "Env_QCResults", ...)`
   seam covers it (dedup keys off `UNIQUE_KEYS[table_name]`, which gains the entry).

5. **D5 — one QC record per source row; NO wide-column pivot (reversal on real-file evidence).**
   The dictionary/paper-mapping sketch implied a dup-as-columns pivot (`qc_dup_*` becoming a
   second synthesized MSD/LCSD record). Verified against the real WMRD file 2026-07-10: MSD/LCSD
   are their **own samples with their own result rows**, and on those rows `qc_dup_*` merely
   echoes the row's own values (`qc_spike_recovery == qc_dup_spike_recovery` on every populated
   pair). A pivot would have double-counted every MSD/LCSD. Per-field rule instead:
   SpikeAmount/PercentRecovery/OriginalConcentration read the primary `qc_*` columns, falling
   back per-field to the `qc_dup_*` twin only when the primary is empty; RPD/RPDControlLimit land
   on the row they appear on. `qc_spike_status`/`qc_dup_spike_status`/`qc_rpd_status` are dropped
   (deterministically derivable from recovery vs. stored control limits — the paper mapping's own
   drop list). The dup-as-columns pivot is explicitly **re-evaluated at the sxsamp/mining slice**
   against formats that may genuinely report the dup only in columns — not assumed dead.

6. **D6 — ND synthesis from `detect_flag`.** `__equis_result = "ND"` when `detect_flag` is `N`
   (casefold), else `result_value`. Reuses ADR-0080's plain-ND lesson (`_RE_NONDETECT` has no
   exponent form; never synthesize `<limit` tokens). A `detect_flag=N` row whose `result_value`
   is populated keeps ND and QA-WARNs (`equis_detect_flag_conflict`) — flag wins, mirroring
   WQX's condition-wins rule (ADR-0080 decision 2).

7. **D7 — qualifier precedence (paper-mapping Q4, final/interpreted).** `__equis_qualifier` =
   first non-empty of `interpreted_qualifiers` → `validator_qualifiers` → `lab_qualifiers`.

8. **D8 — `MethodDilutionKey` fold, unconditional, per-row:**
   `"|".join(p for p in (dilution_factor, test_type, column_number, basis) if p)` after
   NA-normalization (a literal `NA` in `test_type`/`column_number`/`basis` counts as empty — WMRD
   uses `NA` as its null). Same determinism argument as ADR-0080 decision 4: the recipe is
   decided per-row, never per-file, so cross-batch reimport never mints a different key for the
   same physical row. `basis` additionally lands in `ResultBasis` as data (Step-1 convention).

9. **D9 — IsReportable consumer ships with the column.** `canonical_read`'s group resolution
   gains one step: within a group holding MethodDilutionKey-distinct reruns, prefer rows with
   `IsReportable == 1` when any exist; rows with NULL/absent flag (all pre-Step-3 imports) behave
   exactly as today. Closes the deferral noted in `canonical_read.py`'s docstring and
   **ADR-0079 follow-up #3**.

10. **D10 — fail-safe vocabularies (ADR-0080 policy, reused).** Unmapped QC sample type imports
    with the raw code as QCType + QA-WARN (`equis_unmapped_qc_type`) — never silently dropped or
    blanked. Missing Sample_v1 join → QA-WARN + skip row (`equis_missing_sample`). Missing
    Batch_v1 join → empty batch ids + QA-WARN (`equis_missing_batch`), row still imports. A
    field-dup (FD) row stays on the **analytical** stream (not QC) with `QCType=FIELD_DUP` set on
    the analytical row — it's a real environmental sample duplicate, not a lab-QC artifact.

11. **D11 — limit units convert-at-load** via `common/units.convert`, with a same-unit
    short-circuit (casefold; empty `detection_limit_unit` = result units) and keep-raw +
    `equis_limit_unit_mismatch` WARN on `UnitError` — identical policy to ADR-0080 decision 3. In
    the real WMRD file `detection_limit_unit == result_unit` on every row, so the short-circuit
    is the hot path; the conversion branch is exercised by synthetic fixtures.

12. **D12 — zero CLI change.** `autogis import-edd --profile-path wmrd.yaml <file.xls> <gdb>`.
    Format dispatch is entirely via `format: equis_xls` in the profile, exactly like `wqx_csv`.
    Verified by an end-to-end test that calls `read_edd_file` directly against the committed
    fixture — no CLI-dispatch code changed, so no CLI-level test was needed.

## Schema (`SCHEMA_VERSION` 2.2 → 2.3, all additive)

`Env_AnalyticalResults` gains three columns (after the Step-1 block):

| Column | Type | Source (WMRD) |
|---|---|---|
| CASNumber | TEXT 32 | `cas_rn` |
| QuantitationLimit | DOUBLE | `quantitation_limit` (converted to result units per D11) |
| IsReportable | SHORT | `reportable_result` Yes/No → 1/0; NULL when absent |

New `Env_QCResults` table (33 columns, the paper mapping's finalized list verbatim):
`ImportBatchID, SiteID, Matrix, PrepBatchID, AnalysisBatchID, QCType, SampleID, ParentSampleID,
LabSampleID, AnalyteName, AnalyteCanonicalName, CASNumber, MethodID, ResultFraction,
MethodDilutionKey, AnalysisDate, ResultRawText, ResultNumeric, Units, ReportingLimit,
DetectionLimit, Qualifier, IsNonDetect, SpikeAmount, OriginalConcentration, PercentRecovery,
RecoveryLowerLimit, RecoveryUpperLimit, RPD, RPDControlLimit, SourceWorkbook, SourceSheet,
SourceRow`.

`UNIQUE_KEYS["Env_QCResults"]` = `(SiteID, Matrix, AnalysisBatchID, SampleID, QCType,
AnalyteCanonicalName, ResultFraction, MethodID, MethodDilutionKey)`.

Migration: the existing `upgrade_schema` / `run_edd_import` self-heal path (PR #212) already
creates missing tables and appends missing columns — no new migration machinery needed.

## Build facts

- Real-file verification against `B25030623` reconciled exactly: 243 analytical rows / 332 QC
  rows imported. The file itself stays out of the repo per policy.
- Two real-file-driven fixes surfaced during verification (not anticipated by the spec): the
  Batch_v1 join casefolds `test_type` on **both** sides of the join (the sample and batch sheets
  disagree on case in the real export); `_DATE_FORMATS` gained `"%m/%d/%Y %H:%M"` and
  `"%m/%d/%Y %H:%M:%S"`, appended **last** in the format list (ordering-safe — existing formats
  still try first, so no prior-format row can be reparsed differently).
- A synthetic `.xls` fixture (~20 rows, 3 sheets, one junk column) plus its generator script are
  committed under `tests/fixtures/` for the end-to-end test. `xlwt` (used only by the offline
  generator) does **not** become a project dependency — only `xlrd` (D1) does.

## Known limitation (recorded, not fixed in this slice)

Real-file verification surfaced key collisions that are a **silent dedup data-loss risk**, out of
scope for slice 1:

- **Analytical:** 242 of 243 rows are key-distinct. The one collision is the same analyte
  reported under two different lab methods for the same sample/date/fraction — `MethodID` is not
  a component of the frozen ADR-0075 11-part key, so the second method's row silently loses to
  idempotent dedup against the first.
- **QC:** 328 of 332 rows are key-distinct. Surrogate rows need a run-instance discriminator
  (multiple surrogate recoveries per sample/method/fraction collapse onto the same
  `Env_QCResults` key); one pair is a genuine source duplicate (not a key defect).

Fixing this means changing a **frozen, cross-format** key (`UNIQUE_KEYS` for
`Env_AnalyticalResults` and/or `Env_QCResults`), which is explicitly an ADR-level decision outside
this slice's scope — recorded here as a known limitation and follow-up, not silently absorbed
into WMRD-specific code.

## Slice map (deferred, recorded so later slices don't re-derive)

| Slice | Content |
|---|---|
| 2 | mining / epar4 profiles (template-verified only); NYSDEC (dictionary extraction first, then profile) |
| 3 | sxsamp reader (single-sheet commercial format, real data `B26052070.XLS`); re-evaluate the D5 dup-as-columns pivot here |
| 4 | VI paper mapping + `Env_VIBuildingSurveys` (user confirmed VI stays on the roadmap) |
| — | `evaluate_rpd_qa` dual fix (ADR-0079 follow-up #1) |
| — | legacy field-name island tripwire (ADR-0079 follow-up #2) |

## Consequences

- WMRD lab-QC results (blanks, LCS/LCSD, MS/MSD, surrogates, CCV/ICV, ...) now import alongside
  field results with full provenance, closing the `Env_QCResults` gap ADR-0075 deferred to Step 3.
- `canonical_read` reruns correctly prefer the reportable result when a sample carries multiple
  MethodDilutionKey-distinct runs and the source format flags reportability — closes ADR-0079
  follow-up #3.
- The known-limitation key collisions mean a WMRD reimport today can silently drop a same-key
  second method or surrogate run; until the follow-up ADR lands, anyone consuming WMRD data
  cross-checks row counts against the source file for high-stakes reports.
- `wmrd.yaml`'s vocabularies (`qc_sample_type`, `matrix_map`) are verified against **one** real
  Energy Labs WMRD export — marked verified-against-one-export (not DRAFT) with single-lab
  provenance noted; every unmapped value still fails safe with a QA-WARN.

## Alternatives considered

- **Dup-as-columns pivot for MSD/LCSD** (D5) — rejected on real-file evidence: would double-count
  every MSD/LCSD, since those are already independent rows with independently-populated `qc_dup_*`
  echoes, not the sole carrier of a dup's data.
- **Per-dialect readers** (D2) — rejected: known duplication across 4 EQuIS dialects on the
  roadmap; the shape (sample+result+batch join) is genuinely shared.
- **Fixing the frozen key to absorb MethodID/run-instance** in this slice — rejected: a
  cross-format key change is an ADR-level decision with reimport/dedup consequences beyond WMRD;
  recorded as a follow-up instead of an under-scoped in-slice patch.

## Related decisions

- [ADR-0075](0075-canonical-schema-expansion-step1.md) — Step-1 frozen schema/key/seam this slice
  extends additively; deferred `Env_QCResults`/VI to Step 3.
- [ADR-0079](0079-close-canonical-read-merge-gate.md) — canonical-read consumer gate; follow-up #3
  (IsReportable-aware rerun resolution) closed by D9.
- [ADR-0080](0080-wqx-step2-import.md) — Step 2; the synthesized-`__format_*`-column pattern and
  unconditional-fold determinism argument this ADR reuses for D2/D8.
- [ADR-0081](0081-lab-edd-profile-drafter.md) — adjacent EDD-profile-drafting tooling; not a
  dependency of this slice, cross-referenced for context.
