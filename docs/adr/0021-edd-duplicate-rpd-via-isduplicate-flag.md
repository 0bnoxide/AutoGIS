# ADR-0021 — EDD duplicate RPD: detect via IsDuplicate=1 flag, not RPD worksheet

**Status:** Accepted  
**Date:** 2026-06-26  
**Deciders:** Greg / Claude Code  
**Related:** ADR-019 (WG2 scope), ADR-002 (arcpy-free core)

---

## Context

Lab EDDs (CSV/XLSX deliverables from the laboratory) express field-duplicate QA
samples in two different ways depending on the EDD format:

1. **Explicit RPD worksheet** — a separate sheet with parent/duplicate result
   columns and a pre-computed RPD column (handled by `normalize_rpd_table` in
   `normalize_rpd.py`).

2. **Row-level duplicate flag** — duplicate samples are extra rows in the main
   results section, with a flag column (e.g. `IsDuplicate=1`) and a
   `ParentSampleID` back-reference.  This is the pattern produced by common LIMS
   EDD export schemas.

WG2 needs to evaluate RPD for the row-level duplicate pattern, which is what lab
EDD imports produce in `Env_Samples.IsDuplicate` and `Env_Samples.ParentSampleID`.

---

## Decision

`evaluate_duplicate_rpd()` in `evaluate_rpd_qa.py` operates exclusively on
`IsDuplicate=1` rows and `ParentSampleID` cross-references in the in-memory
`SampleRecord` / `AnalyticalResultRecord` lists.  It does **not** parse RPD
worksheets (that is `normalize_rpd_table`'s job).

The two paths (`normalize_rpd_table` for explicit RPD sheets;
`evaluate_duplicate_rpd` for EDD row-level flags) remain separate and
complementary: the import pipeline calls whichever is appropriate for the workbook
type.

---

## Rationale

- **No schema change:** `IsDuplicate` and `ParentSampleID` are already present in
  `SampleRecord` (set by `table_normalizer.py:detect_duplicate_sample()`).
- **Separation of concerns:** the RPD worksheet normalizer already handles explicit
  RPD tables correctly; blending the two paths would create fragile conditional
  logic.
- **Headless / standalone:** `evaluate_duplicate_rpd` works from CSV sidecar files
  (via `read_records_csv`) with no arcpy, so it can run in post-import QA
  pipelines and CI.

---

## Consequences

- Post-import RPD QA for EDD-sourced data uses `evaluate-rpd-qa` CLI command.
- Workbooks with explicit RPD sheets continue to use `normalize_rpd_table` during
  import; `evaluate_duplicate_rpd` is not called for those.
- If a future EDD format provides both an RPD sheet *and* `IsDuplicate` flags,
  the caller must choose one path (or deduplicate results) — this is the
  caller's responsibility, not the core's.
