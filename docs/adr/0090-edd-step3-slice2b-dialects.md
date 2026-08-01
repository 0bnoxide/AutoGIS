# ADR-0090: EDD Step-3 slice 2b — mining/epar4/NYSDEC dialect support

**Status:** Accepted

**Date:** 2026-07-17

## Context

Slice 1 (ADR-0082) shipped the EQuIS v1 WMRD reader (`equis_reader.py`,
xlrd-only `.xls`, three-sheet Sample/TestResultQC/Batch shape). The slice-2
design spec (`docs/superpowers/specs/2026-07-12-edd-step3-slice2-design.md`,
PR #243) recorded template-verified facts for three further dialects — MTDEQ
Mining, EPA Region 4 (epar4), NYSDEC v5 — all `.xlsx`, all EQuIS-vocabulary
cousins with structural deltas: Mining renames ~10 columns and carries inline
batch ids; epar4 splits Test/Result into two sheets joined by a 7-column
composite and has no batch sheet; NYSDEC extends the batch join with
`analysis_date`. ADR-0084 froze the unique-key compositions and rejected
key widening and run-instance ordinals; QC rerun collisions ERROR-block by
design (#244).

## Decision

Implement the spec's R1–R9 as reader/profile extensions (no new reader, no
new dependency, zero CLI change):

- **R1** `read_equis_xls` dispatches by extension: `.xls` → xlrd (unchanged),
  `.xlsx` → openpyxl (existing dep, read-only, lazy import) normalizing cell
  text to the same contract (`_xlsx_cell_text`). Format id stays `equis_xls`.
- **R2** headers casefold + strip one leading `#` at load, both engines.
- **R3** new optional profile key `source_aliases: dict[str, str]` renames a
  dialect's outlier source columns onto the EQuIS canonical names before
  synthesis, so every `_COL_*` rule works untouched.
- **R4** new optional profile key `test_sheet:` — epar4's `EPAR4_TST_v1`
  rows are indexed by the shared 7-column composite and merged under the
  result row (result wins); a miss is QA-WARN `equis_missing_test` +
  fail-safe import. **This ADR explicitly accepts the amendment of
  ADR-0075's "flat and 2-sheet-shaped permanently" `LabEDDProfile` freeze**
  to admit `test_sheet:` (and the `source_aliases:` mapping key), following
  the precedent of slice 1's `batch_sheet` key (ADR-0082). All field
  mappings remain in profile YAML; the profile remains declarative.
- **R5** inline-batch fallback: with no batch sheet, a row's single
  `test_batch_type`/`test_batch_id` pair routes by type, case-insensitively
  (Mining/NYSDEC record uppercase PREP/ANALYSIS); a prep-typed id also
  fills `__equis_analysis_batch` because `AnalysisBatchID` — not
  PrepBatchID — is the frozen Env_QCResults key part. Unknown type → both
  empty + `equis_unknown_batch_type` WARN. Batch-sheet type lookups are
  case-insensitive too (slice-1's exact-case `Prep`/`Analysis` was WMRD
  vocabulary, not a contract).
- **R6** the batch join composite extends with `analysis_date` when both
  the batch and result sheets carry the column (NYSDEC `Batch_v5`); WMRD's
  5-column join is byte-identical when absent (pinned by existing tests).
- **R7** three DRAFT profiles (`mining.yaml`, `epar4.yaml`, `nysdec.yaml`),
  template-verified only; vocabularies seeded from the MTDEQ enum XML, the
  epar4 `rt_*` sheets, and the NYSDEC valid-values workbook. Unmapped
  values fail safe with QA-WARN (ADR-0080/D10 policy). Banners stay until
  verified against a real deliverable (wqx.yaml precedent).
- **R8** zero CLI change — dispatch entirely via `format: equis_xls`.
- **R9** when a profile sets `test_sheet:` (epar4), the reader folds a
  bounded `analysis_date`+`analysis_time` token — the two joined with `@`
  (absent from normalized `m/d/Y` dates and `H:M` times, so the map from a
  (date, time) pair to a token is injective) — into the `MethodDilutionKey`
  value recipe (ADR-0075 §3 escape hatch, same mechanism as ADR-0084 §1's
  method fold) — per-row, source-alone deterministic — so two reanalyses
  differing only by date/time key distinctly on both tables
  (`MethodDilutionKey` is a frozen key part of both). Worst-case composed
  value (4 run parts + method + a ~20-char date/time token) stays far below
  the TEXT(64) `detect_overlength_keys` guard. The token also feeds the #244
  run-identity design.

## Consequences

- The frozen key compositions are untouched; no run-instance ordinals exist.
  Dialect QC rerun collisions (non-epar4) still ERROR-block by design (#244).
- `LabEDDProfile` is now declaratively up-to-4-sheet-shaped
  (`sample_sheet`/`result_sheet`/`batch_sheet`/`test_sheet`); ADR-0075's
  freeze is amended exactly that far and no further.
- The three profiles are DRAFT: first production import of each dialect must
  be verified against a real deliverable before banner removal.
- Committed fixtures are synthetic openpyxl-generated `.xlsx` (template
  headers + invented rows); no client data enters the repo.
- **Post-review fixes (PR #253 codex, two data-integrity P1s):**
  - *R9 token injectivity.* The original token stripped all non-digits and
    concatenated, so `1/23/2025`+`4:56` and `12/3/2025`+`4:56` both became
    `1232025456` and collapsed the frozen key. Replaced with the `@`-joined
    form above; a regression pins the pair distinct.
  - *Duplicate test-key collision.* Two `test_sheet` rows sharing the R4
    7-column composite but carrying conflicting content (e.g. dilution 1 vs
    5) used to last-write-wins, making the merged dilution/prep metadata —
    and thus `MethodDilutionKey` — depend on file order. Now a blocking
    `equis_test_key_collision` (`SEV_ERROR`) that `run_edd_import` folds into
    the batch-integrity write-abort, matching the ADR-0084 within-file
    key-collision guard's "reject the whole batch for adjudication" policy.
    Exact duplicates stay idempotent (no error).

## Alternatives considered

- **Per-dialect `_COL_*` constant sets behind a `dialect:` knob.** Rejected
  (spec R3 rejection): every future dialect becomes a reader edit, and the
  three dialects verified here already share ~80% of their column vocabulary
  with WMRD — a parallel constant set would duplicate that shared surface
  per dialect instead of bridging the outliers once via `source_aliases`.
- **Route Mining through the `two_tab_xlsx` reader** (WQX-family, ADR-0080)
  instead of extending `equis_reader`. Rejected (D2 rejection re-confirmed):
  Mining is EQuIS-vocabulary, not WQX-vocabulary, and doing this would
  duplicate the QC stream fork, ND synthesis, and spike/recovery handling
  already built into `equis_reader` into a second reader rather than reusing
  it via `source_aliases`.
- **Widen the frozen unique keys** to carry run identity (e.g. an
  `AnalysisTime` or run-instance key part) instead of folding a token into
  `MethodDilutionKey`. Banned by ADR-0084, which rejected key-widening there
  for the same reason it applies here: it re-keys every existing row of
  every format for a problem localized to one reader family. The R9
  value-recipe fold is the sanctioned mechanism (ADR-0075 §3 escape hatch).

## Related decisions

- [ADR-0075](0075-canonical-schema-expansion-step1.md) — frozen keys, `LabEDDProfile` shape, ADR-0075 §3 value-recipe extensibility
- [ADR-0082](0082-edd-step3-equis-wmrd-slice1.md) — slice 1, precedent for `batch_sheet` profile key
- [ADR-0084](0084-edd-step3-slice2-key-collision-resolution.md) — slice 2 key decisions, analytical method fold mechanism
