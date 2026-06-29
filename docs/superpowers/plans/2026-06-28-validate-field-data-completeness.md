# ValidateFieldDataCompleteness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ValidateFieldDataCompleteness` — compare sampling event plan vs. received lab results; flag not-sampled wells, unexpected results, hold-time violations, and duplicate sample IDs.
See spec: `docs/superpowers/specs/2026-06-28-validate-field-data-completeness-design.md`.

**Architecture:**
- New: `autogis/core/envmon/field_completeness_validator.py`
- Modify: `autogis/adapters/cli.py` — add `validate-field-completeness` command (headless)
- New: `tests/envmon/test_field_completeness_validator.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `datetime`, `dataclasses`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `field_completeness_validator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_field_completeness_validator.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.field_completeness_validator import (
    CompletenessIssue, CompletenessResult,
    validate_field_completeness, write_completeness_report,
)

_PLAN = [
    {"SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
    {"SampleID": "H281-MW02-20260615-GW", "LocationID": "MW-02",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
    {"SampleID": "H281-MW03-20260615-GW", "LocationID": "MW-03",
     "AnalyteGroup": "GW_VOC", "HoldTimeDays": "14",
     "CollectionDate": "2026-06-15"},
]
_RESULTS = [
    {"SampleID": "H281-MW01-20260615-GW", "AnalysisDate": "2026-06-20"},
    {"SampleID": "H281-MW02-20260615-GW", "AnalysisDate": "2026-06-22"},
    # MW-03 not in results — not sampled
    # MW-99 unexpected
    {"SampleID": "H281-MW99-20260615-GW", "AnalysisDate": "2026-06-20"},
]


def test_matched_count():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert result.matched_count == 2


def test_not_sampled():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert "H281-MW03-20260615-GW" in result.not_sampled
    assert any(i.issue_type == "not_sampled" for i in result.issues)


def test_unexpected_result():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert "H281-MW99-20260615-GW" in result.unexpected
    assert any(i.issue_type == "unexpected_result" for i in result.issues)


def test_hold_time_exceeded():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-20"}]  # 19 days
    result = validate_field_completeness(plan, results)
    assert any(i.issue_type == "hold_time_exceeded" for i in result.issues)


def test_hold_time_ok():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-10"}]  # 9 days
    result = validate_field_completeness(plan, results)
    assert not any(i.issue_type == "hold_time_exceeded" for i in result.issues)


def test_duplicate_sample_id():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-05"},
               {"SampleID": "S1", "AnalysisDate": "2026-06-05"}]
    result = validate_field_completeness(plan, results)
    assert any(i.issue_type == "duplicate_sample_id" for i in result.issues)


def test_planned_count():
    result = validate_field_completeness(_PLAN, _RESULTS)
    assert result.planned_count == 3
    assert result.received_count == 3


def test_write_completeness_report(tmp_path):
    result = validate_field_completeness(_PLAN, _RESULTS)
    out = tmp_path / "issues.csv"
    write_completeness_report(result, out)
    assert out.exists()
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) > 0
    assert "issue_type" in rows[0]


