# ReconcileFieldAndLabData Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `ReconcileFieldAndLabData` (roadmap #7.3) — a **post-import** cross-table reconciler that compares normalized `Env_Samples` records against `Env_AnalyticalResults` for sample-ID/date/location/matrix alignment and nondetect-qualifier consistency, producing a `QACollector` report.

**Architecture:**
- New: `autogis/core/envmon/reconcile_field_lab_data.py` — all headless reconciliation logic (`FieldLabMismatch`, `ReconcileFieldLabResult`, `reconcile_field_and_lab()`, `reconcile_to_qa()`); strictly arcpy-free.
- Modify: `autogis/adapters/cli.py` — add `envmon reconcile-field-lab` command (fully headless; no `_guard` call needed).
- New: `tests/envmon/test_reconcile_field_lab_data.py` — arcpy-free unit + CLI integration tests.

**Tech Stack:** Python stdlib (`csv`, `difflib`, `dataclasses`), `autogis.core.common.qa.{QACollector, QARecord}`, `autogis.core.envmon.gdb_schema.{SampleRecord, AnalyticalResultRecord}`, `autogis.core.envmon.evaluate_rpd_qa.read_records_csv`, `yaml` (already project dependency).

## Global Constraints

- No `arcpy` or `arcgis` imports anywhere in `autogis/core/` or `autogis/adapters/`. Violation breaks the headless test environment.
- `SampleRecord` and `AnalyticalResultRecord` come from `autogis.core.envmon.gdb_schema` — do NOT redefine them.
- `read_records_csv` comes from `autogis.core.envmon.evaluate_rpd_qa` — do NOT redefine it.
- `QACollector` / `QARecord` come from `autogis.core.common.qa`.
- Tests run with: `python -m pytest -q`
- CLI `--fail-on` default: `"error"` (consistent with `reconcile-survey123-lab`, `reconcile-locations`).
- Branch: `main` (standalone module; no feature branch required).
- `yaml` is already a project dependency (`import yaml` in `cli.py`); no new dependency needed.

---

## 2.6 vs 7.3 Boundary — Read This Before Touching Code

**Tool 2.6 — `reconcile_survey123_lab.py` (already shipped):**
- Stage: **PRE-IMPORT** — runs before data enters the database.
- Inputs: raw Survey123 field-export CSV + raw lab EDD file (or `LabSample` objects from `extract_sample_roster`).
- Own lightweight types: `Survey123Sample`, `LabSample`, `ReconcileS123LabResult`.
- Purpose: verify that every field submission will receive a lab result (and vice versa) so the team can chase missing samples before the deadline.
- Checks: sample_id match/mismatch (fuzzy), date mismatch, matrix mismatch, location mismatch.
- CLI: `envmon reconcile-survey123-lab`.

**Tool 7.3 — `reconcile_field_lab_data.py` (this plan):**
- Stage: **POST-IMPORT** — runs after `envmon import-edd` has populated `Env_Samples` and `Env_AnalyticalResults`.
- Inputs: CSV exports of `Env_Samples` and `Env_AnalyticalResults` (normalized GDB tables).
- Uses existing schema types: `SampleRecord`, `AnalyticalResultRecord` from `gdb_schema.py`.
- Purpose: catch import bugs and data-integrity issues that only appear once the records are normalized (e.g., EDD importer wrote a result under the wrong matrix, or set `IsNonDetect=1` without clearing `ResultNumeric`).
- Additional checks (beyond 2.6): **nondetect inconsistency** (`IsNonDetect=1` but `ResultNumeric > ReportingLimit`), **detect_without_value** (`IsDetected=1` but `ResultNumeric` is `None`), optional **expected-analyte coverage** per (location, matrix).
- CLI: `envmon reconcile-field-lab`.

**Reuse decisions:**
| Dependency | Decision | Reason |
|---|---|---|
| `QACollector` / `QARecord` | IMPORT | Universal output model for all envmon tools. |
| `SampleRecord` / `AnalyticalResultRecord` | IMPORT from `gdb_schema` | Canonical normalized schema; already used by `evaluate_rpd_qa`, `compare_events`, etc. |
| `read_records_csv` | IMPORT from `evaluate_rpd_qa` | Already handles type coercion for these exact dataclasses; no re-implementation. |
| `_sim()` from `reconcile_survey123_lab` | DO NOT IMPORT | Private function from a parallel module; duplicate the one-liner instead to keep coupling zero. |
| `reconcile_to_qa()` from `reconcile_survey123_lab` | DO NOT IMPORT | Different mismatch model; a new `reconcile_to_qa()` of the same name lives in this module. |

**Expected duplicate findings:** Running both 2.6 (pre-import) and 7.3 (post-import) on the same event is correct and intended. Any finding surfaced by 2.6 that was not resolved before import will appear again in 7.3. That is a feature, not a bug — two independent checkpoints.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `autogis/core/envmon/reconcile_field_lab_data.py` | All reconciliation logic; headless. |
| Create | `tests/envmon/test_reconcile_field_lab_data.py` | Unit tests + CLI help test. |
| Modify | `autogis/adapters/cli.py` | Add `reconcile-field-lab` command after the `reconcile-survey123-lab` block. |

