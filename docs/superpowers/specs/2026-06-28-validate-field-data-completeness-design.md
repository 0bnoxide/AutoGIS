# ValidateFieldDataCompleteness Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ValidateFieldDataCompleteness (Phase 2 / Tool 2.8)
**Priority:** HIGH — catches missing samples before report deliverable; saves rework

---

## Problem

After each sampling event, the lab returns results for the samples they received.
But there is often a gap: some wells in the sampling plan were not sampled (access
issue, bail failure, dry well), and some samples received by the lab don't match
any well in the plan (mislabeled COC). Currently, this comparison is done manually
in spreadsheets by cross-referencing the sampling event plan against the EDD or
lab result CSV. The comparison is tedious and mistakes lead to report errors.

---

## Approach

**Chosen:** Dual-input comparison: sampling event plan CSV (from
`create-sampling-event`) vs. received lab results CSV. Produces:
1. Not sampled: wells in plan with no lab results
2. Unexpected results: lab samples with no matching plan entry
3. Hold time violations: sample date vs. analysis date exceeds group hold time
4. Duplicate result conflicts: sample ID present in results more than once

**Rejected: Integrating into `ReconcileSurvey123AndLabResults`.** Reconciliation
compares Survey123 field submissions vs. lab; this tool compares the sampling
*plan* vs. lab results — a pre-reconciliation completeness check with different
inputs.

**Rejected: Requiring a GDB.** All inputs are CSVs; this is a headless operation.

---

## Architecture

```
autogis/
  core/envmon/
    field_completeness_validator.py   ← NEW
  adapters/
    cli.py                            ← add validate-field-completeness command
tests/envmon/
  test_field_completeness_validator.py ← NEW
```

---

## Public API (`field_completeness_validator.py`)

```python
@dataclass
class CompletenessIssue:
    issue_type: str   # not_sampled | unexpected_result | hold_time_exceeded | duplicate_sample_id
    sample_id: str
    location_id: str
    analyte_group: str
    detail: str
    severity: str     # ERROR | WARNING | INFO

@dataclass
class CompletenessResult:
    issues: list[CompletenessIssue]
    planned_count: int
    received_count: int
    matched_count: int
    not_sampled: list[str]       # sample IDs in plan with no results
    unexpected: list[str]        # sample IDs in results with no plan entry
    hold_time_violations: int
    qa: QACollector

def validate_field_completeness(
    plan_rows: list[dict],            # from event plan CSV (SampleID, LocationID, AnalyteGroup, HoldTimeDays, CollectionDate)
    result_rows: list[dict],          # from lab results CSV (SampleID, AnalysisDate, ...)
    *,
    match_field: str = "SampleID",
    hold_time_field: str = "HoldTimeDays",
) -> CompletenessResult:
    """
    Match plan vs results by SampleID. Flag:
    - not_sampled: plan SampleID absent from results
    - unexpected_result: result SampleID absent from plan
    - hold_time_exceeded: (AnalysisDate - CollectionDate) > HoldTimeDays
    - duplicate_sample_id: SampleID appears > 1 time in results
    """

def write_completeness_report(result: CompletenessResult, out_path: Path) -> None:
    """Write CSV of CompletenessIssues."""
```

---

## CLI Command

```
autogis envmon validate-field-completeness \
  --plan <sampling_event_plan.csv> \
  --results <lab_results.csv> \
  --out <completeness_issues.csv> \
  [--report <qa.md>] \
  [--fail-on error|warning]
```

Headless.

---

## Test Strategy

`tests/envmon/test_field_completeness_validator.py` — arcpy-free:

1. Matching sample IDs → `matched_count` correct, no issues
2. Sample in plan but not in results → `not_sampled` list populated, ERROR issue
3. Sample in results but not in plan → `unexpected` list populated, WARNING issue
4. Hold time exceeded → issue type `hold_time_exceeded`, WARNING severity
5. Duplicate SampleID in results → `duplicate_sample_id` issue
6. `planned_count` + `received_count` reflect input lengths
7. `write_completeness_report` produces CSV with `issue_type` column
8. Empty results → all plan entries flagged as not_sampled