def test_all_matched_no_issues():
    plan = [{"SampleID": "S1", "LocationID": "MW-01", "AnalyteGroup": "GW_VOC",
             "HoldTimeDays": "14", "CollectionDate": "2026-06-01"}]
    results = [{"SampleID": "S1", "AnalysisDate": "2026-06-05"}]
    result = validate_field_completeness(plan, results)
    assert len(result.issues) == 0
    assert result.matched_count == 1
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_field_completeness_validator.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/field_completeness_validator.py`**

```python
"""field_completeness_validator.py — sampling plan vs. lab results completeness check."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO


@dataclass
class CompletenessIssue:
    issue_type: str
    sample_id: str
    location_id: str
    analyte_group: str
    detail: str
    severity: str


@dataclass
class CompletenessResult:
    issues: list
    planned_count: int
    received_count: int
    matched_count: int
    not_sampled: list
    unexpected: list
    hold_time_violations: int
    qa: QACollector


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def validate_field_completeness(
    plan_rows: list,
    result_rows: list,
    *,
    match_field: str = "SampleID",
    hold_time_field: str = "HoldTimeDays",
) -> CompletenessResult:
    qa = QACollector()
    issues: list = []

    plan_by_id = {r.get(match_field, ""): r for r in plan_rows}
    result_by_id: dict[str, list] = {}
    for r in result_rows:
        sid = r.get(match_field, "")
        result_by_id.setdefault(sid, []).append(r)

    plan_ids = set(plan_by_id.keys())
    result_ids = set(result_by_id.keys())

    matched = plan_ids & result_ids
    not_sampled = sorted(plan_ids - result_ids)
    unexpected = sorted(result_ids - plan_ids)
    hold_violations = 0

    for sid in not_sampled:
        pr = plan_by_id[sid]
        issues.append(CompletenessIssue(
            issue_type="not_sampled", sample_id=sid,
            location_id=pr.get("LocationID", ""),
            analyte_group=pr.get("AnalyteGroup", ""),
            detail=f"{sid} in plan but not in lab results.",
            severity="ERROR",
        ))
        qa.add(QARecord(SEV_ERROR, "not_sampled", f"{sid} not in lab results."))

    for sid in unexpected:
        issues.append(CompletenessIssue(
            issue_type="unexpected_result", sample_id=sid,
            location_id="", analyte_group="",
            detail=f"{sid} in lab results but not in plan.",
            severity="WARNING",
        ))
        qa.add(QARecord(SEV_WARNING, "unexpected_result",
                        f"{sid} in results but not in plan."))

    # Duplicate result check
    for sid, recs in result_by_id.items():
        if len(recs) > 1:
            issues.append(CompletenessIssue(
                issue_type="duplicate_sample_id", sample_id=sid,
                location_id="", analyte_group="",
                detail=f"{sid} appears {len(recs)} times in results.",
                severity="WARNING",
            ))
            qa.add(QARecord(SEV_WARNING, "duplicate_sample_id",
                            f"{sid} appears {len(recs)} times."))

    # Hold time check for matched samples
    for sid in matched:
        pr = plan_by_id[sid]
        hold_days_str = pr.get(hold_time_field, "")
        coll_date_str = pr.get("CollectionDate", "")
        for rr in result_by_id[sid]:
            analysis_date_str = rr.get("AnalysisDate", "")
            coll = _parse_date(coll_date_str)
            analysis = _parse_date(analysis_date_str)
            try:
                hold_days = int(float(hold_days_str))
            except (ValueError, TypeError):
                continue
            if coll and analysis:
                elapsed = (analysis - coll).days
                if elapsed > hold_days:
                    hold_violations += 1
                    issues.append(CompletenessIssue(
                        issue_type="hold_time_exceeded", sample_id=sid,
                        location_id=pr.get("LocationID", ""),
                        analyte_group=pr.get("AnalyteGroup", ""),
                        detail=(f"Elapsed {elapsed}d > hold time {hold_days}d "
                                f"(collected {coll_date_str}, analysed {analysis_date_str})."),
                        severity="WARNING",
                    ))
                    qa.add(QARecord(SEV_WARNING, "hold_time_exceeded",
                                    f"{sid}: {elapsed}d elapsed > {hold_days}d hold time."))

    qa.add(QARecord(SEV_INFO, "completeness_checked",
                    f"Planned: {len(plan_ids)}  Received: {len(result_ids)}  "
                    f"Matched: {len(matched)}  Not sampled: {len(not_sampled)}  "
                    f"Unexpected: {len(unexpected)}  Hold violations: {hold_violations}"))

    return CompletenessResult(
        issues=issues, planned_count=len(plan_ids),
        received_count=len(result_ids), matched_count=len(matched),
        not_sampled=not_sampled, unexpected=unexpected,
        hold_time_violations=hold_violations, qa=qa,
    )


def write_completeness_report(result: CompletenessResult, out_path: Path) -> None:
    fields = ["issue_type", "sample_id", "location_id",
              "analyte_group", "detail", "severity"]
    with Path(out_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for issue in result.issues:
            w.writerow({f: getattr(issue, f, "") for f in fields})
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_field_completeness_validator.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/field_completeness_validator.py \
        tests/envmon/test_field_completeness_validator.py
git commit -m "feat(envmon): field_completeness_validator — plan vs. lab results completeness check"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("validate-field-completeness")
@click.option("--plan", "plan_path", required=True, type=click.Path(exists=True))
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def validate_field_completeness_cmd(plan_path, results_path, out, report, fail_on):
    """Compare sampling plan vs. lab results for completeness (headless)."""
    import csv as _csv
    from autogis.core.envmon.field_completeness_validator import (
        validate_field_completeness, write_completeness_report)

    with open(plan_path, newline="", encoding="utf-8") as fh:
        plan = list(_csv.DictReader(fh))
    with open(results_path, newline="", encoding="utf-8") as fh:
        results = list(_csv.DictReader(fh))
    result = validate_field_completeness(plan, results)
    write_completeness_report(result, Path(out))
    click.echo(f"Planned: {result.planned_count}  Received: {result.received_count}  "
               f"Matched: {result.matched_count}  Issues: {len(result.issues)}  Out: {out}")
    _render_qa(result.qa, report, fail_on)
```

- [ ] **Step 2: Help test + commit**

```python
def test_validate_field_completeness_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-field-completeness" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_field_completeness_validator.py
git commit -m "feat(cli): add validate-field-completeness command"
```