---

### Task 1: Core module `reconcile_field_lab_data.py`

**Files:**
- Create: `autogis/core/envmon/reconcile_field_lab_data.py`
- Create: `tests/envmon/test_reconcile_field_lab_data.py`

**Interfaces:**
- Consumes: `SampleRecord`, `AnalyticalResultRecord` (gdb_schema), `QACollector`, `QARecord`, `SEV_ERROR`, `SEV_WARNING`, `SEV_INFO` (core.common.qa).
- Produces:
  - `FieldLabMismatch` dataclass — one per rule violation.
  - `ReconcileFieldLabResult` dataclass — `mismatches`, `orphan_samples`, `orphan_results`, `matched_count`.
  - `reconcile_field_and_lab(samples, results, expected_analytes, similarity_threshold) -> ReconcileFieldLabResult`
  - `reconcile_to_qa(result: ReconcileFieldLabResult) -> QACollector`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_reconcile_field_lab_data.py`:

```python
"""Tests for reconcile_field_lab_data (Tool 7.3, post-import field/lab QA).

All test fixtures are constructed from gdb_schema dataclasses so the tests
exercise exactly the same types the CLI will feed the reconciler.
"""
from datetime import date

from autogis.core.envmon.gdb_schema import AnalyticalResultRecord, SampleRecord
from autogis.core.envmon.reconcile_field_lab_data import (
    FieldLabMismatch,
    ReconcileFieldLabResult,
    reconcile_field_and_lab,
    reconcile_to_qa,
)
from autogis.core.common.qa import SEV_ERROR, SEV_WARNING, SEV_INFO

# ---------------------------------------------------------------------------
# Test-data factories — supply ALL required positional fields; vary only what
# the test cares about.
# ---------------------------------------------------------------------------

def _sample(
    sample_id: str = "H281-MW01-20260615-GW",
    location_id: str = "MW-01",
    sample_date: date = date(2026, 6, 15),
    matrix: str = "GW",
) -> SampleRecord:
    return SampleRecord(
        ImportBatchID="B1",
        SiteID="H281",
        Matrix=matrix,
        LocationID=location_id,
        SampleID=sample_id,
        ParentSampleID="",
        SampleDate=sample_date,
        SampleDateRaw=str(sample_date),
        DepthTop_ft=None,
        DepthBottom_ft=None,
        DepthIntervalText="",
        IsDuplicate=0,
        DuplicateType="",
        LabSampleID="LAB-001",
        SourceWorkbook="test.xlsx",
        SourceSheet="Results",
        SourceRow=2,
    )


def _result(
    sample_id: str = "H281-MW01-20260615-GW",
    location_id: str = "MW-01",
    sample_date: date = date(2026, 6, 15),
    matrix: str = "GW",
    analyte: str = "Benzene",
    is_nondetect: int = 0,
    result_numeric: float | None = 1.5,
    reporting_limit: float | None = 0.5,
    qualifier: str = "",
    is_not_analyzed: int = 0,
    is_not_sampled: int = 0,
) -> AnalyticalResultRecord:
    return AnalyticalResultRecord(
        ImportBatchID="B1",
        SiteID="H281",
        Matrix=matrix,
        LocationID=location_id,
        SampleID=sample_id,
        ParentSampleID="",
        SampleDate=sample_date,
        DepthTop_ft=None,
        DepthBottom_ft=None,
        DepthIntervalText="",
        AnalyticalGroup="VOC",
        MethodGroup="8260",
        AnalyteName=analyte,
        AnalyteCanonicalName=analyte,
        AnalyteAbbreviation="BNZ",
        ResultRawText=str(result_numeric) if result_numeric is not None else "",
        ResultNumeric=result_numeric,
        ReportingLimit=reporting_limit,
        DetectionLimit=None,
        Units="ug/L",
        Qualifier=qualifier,
        IsNonDetect=is_nondetect,
        IsDetected=int(not is_nondetect and result_numeric is not None),
        IsEstimated=0,
        IsDiluted=0,
        IsNotAnalyzed=is_not_analyzed,
        IsNotSampled=is_not_sampled,
        IsNotMeasured=0,
        ScreeningLevel=None,
        ScreeningLevelSource="",
        ExceedsScreeningLevel=None,
        DisplayText="",
        DisplayColorClass="",
        SourceWorkbook="test.xlsx",
        SourceSheet="Results",
        SourceRow=3,
        SourceColumn="",
        SourceCell="",
    )


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------

def test_perfect_match_no_mismatches():
    """Matching sample_id, date, location, matrix with clean result → no flags."""
    out = reconcile_field_and_lab([_sample()], [_result()])
    assert out.orphan_samples == []
    assert out.orphan_results == []
    assert out.mismatches == []
    assert out.matched_count == 1


