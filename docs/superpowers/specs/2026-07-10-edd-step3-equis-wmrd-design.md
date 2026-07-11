# EDD Step 3, Slice 1 — EQuIS reader + WMRD profile + QC schema (design)

**Date:** 2026-07-10
**Status:** approved design (user-approved in session; slice 1 of the decomposed Step 3)
**Program:** Step 3 of the ADR-0075 lab analytical ingestion program (Step 1 = PR #212,
merge gate = PR #223 / ADR-0079, Step 2 = PR #226 / ADR-0080).
**Companion:** `2026-07-09-edd-paper-mapping-outcome.md` — the paper mapping that
finalized the Env_QCResults field list and the Step-3 additions. This spec consumes
those lists verbatim; it does not re-derive them.

## Why a slice, and which one

Step 3 as named (EQuIS dialects mining/wmrd/epar4/NYSDEC + Env_QCResults +
CASNumber/QuantitationLimit/IsReportable) is several subsystems. Decomposition
decided in-session:

| Slice | Content | Status |
|---|---|---|
| **1 (this spec)** | Additive schema (Env_QCResults + 3 AnalyticalResults columns) + `equis_reader.py` + WMRD profile + canonical_read IsReportable resolution | build now |
| 2 | mining / epar4 profiles (template-verified only), NYSDEC (dictionary extraction first, then profile) | later |
| 3 | sxsamp reader (single-sheet commercial format, real data `B26052070.XLS`) | later |
| 4 | VI paper mapping + `Env_VIBuildingSurveys` (user confirmed VI **stays on the roadmap**) | later |
| — | `evaluate_rpd_qa` dual fix (ADR-0079 follow-up #1) | independent bugfix PR |
| — | legacy field-name island tripwire (ADR-0079 follow-up #2) | later |

WMRD goes first because it is the **only EQuIS dialect with a real filled EDD** to
verify against (`B25030623-MT-WMRD (EQUIS).XLS`: Sample_v1 44 samples,
TestResultQC_v1 575 result rows, Batch_v1 89 rows). Mining/epar4/NYSDEC have only
blank templates + dictionaries; building their profiles on a proven reader is a
YAML-only exercise later.

### Real-file facts that drove the design (verified 2026-07-10 against B25030623)

- Sample_v1 mixes field samples (`sample_source=Field`, `sample_type_code=N`, 10)
  with lab-QC samples (`sample_source=LAB`, 34: QC-LCS/LCSD/LMS/LMSD/LB/LD/LCCV/
  LICV/PDS/LIFC, plus CRA and SRM). **QC routing is decided on the sample sheet.**
- Exception: `result_type_code=SUR` rows (surrogate recoveries, units
  `% recovery`, 50 rows) sit on **field** samples and are QC anyway.
- Every TestResultQC_v1 `#sys_sample_code` resolves in Sample_v1 (join complete in
  the real file; missing-sample is still a guarded path).
- WMRD carries all three limits as plain columns (`method_detection_limit`,
  `reporting_detection_limit`, `quantitation_limit`) — no WQX-style LimitType
  routing needed. `reportable_result` = Yes/No maps directly to IsReportable.
- Batch_v1 joins on the composite (sys_sample_code, lab_anl_method_name, fraction,
  column_number, test_type); the real export contains a junk `Expr1002` column —
  the reader must address columns **by header name** and ignore unknown columns.
- Both real EDDs are legacy binary **BIFF .xls** (OLE2 magic verified) — openpyxl
  cannot open them.

## Decisions

- **D1 — xlrd becomes a required dependency** (user-selected). xlrd 2.x is
  pure-Python, ~100 KB, zero transitive deps, reads exactly legacy .xls.
  Lazy-imported inside `equis_reader.py` only, so nothing else pays for it.
  Rejected: optional `[equis]` extra (worse UX on a core import path), forced
  .xlsx conversion (permanent manual step on every lab deliverable).
- **D2 — one parameterized family reader**, `equis_reader.py`, format id
  `equis_xls`. The reader knows the EQuIS v1 *shape* (sample sheet + result/QC
  sheet + batch sheet joined on composite keys); every sheet name comes from a new
  small `equis:` profile section and every field mapping stays in the standard
  `columns:` map pointing at real or synthesized `__equis_*` keys — the ADR-0080
  synthesized-columns pattern. Rejected: per-dialect readers (known duplication —
  3 more dialects are already on the roadmap), declarative join engine (the "new
  abstraction layer" ADR-0075 explicitly rejected).
- **D3 — QC rows ride the same read, then fork.** The reader tags flattened rows
  with `__equis_stream` = `"qc"` when the parent sample is `sample_source=LAB`
  (casefold) **or** the row is `result_type_code=SUR`; `run_edd_import` splits the
  tagged rows before `normalize_edd_rows`, so the analytical path never sees QC
  rows and `read_edd_file`'s signature is unchanged.
- **D4 — Env_QCResults ships the paper-mapping list verbatim** (~30 columns, see
  Schema below) with the proposed 9-part unique key. New `QCResultRecord`
  dataclass + `normalize_qc_rows(rows, profile, qa)` + `write_qc_results_to_gdb`
  (arcpy seam, `pragma: no cover`, doc-verified per ADR-0077).
- **D5 — wide-column QC pivot.** A QC row with populated `qc_dup_*` columns emits
  a second QCResultRecord (QCType MSD when base is MS, LCSD when base is LCS)
  reusing the `qc_dup_*` spike/recovery values; `qc_rpd`/`qc_rpd_cl` land on both
  rows. `qc_spike_status`/`qc_dup_spike_status`/`qc_rpd_status` are **dropped**
  (deterministically derivable from recovery vs stored control limits — paper
  mapping's own drop list).
- **D6 — ND synthesis from detect_flag.** `__equis_result` = `"ND"` when
  `detect_flag` is `N` (casefold), else `result_value`. Reuses ADR-0080's plain-ND
  lesson (`_RE_NONDETECT` has no exponent form; never synthesize `<limit`
  tokens). A `detect_flag=N` row whose result_value is populated keeps ND and
  QA-WARNs (`equis_detect_flag_conflict`) — flag wins, mirroring WQX's
  condition-wins rule.
- **D7 — qualifier convention (paper-mapping Q4, final/interpreted).**
  `__equis_qualifier` = first non-empty of `interpreted_qualifiers` →
  `validator_qualifiers` → `lab_qualifiers`.
- **D8 — MethodDilutionKey fold, unconditional, per-row:**
  `"|".join(p for p in (dilution_factor, test_type, column_number, basis) if p)`
  after NA-normalization (a literal `NA` in test_type/column_number/basis counts
  as empty — WMRD uses `NA` as its null). Same determinism argument as ADR-0080:
  recipe decided per-row, never per-file. `basis` additionally lands in
  `ResultBasis` as data (Step-1 convention).
- **D9 — IsReportable consumer ships with the column.** `canonical_read`'s group
  resolution gains one step: within a group holding MethodDilutionKey-distinct
  reruns, prefer rows with `IsReportable == 1` when any exist; rows with NULL /
  absent flag (all pre-Step-3 imports) behave exactly as today. Closes the
  deferral in `canonical_read.py`'s docstring and ADR-0079 follow-up #3.
- **D10 — fail-safe vocabularies, ADR-0080 policy.** Unmapped QC sample type →
  import with the raw code as QCType + QA-WARN (`equis_unmapped_qc_type`); never
  silently drop or silently blank. Missing Sample_v1 join → QA-WARN + skip row
  (`equis_missing_sample`). Missing Batch_v1 join → empty batch ids + QA-WARN
  (`equis_missing_batch`), row still imports.
- **D11 — limit units convert-at-load** via `common/units.convert`, same-unit
  short-circuit (casefold; empty `detection_limit_unit` = result units), keep-raw
  + `equis_limit_unit_mismatch` WARN on UnitError — identical policy to ADR-0080.
  In the real WMRD file `detection_limit_unit == result_unit` on every row, so
  the short-circuit is the hot path.
- **D12 — zero CLI change.** `autogis import-edd --profile-path wmrd.yaml
  <file.xls> <gdb>`. Format dispatch via `format: equis_xls` in the profile,
  exactly like `wqx_csv`.

## Schema (SCHEMA_VERSION 2.2 → 2.3, all additive)

`Env_AnalyticalResults` — three appended columns (after the Step-1 block in
`gdb_schema.py`):

| Column | Type | Source (WMRD) |
|---|---|---|
| CASNumber | TEXT 32 | cas_rn |
| QuantitationLimit | DOUBLE | quantitation_limit (converted to result units per D11) |
| IsReportable | SHORT | reportable_result Yes/No → 1/0; NULL when absent |

New `Env_QCResults` table — the paper-mapping's finalized 33-column list verbatim:
ImportBatchID (T64), SiteID (T32), Matrix (T16), PrepBatchID (T64),
AnalysisBatchID (T64), QCType (T32), SampleID (T64), ParentSampleID (T64),
LabSampleID (T64), AnalyteName (T128), AnalyteCanonicalName (T128),
CASNumber (T32), MethodID (T64), ResultFraction (T32), MethodDilutionKey (T64),
AnalysisDate (DT), ResultRawText (T64), ResultNumeric (D), Units (T16),
ReportingLimit (D), DetectionLimit (D), Qualifier (T16), IsNonDetect (SH),
SpikeAmount (D), OriginalConcentration (D), PercentRecovery (D),
RecoveryLowerLimit (D), RecoveryUpperLimit (D), RPD (D), RPDControlLimit (D),
SourceWorkbook (T255), SourceSheet (T64), SourceRow (L).

SampleID convention (from the paper mapping): the QC sample's own id (lab-source
sys_sample_code); **for surrogate rows, the field sample's id**. ParentSampleID
carries `parent_sample_code` where the format supplies one.

`UNIQUE_KEYS["Env_QCResults"]` = (SiteID, Matrix, AnalysisBatchID, SampleID,
QCType, AnalyteCanonicalName, ResultFraction, MethodID, MethodDilutionKey).

Migration: the existing `upgrade_schema` / `run_edd_import` self-heal path
(PR #212) already creates missing tables and appends missing columns — no new
migration machinery.

## Reader design (`autogis/core/envmon/equis_reader.py`)

```
read_equis_xls(path, profile, qa=None)
  -> list[dict]   # flat rows; QC rows tagged __equis_stream="qc"
```

1. `import xlrd` (lazy, function-level). Open workbook; fetch the three sheets
   named by `profile.equis` (`sample_sheet`, `result_sheet`, `batch_sheet`;
   batch_sheet optional — absent means no batch ids). Each sheet → list of dicts
   keyed by header row (row 0), values `str(cell.value).strip()`; xlrd float
   artifacts (`438175.0` for text-ish numerics) normalized via a small
   `_cell_text` helper (int-valued floats render without `.0`).
2. Index Sample_v1 by `sys_sample_code`; index Batch_v1 by the 5-part composite,
   splitting `test_batch_type` Prep/Analysis into `__equis_prep_batch` /
   `__equis_analysis_batch`.
3. Per result row (stamping `row["__source_row"]` with the true sheet row):
   - join sample (D10 on miss); copy sample-side fields onto the flat row
     (sample_date, sys_loc_code, start/end depth + unit, sample_matrix_code,
     sample_type_code, sample_source, parent_sample_code, sample_name).
   - synthesize: `__equis_stream` (D3), `__equis_qc_type` (value_map
     `qc_sample_type` over sample_type_code; SUR rows → `SURROGATE`),
     `__equis_result` (D6), `__equis_qualifier` (D7),
     `__equis_matrix` (matrix_map over sample_matrix_code),
     `__equis_method_dilution_key` (D8), `__equis_units` (result_unit, else
     detection_limit_unit), converted `__equis_reporting_limit` /
     `__equis_detection_limit` / `__equis_quantitation_limit` (D11),
     `__equis_is_reportable` (Yes/No → "1"/"0"), batch ids.
4. Return all rows; the importer splits streams (D3).

Profile (`autogis/config/lab_profiles/wmrd.yaml`, `format: equis_xls`): standard
`columns:` map pointing canonical fields at real or `__equis_*` columns —
sample_id: sys_sample_code, location_id: sys_loc_code, event_date: sample_date,
lab_sample_id: lab_sample_id, analyte: chemical_name, cas_number: cas_rn,
method_id: lab_anl_method_name, fraction: fraction, analysis_date: analysis_date,
prep_method: prep_method, prep_date: prep_date, lab_name: lab_name_code,
basis: basis, result/units/limits/qualifier/matrix/qc_type/dilution_factor →
their `__equis_*` keys. `value_maps.qc_sample_type`: N→"" , QC-LCS→LCS,
QC-LCSD→LCSD, QC-LMS→MS, QC-LMSD→MSD, QC-LB→LAB_BLANK, QC-LD→LAB_DUP,
QC-LCCV→CCV, QC-LICV→ICV, QC-PDS→PDS, QC-LIFC→IFC, SRM→SRM, CRA→CRA.
`matrix_map`: SOLID→SOIL, WQ→GW, SQ-CONTROL/WQ-CONTROL kept as-is on QC rows.
The vocabularies are verified against one real Energy-Labs WMRD export
(B25030623) — mark the profile header accordingly (verified-against-one-export,
not DRAFT, but note the single-lab provenance).

### Normalizer / importer touches (deliberate, minimal)

- `normalize_edd_rows`: resolve optional `cas_number` and `quantitation_limit`
  and `is_reportable` columns, mirroring the existing `detection_limit` pattern
  (ADR-0080 §6). Format-agnostic: every EQuIS dialect carries them natively.
- `run_edd_import`: split `__equis_stream=="qc"` rows → `normalize_qc_rows` →
  `write_qc_results_to_gdb`; analytical rows continue unchanged. Formats that
  never tag (flat_csv, two_tab_xlsx, wqx_csv) see zero behavior change.
- `edd_profile.py`: `_VALID_FORMATS` += `equis_xls`; new optional `equis:`
  section (sheet names) with validation.

## QC normalization (`normalize_qc_rows`)

Maps tagged flat rows → `QCResultRecord` (fields = Env_QCResults columns).
ResultNumeric parses `__equis_result` (ND → IsNonDetect=1, ResultNumeric NULL);
spike rows additionally receive `qc_spike_measured` into ResultNumeric when
result_value is empty (documented convention from the paper mapping). D5 pivot
emits the dup record. AnalyteCanonicalName reuses the existing canonicalization
helper the analytical path uses (same dictionary; speciation fold rule applies).

## Testing (arcpy-free)

- Transform-level tests on plain dict rows (pattern of `test_wqx_reader.py`):
  QC routing incl. SUR-on-field-sample, D5 pivot, D6 conflict WARN, D7 qualifier
  precedence, D8 NA-normalized fold, D10 miss paths, D11 conversion+short-circuit.
- One committed synthetic `.xls` fixture (~20 rows, 3 sheets, junk column
  included) drives the end-to-end test: read → split → normalize both streams →
  `compute_unique_key` distinctness on both tables. Fixture built once offline by
  a scratchpad script using xlwt; **xlwt does not become a dependency** (the
  generator script is committed under `tests/fixtures/` with a regeneration
  note).
- canonical_read: IsReportable-preference tests (flag present picks flagged row;
  all-NULL behaves exactly as today — pinned).
- Schema: SCHEMA_VERSION bump test + Env_QCResults presence in
  TABLE_FIELDS/UNIQUE_KEYS.
- Manual verification against the real `B25030623` file during dev, recorded in
  the PR (client data never enters the repo).

## Explicitly deferred (recorded so later slices don't re-derive)

- mining/epar4 profiles; NYSDEC dictionary extraction + profile (slice 2).
- sxsamp reader + BS1/BS2 QCType semantics question (slice 3).
- VI paper mapping + Env_VIBuildingSurveys (slice 4 — VI confirmed on-roadmap).
- `evaluate_rpd_qa` dual fix; legacy-island tripwire (ADR-0079 follow-ups #1/#2).
- SampleParameter / field-parameter sheet routing (flattens into
  Env_AnalyticalResults later, no schema change needed).
- Radiochem columns (result_error_delta etc.) — not in this practice's workflow.
- `qc_level` (SCREEN/QUANT), `analysis_location` — deferred per paper mapping.