def test_orphan_sample_no_results():
    """Sample with no matching result SampleID is recorded as orphan_sample."""
    s = _sample()
    r = _result(sample_id="UNRELATED-SAMPLE-99")
    out = reconcile_field_and_lab([s], [r])
    assert s in out.orphan_samples


def test_orphan_result_no_sample():
    """Result whose SampleID matches no sample is recorded as orphan_result."""
    s = _sample()
    r = _result(sample_id="LAB-ONLY-ORPHAN")
    out = reconcile_field_and_lab([s], [r])
    assert r in out.orphan_results


def test_empty_inputs_return_zero_counts():
    out = reconcile_field_and_lab([], [])
    assert out.matched_count == 0
    assert out.orphan_samples == []
    assert out.orphan_results == []
    assert out.mismatches == []


# ---------------------------------------------------------------------------
# Date / location / matrix mismatches on matched pairs
# ---------------------------------------------------------------------------

def test_date_mismatch_flagged():
    """Result SampleDate differs from sample SampleDate → date_mismatch."""
    r = _result(sample_date=date(2026, 6, 16))
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "date_mismatch" in rules


def test_location_mismatch_flagged():
    """Result LocationID differs from sample LocationID → location_mismatch."""
    r = _result(location_id="MW-99")
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "location_mismatch" in rules


def test_matrix_mismatch_flagged():
    """Result Matrix differs from sample Matrix → matrix_mismatch."""
    r = _result(matrix="SOIL")
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "matrix_mismatch" in rules


def test_location_mismatch_is_case_insensitive():
    """Location comparison is case-insensitive — 'mw-01' must not mismatch 'MW-01'."""
    r = _result(location_id="mw-01")
    out = reconcile_field_and_lab([_sample(location_id="MW-01")], [r])
    rules = [m.rule for m in out.mismatches]
    assert "location_mismatch" not in rules


def test_matrix_mismatch_is_case_insensitive():
    """Matrix comparison is case-insensitive — 'gw' must not mismatch 'GW'."""
    r = _result(matrix="gw")
    out = reconcile_field_and_lab([_sample(matrix="GW")], [r])
    rules = [m.rule for m in out.mismatches]
    assert "matrix_mismatch" not in rules


# ---------------------------------------------------------------------------
# Nondetect / detect consistency
# ---------------------------------------------------------------------------

def test_nondetect_with_positive_numeric_above_rl_flagged():
    """IsNonDetect=1 but ResultNumeric > ReportingLimit → nondetect_inconsistency."""
    r = _result(is_nondetect=1, result_numeric=5.0, reporting_limit=0.5)
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "nondetect_inconsistency" in rules


def test_nondetect_with_none_numeric_is_clean():
    """IsNonDetect=1 with ResultNumeric=None is normal (ND = value not reported)."""
    r = _result(is_nondetect=1, result_numeric=None, reporting_limit=0.5, qualifier="U")
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "nondetect_inconsistency" not in rules


def test_nondetect_with_numeric_at_or_below_rl_is_clean():
    """IsNonDetect=1 with ResultNumeric <= ReportingLimit is acceptable (imputed ND value)."""
    r = _result(is_nondetect=1, result_numeric=0.5, reporting_limit=0.5, qualifier="U")
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "nondetect_inconsistency" not in rules


def test_detect_without_numeric_value_flagged():
    """IsDetected=1 (IsNonDetect=0) but ResultNumeric is None → detect_without_value."""
    r = _result(is_nondetect=0, result_numeric=None, qualifier="")
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "detect_without_value" in rules


def test_detect_without_value_suppressed_when_not_analyzed():
    """IsNotAnalyzed=1 with no numeric value must NOT flag detect_without_value."""
    r = _result(is_nondetect=0, result_numeric=None, is_not_analyzed=1)
    out = reconcile_field_and_lab([_sample()], [r])
    rules = [m.rule for m in out.mismatches]
    assert "detect_without_value" not in rules


# ---------------------------------------------------------------------------
# Expected-analyte coverage (optional)
# ---------------------------------------------------------------------------

def test_missing_expected_analyte_flagged():
    """GW Benzene expected but only Toluene present → missing_expected_analyte."""
    expected = {"GW": ["Benzene", "Toluene"]}
    r_toluene = _result(analyte="Toluene")
    out = reconcile_field_and_lab(
        [_sample()], [r_toluene], expected_analytes=expected
    )
    rules = [m.rule for m in out.mismatches]
    assert "missing_expected_analyte" in rules
    # Toluene is present — must NOT be flagged
    missing_analytes = [m.analyte_name for m in out.mismatches
                        if m.rule == "missing_expected_analyte"]
    assert "Toluene" not in missing_analytes
    assert "Benzene" in missing_analytes


def test_all_expected_analytes_present_no_flag():
    """When all expected analytes are present, no missing_expected_analyte flags."""
    expected = {"GW": ["Benzene"]}
    r = _result(analyte="Benzene")
    out = reconcile_field_and_lab([_sample()], [r], expected_analytes=expected)
    rules = [m.rule for m in out.mismatches]
    assert "missing_expected_analyte" not in rules


def test_no_expected_analytes_skips_coverage_check():
    """expected_analytes=None → no missing_expected_analyte flags ever."""
    r = _result(analyte="Benzene")
    out = reconcile_field_and_lab([_sample()], [r], expected_analytes=None)
    rules = [m.rule for m in out.mismatches]
    assert "missing_expected_analyte" not in rules


# ---------------------------------------------------------------------------
# QA severity mapping
# ---------------------------------------------------------------------------

def test_reconcile_to_qa_matrix_mismatch_is_error():
    """matrix_mismatch → SEV_ERROR (potential cross-contamination data error)."""
    r = _result(matrix="SOIL")
    result = reconcile_field_and_lab([_sample()], [r])
    qa = reconcile_to_qa(result)
    assert any(
        rec.category == "matrix_mismatch" and rec.severity == SEV_ERROR
        for rec in qa.records
    )


def test_reconcile_to_qa_nondetect_inconsistency_is_error():
    """nondetect_inconsistency → SEV_ERROR (corrupt import flag)."""
    r = _result(is_nondetect=1, result_numeric=5.0, reporting_limit=0.5)
    result = reconcile_field_and_lab([_sample()], [r])
    qa = reconcile_to_qa(result)
    assert any(
        rec.category == "nondetect_inconsistency" and rec.severity == SEV_ERROR
        for rec in qa.records
    )


def test_reconcile_to_qa_detect_without_value_is_error():
    """detect_without_value → SEV_ERROR (potential data loss)."""
    r = _result(is_nondetect=0, result_numeric=None)
    result = reconcile_field_and_lab([_sample()], [r])
    qa = reconcile_to_qa(result)
    assert any(
        rec.category == "detect_without_value" and rec.severity == SEV_ERROR
        for rec in qa.records
    )


def test_reconcile_to_qa_orphan_sample_is_warning():
    """orphan_sample → SEV_WARNING (may be lab delay, not necessarily wrong)."""
    s = _sample()
    result = reconcile_field_and_lab([s], [])
    qa = reconcile_to_qa(result)
    assert any(
        rec.category == "orphan_sample" and rec.severity == SEV_WARNING
        for rec in qa.records
    )


def test_reconcile_to_qa_orphan_result_is_warning():
    """orphan_result → SEV_WARNING (may be QC sample or lab rerun)."""
    r = _result(sample_id="LAB-ONLY-SAMPLE")
    result = reconcile_field_and_lab([], [r])
    qa = reconcile_to_qa(result)
    assert any(
        rec.category == "orphan_result" and rec.severity == SEV_WARNING
        for rec in qa.records
    )


def test_reconcile_to_qa_always_has_reconcile_complete_info():
    """reconcile_to_qa always appends an INFO summary record."""
    result = reconcile_field_and_lab([_sample()], [_result()])
    qa = reconcile_to_qa(result)
    assert any(rec.category == "reconcile_complete" and rec.severity == SEV_INFO
               for rec in qa.records)


# ---------------------------------------------------------------------------
# Invariant: module must be arcpy-free
# ---------------------------------------------------------------------------

def test_module_is_arcpy_free():
    """Core module must not import arcpy or arcgis (arcpy-free invariant)."""
    import inspect
    import autogis.core.envmon.reconcile_field_lab_data as m
    src = inspect.getsource(m)
    assert "import arcpy" not in src
    assert "from arcpy" not in src
    assert "import arcgis" not in src
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/envmon/test_reconcile_field_lab_data.py -v
```

Expected: `ModuleNotFoundError: No module named 'autogis.core.envmon.reconcile_field_lab_data'` — confirms nothing is implemented yet.

- [ ] **Step 3: Create `autogis/core/envmon/reconcile_field_lab_data.py`**

```python
"""reconcile_field_lab_data.py — post-import field/lab cross-table reconciler (Tool 7.3).

Compares normalized Env_Samples records against Env_AnalyticalResults for:
  - orphan_sample   : sample record with no analytical results
  - orphan_result   : analytical result with no parent sample record
  - date_mismatch   : SampleDate disagrees between the two tables
  - location_mismatch: LocationID disagrees between the two tables
  - matrix_mismatch : Matrix disagrees between the two tables (ERROR)
  - nondetect_inconsistency: IsNonDetect=1 but ResultNumeric > ReportingLimit (ERROR)
  - detect_without_value: IsDetected=1 but ResultNumeric is None (ERROR)
  - missing_expected_analyte: required analyte absent for a (location, matrix) pair

Relation to Tool 2.6 (reconcile_survey123_lab.py):
  - 2.6 is PRE-IMPORT: raw Survey123 CSV + raw lab EDD → field-to-lab coverage check
  - 7.3 (this module) is POST-IMPORT: normalized GDB table exports → import integrity check
  Different input types, different rule set, no shared imports between the two modules.

Arcpy-free. No arcpy or arcgis imports anywhere in this file.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO
from .gdb_schema import AnalyticalResultRecord, SampleRecord


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FieldLabMismatch:
    """One rule violation found during reconciliation."""
    rule: str          # e.g. "date_mismatch", "nondetect_inconsistency"
    severity: str      # SEV_ERROR or SEV_WARNING
    sample_id: str
    location_id: str
    sample_date: str   # ISO date string or ""
    matrix: str
    analyte_name: str  # "" when not analyte-specific
    message: str


@dataclass
class ReconcileFieldLabResult:
    """Aggregate output of reconcile_field_and_lab()."""
    mismatches: list[FieldLabMismatch] = field(default_factory=list)
    orphan_samples: list[SampleRecord] = field(default_factory=list)
    orphan_results: list[AnalyticalResultRecord] = field(default_factory=list)
    matched_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sim(a: str, b: str) -> float:
    """Sequence similarity ratio for fuzzy sample-ID fallback (0.0–1.0)."""
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def _date_str(d) -> str:
    return d.isoformat() if d is not None else ""


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------

def reconcile_field_and_lab(
    samples: list[SampleRecord],
    results: list[AnalyticalResultRecord],
    expected_analytes: Optional[dict[str, list[str]]] = None,
    similarity_threshold: float = 0.85,
) -> ReconcileFieldLabResult:
    """Reconcile Env_Samples records against Env_AnalyticalResults records.

    Args:
        samples: SampleRecord list, e.g. from read_records_csv(path, SampleRecord).
        results: AnalyticalResultRecord list, e.g. from read_records_csv(path, AnalyticalResultRecord).
        expected_analytes: Optional dict mapping matrix (e.g. "GW") to a list of
            canonical analyte names that must appear in Env_AnalyticalResults for
            every (location_id, matrix) pair present in Env_Samples. When None,
            coverage checks are skipped.
        similarity_threshold: Minimum difflib ratio (0–1) for fuzzy SampleID
            fallback. Fuzzy matching only triggers when no exact match is found.
            A match below this threshold is treated as an orphan_result.
    """
    out = ReconcileFieldLabResult()

    # Index samples by SampleID for O(1) exact lookup
    sample_index: dict[str, SampleRecord] = {s.SampleID: s for s in samples}
    unmatched_sample_ids: set[str] = set(sample_index.keys())

    # Group results by SampleID (multiple analytes share a SampleID)
    results_by_sample: dict[str, list[AnalyticalResultRecord]] = {}
    for r in results:
        results_by_sample.setdefault(r.SampleID, []).append(r)

    for result_sid, recs in results_by_sample.items():
        matched_sample = sample_index.get(result_sid)

        if matched_sample is None:
            # Fuzzy fallback — pick best match among all known sample IDs
            if sample_index:
                best_score, best_sid = max(
                    ((_sim(result_sid, s), s) for s in sample_index),
                    key=lambda x: x[0],
                    default=(0.0, ""),
                )
            else:
                best_score, best_sid = 0.0, ""

            if best_score >= similarity_threshold and best_sid:
                matched_sample = sample_index[best_sid]
                out.mismatches.append(FieldLabMismatch(
                    rule="sample_id_mismatch",
                    severity=SEV_WARNING,
                    sample_id=result_sid,
                    location_id=recs[0].LocationID,
                    sample_date=_date_str(recs[0].SampleDate),
                    matrix=recs[0].Matrix,
                    analyte_name="",
                    message=(
                        f"Lab SampleID {result_sid!r} fuzzy-matched to field record "
                        f"{best_sid!r} (similarity={best_score:.2f}). Verify manually."
                    ),
                ))
            else:
                # No usable match — all results for this SampleID are orphans
                out.orphan_results.extend(recs)
                continue

        unmatched_sample_ids.discard(matched_sample.SampleID)
        out.matched_count += 1

        for r in recs:
            _check_result_vs_sample(out, matched_sample, r)

    # Samples not claimed by any result group are orphaned
    for sid in unmatched_sample_ids:
        out.orphan_samples.append(sample_index[sid])

    # Optional expected-analyte coverage
    if expected_analytes:
        _check_expected_analytes(out, samples, results, expected_analytes)

    return out


def _check_result_vs_sample(
    out: ReconcileFieldLabResult,
    s: SampleRecord,
    r: AnalyticalResultRecord,
) -> None:
    """Append mismatches found when comparing one result record against its parent sample."""
    sid = r.SampleID
    loc = r.LocationID
    dt = _date_str(r.SampleDate)
    mx = r.Matrix
    an = r.AnalyteName

    # --- Date mismatch ---
    if s.SampleDate != r.SampleDate:
        out.mismatches.append(FieldLabMismatch(
            rule="date_mismatch",
            severity=SEV_WARNING,
            sample_id=sid,
            location_id=loc,
            sample_date=dt,
            matrix=mx,
            analyte_name=an,
            message=(
                f"SampleDate mismatch for {sid!r}: "
                f"Env_Samples={_date_str(s.SampleDate)} vs "
                f"Env_AnalyticalResults={dt}. "
                f"Check EDD import mapping or lab CoC."
            ),
        ))

    # --- Location mismatch ---
    if s.LocationID.upper() != r.LocationID.upper():
        out.mismatches.append(FieldLabMismatch(
            rule="location_mismatch",
            severity=SEV_WARNING,
            sample_id=sid,
            location_id=loc,
            sample_date=dt,
            matrix=mx,
            analyte_name=an,
            message=(
                f"LocationID mismatch for {sid!r}: "
                f"Env_Samples={s.LocationID!r} vs "
                f"Env_AnalyticalResults={r.LocationID!r}. "
                f"Check analyte dictionary alias or EDD column mapping."
            ),
        ))

    # --- Matrix mismatch (ERROR — cross-matrix confusion is a data integrity issue) ---
    if s.Matrix.upper() != r.Matrix.upper():
        out.mismatches.append(FieldLabMismatch(
            rule="matrix_mismatch",
            severity=SEV_ERROR,
            sample_id=sid,
            location_id=loc,
            sample_date=dt,
            matrix=mx,
            analyte_name=an,
            message=(
                f"Matrix mismatch for {sid!r}: "
                f"Env_Samples={s.Matrix!r} vs "
                f"Env_AnalyticalResults={r.Matrix!r}. "
                f"Results may be assigned to the wrong layer. Correct before mapping."
            ),
        ))

    # --- Nondetect inconsistency (ERROR — IsNonDetect flag contradicts numeric value) ---
    if r.IsNonDetect and r.ResultNumeric is not None:
        rl = r.ReportingLimit if r.ReportingLimit is not None else 0.0
        if r.ResultNumeric > rl:
            out.mismatches.append(FieldLabMismatch(
                rule="nondetect_inconsistency",
                severity=SEV_ERROR,
                sample_id=sid,
                location_id=loc,
                sample_date=dt,
                matrix=mx,
                analyte_name=an,
                message=(
                    f"IsNonDetect=1 but ResultNumeric={r.ResultNumeric} exceeds "
                    f"ReportingLimit={r.ReportingLimit} for {an!r} in {sid!r}. "
                    f"EDD import may have set the ND flag incorrectly."
                ),
            ))

    # --- Detected result with no numeric value (ERROR — possible data loss) ---
    if (
        not r.IsNonDetect
        and r.ResultNumeric is None
        and not r.IsNotAnalyzed
        and not r.IsNotSampled
        and not r.IsNotMeasured
    ):
        out.mismatches.append(FieldLabMismatch(
            rule="detect_without_value",
            severity=SEV_ERROR,
            sample_id=sid,
            location_id=loc,
            sample_date=dt,
            matrix=mx,
            analyte_name=an,
            message=(
                f"IsDetected=1 but ResultNumeric is None for {an!r} in {sid!r}. "
                f"Possible data loss during EDD import; check source cell."
            ),
        ))


def _check_expected_analytes(
    out: ReconcileFieldLabResult,
    samples: list[SampleRecord],
    results: list[AnalyticalResultRecord],
    expected_analytes: dict[str, list[str]],
) -> None:
    """Flag (location_id, matrix) pairs missing required analytes.

    Only checks pairs that have at least one sample record. Skips results where
    IsNotAnalyzed=1 (the lab omitted the test; not a reconciliation failure).
    """
    # Build set of (location_id_upper, matrix_upper, analyte_canonical_upper) present
    present: set[tuple[str, str, str]] = {
        (r.LocationID.upper(), r.Matrix.upper(), r.AnalyteCanonicalName.upper())
        for r in results
        if not r.IsNotAnalyzed
    }

    seen_pairs: set[tuple[str, str]] = set()
    for s in samples:
        key = (s.LocationID.upper(), s.Matrix.upper())
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        # Support both "GW" and "gw" as keys in the expected_analytes dict
        required = (
            expected_analytes.get(s.Matrix)
            or expected_analytes.get(s.Matrix.upper())
            or []
        )
        for analyte in required:
            if (s.LocationID.upper(), s.Matrix.upper(), analyte.upper()) not in present:
                out.mismatches.append(FieldLabMismatch(
                    rule="missing_expected_analyte",
                    severity=SEV_WARNING,
                    sample_id="",
                    location_id=s.LocationID,
                    sample_date="",
                    matrix=s.Matrix,
                    analyte_name=analyte,
                    message=(
                        f"Expected analyte {analyte!r} not found in "
                        f"Env_AnalyticalResults for location {s.LocationID!r} "
                        f"(matrix={s.Matrix!r}). Lab may have omitted it or "
                        f"used a non-canonical name."
                    ),
                ))


# ---------------------------------------------------------------------------
# QA output
# ---------------------------------------------------------------------------

def reconcile_to_qa(result: ReconcileFieldLabResult) -> QACollector:
    """Convert ReconcileFieldLabResult into a QACollector for _render_qa output."""
    qa = QACollector()

    _sev: dict[str, str] = {
        "matrix_mismatch": SEV_ERROR,
        "nondetect_inconsistency": SEV_ERROR,
        "detect_without_value": SEV_ERROR,
        "date_mismatch": SEV_WARNING,
        "location_mismatch": SEV_WARNING,
        "sample_id_mismatch": SEV_WARNING,
        "missing_expected_analyte": SEV_WARNING,
    }

    for m in result.mismatches:
        qa.add(QARecord(
            severity=_sev.get(m.rule, SEV_WARNING),
            category=m.rule,
            message=m.message,
            location_id=m.location_id,
            sample_id=m.sample_id,
            sample_date=m.sample_date,
            analyte_name=m.analyte_name,
        ))

    for s in result.orphan_samples:
        qa.add(QARecord(
            severity=SEV_WARNING,
            category="orphan_sample",
            message=(
                f"Sample {s.SampleID!r} (location={s.LocationID!r}, "
                f"matrix={s.Matrix!r}, date={_date_str(s.SampleDate)}) "
                f"has no corresponding rows in Env_AnalyticalResults. "
                f"Lab results may not yet be received."
            ),
            location_id=s.LocationID,
            sample_id=s.SampleID,
            sample_date=_date_str(s.SampleDate),
        ))

    for r in result.orphan_results:
        qa.add(QARecord(
            severity=SEV_WARNING,
            category="orphan_result",
            message=(
                f"Analytical result for sample {r.SampleID!r} "
                f"(analyte={r.AnalyteName!r}, location={r.LocationID!r}) "
                f"has no parent record in Env_Samples. "
                f"May be a QC sample, lab duplicate, or import error."
            ),
            location_id=r.LocationID,
            sample_id=r.SampleID,
            sample_date=_date_str(r.SampleDate),
            analyte_name=r.AnalyteName,
        ))

    qa.add(QARecord(
        severity=SEV_INFO,
        category="reconcile_complete",
        message=(
            f"Matched: {result.matched_count}  "
            f"Orphan samples: {len(result.orphan_samples)}  "
            f"Orphan results: {len(result.orphan_results)}  "
            f"Mismatches: {len(result.mismatches)}"
        ),
    ))
    return qa
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_reconcile_field_lab_data.py -v
```

Expected: all tests PASS. Count should be 22.

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all prior tests still pass; new tests added.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/reconcile_field_lab_data.py tests/envmon/test_reconcile_field_lab_data.py
git commit -m "feat(envmon): reconcile_field_lab_data — post-import field/lab cross-table QA (Tool 7.3)"
```

---

### Task 2: CLI command `envmon reconcile-field-lab`

**Files:**
- Modify: `autogis/adapters/cli.py` (add command after the `reconcile-survey123-lab` block at line ~1327)
- Modify: `tests/envmon/test_reconcile_field_lab_data.py` (append CLI help test)

**Interfaces:**
- Consumes: `reconcile_field_and_lab`, `reconcile_to_qa` (from `reconcile_field_lab_data`); `read_records_csv` (from `evaluate_rpd_qa`); `SampleRecord`, `AnalyticalResultRecord` (from `gdb_schema`); `_render_qa` helper already defined in `cli.py`; `yaml` already imported in `cli.py`; `Path` already imported in `cli.py`.
- Produces: `envmon reconcile-field-lab` command registered in `@envmon` group.

**Note:** This command is fully headless. Do NOT call `_guard()` — `_guard` is only for commands that require arcpy at runtime.

- [ ] **Step 1: Add command to `autogis/adapters/cli.py`**

Find the closing lines of the `reconcile-survey123-lab` command handler (around line 1327) and insert the following block immediately after it, before the `route-survey123` command:

```python
@envmon.command("reconcile-field-lab")
@click.option("--samples-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_Samples (output of import-edd or GDB table export).")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--expected-analytes", "expected_yaml", default=None,
              type=click.Path(exists=True),
              help=(
                  "YAML file mapping matrix to required analyte list. "
                  "Top-level key 'expected_analytes' is optional. "
                  "Example: {GW: [Benzene, Toluene], SOIL: [TPH-D]}"
              ))
@click.option("--threshold", type=float, default=0.85, show_default=True,
              help="Fuzzy SampleID similarity threshold (0.0–1.0).")
@click.option("--report", default=None, type=click.Path(),
              help="Output report path (.csv / .json / .md).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def reconcile_field_lab_cmd(samples_csv, results_csv, expected_yaml,
                            threshold, report, fail_on):
    """Tool 7.3: reconcile Env_Samples vs Env_AnalyticalResults post-import (headless).

    Checks for orphan samples/results, date/location/matrix mismatches,
    nondetect qualifier inconsistency, and optional expected-analyte coverage.
    Exits 1 when the worst finding meets --fail-on severity.
    """
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.gdb_schema import SampleRecord, AnalyticalResultRecord
    from autogis.core.envmon.reconcile_field_lab_data import (
        reconcile_field_and_lab, reconcile_to_qa,
    )

    samples = read_records_csv(Path(samples_csv), SampleRecord)
    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)

    expected: dict | None = None
    if expected_yaml:
        raw = yaml.safe_load(Path(expected_yaml).read_text(encoding="utf-8"))
        # Accept both {"GW": [...]} and {"expected_analytes": {"GW": [...]}}
        if isinstance(raw, dict) and "expected_analytes" in raw:
            expected = raw["expected_analytes"]
        else:
            expected = raw

    result = reconcile_field_and_lab(
        samples, results,
        expected_analytes=expected,
        similarity_threshold=threshold,
    )
    click.echo(
        f"Matched: {result.matched_count}  "
        f"Orphan samples: {len(result.orphan_samples)}  "
        f"Orphan results: {len(result.orphan_results)}  "
        f"Mismatches: {len(result.mismatches)}"
    )
    qa = reconcile_to_qa(result)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Add CLI help test**

Append to `tests/envmon/test_reconcile_field_lab_data.py`:

```python
def test_reconcile_field_lab_in_help():
    """CLI command must appear in 'autogis envmon --help' output."""
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as cli_root
    result = CliRunner().invoke(cli_root, ["envmon", "--help"])
    assert result.exit_code == 0, result.output
    assert "reconcile-field-lab" in result.output
```

- [ ] **Step 3: Run all tests**

```
python -m pytest tests/envmon/test_reconcile_field_lab_data.py -v
```

Expected: all 23 tests PASS (22 core + 1 CLI help test).

- [ ] **Step 4: Run full suite**

```
python -m pytest -q
```

Expected: all prior tests still pass.

- [ ] **Step 5: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_reconcile_field_lab_data.py
git commit -m "feat(cli): add reconcile-field-lab command (Tool 7.3 post-import QA)"
```

---

## Self-Review Checklist

**Spec coverage:**

| Requirement | Covered in |
|---|---|
| Sample ID mismatch detection | `reconcile_field_and_lab` exact + fuzzy match; `sample_id_mismatch` rule |
| Date mismatch | `_check_result_vs_sample` → `date_mismatch` |
| Location mismatch | `_check_result_vs_sample` → `location_mismatch` |
| Matrix mismatch | `_check_result_vs_sample` → `matrix_mismatch` (SEV_ERROR) |
| Nondetect mismatch | `_check_result_vs_sample` → `nondetect_inconsistency` (SEV_ERROR) |
| Headless core | No arcpy/arcgis imports; test asserts this at runtime |
| QA table output | `reconcile_to_qa` → `QACollector` with per-record `QARecord` |
| CLI surface | Task 2, `envmon reconcile-field-lab` |
| TDD | Tests written first (Step 1), implementation second (Step 3) |
| Explicit 2.6 vs 7.3 boundary | Module docstring + plan section above |

**Placeholder scan:** No TBD/TODO/fill-in placeholders present. Every code block is complete and runnable.

**Type consistency:**
- `FieldLabMismatch` is defined in Task 1 Step 3, used identically in tests (Task 1 Step 1) via import.
- `ReconcileFieldLabResult` is imported in tests and returned by `reconcile_field_and_lab` — same type name throughout.
- `reconcile_to_qa` takes `ReconcileFieldLabResult` in both the implementation and the CLI — consistent.
- `read_records_csv(path, SampleRecord)` / `read_records_csv(path, AnalyticalResultRecord)` — function and types already exist in `evaluate_rpd_qa.py` and `gdb_schema.py`.

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **2.6 overlap**: Both tools flag date/location/matrix mismatches, so the same issue appears twice when both run. | Certain | Documented in module docstring and this plan. The tools serve different stages; duplication is intentional and correct. |
| **`SampleRecord` / `AnalyticalResultRecord` field count**: ~16 and ~30 required fields each; test factory is verbose. | High | Factory functions `_sample()` / `_result()` in the test file centralize fixture construction. Only the meaningful field is varied per test. |
| **`read_records_csv` import path**: it lives in `evaluate_rpd_qa.py`, not a shared utilities module. Moving it breaks the CLI import. | Low | Acceptable technical debt (YAGNI). If a third importer appears, extract it then. |
| **Fuzzy fallback performance**: O(samples × unique_result_SIDs). With 10,000 samples and 5,000 unique result SIDs this is 50M comparisons. | Low for real data (typical site: <500 samples/event) | Fuzzy path only triggers on non-exact-match results. Add a note to `--help` recommending pre-filtering by event when datasets are large. |
| **`IsDetected` / `IsNonDetect` both 0**: possible for `IsNotAnalyzed=1` rows. The `detect_without_value` guard already checks `not r.IsNotAnalyzed and not r.IsNotSampled and not r.IsNotMeasured`; this edge case is covered by `test_detect_without_value_suppressed_when_not_analyzed`. | Medium | Covered by explicit test. |
