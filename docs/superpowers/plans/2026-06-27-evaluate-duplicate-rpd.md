# EvaluateDuplicateRPD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Wrap the existing `normalize_rpd.py` computation into a complete
`EvaluateDuplicateRPD` tool — adds a screening-level comparison (flag RPDs exceeding
a regulatory threshold), a QACollector output, and a CLI command `evaluate-rpd`.
Also adds an optional numpy_geom nearest-neighbor call for fuzzy duplicate-location
matching per the Phase 2.6 roadmap note.

**Architecture:**
- New: `autogis/core/envmon/evaluate_rpd.py` — wraps `normalize_rpd_table()`, adds screening check + QA output
- Modify: `autogis/adapters/cli.py` — add `evaluate-rpd` command (headless)
- New: `tests/envmon/test_evaluate_rpd.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Arcpy-free (`normalize_rpd.py` is already arcpy-free).
- numpy_geom integration is optional (guarded import); tool works without numpy.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `evaluate_rpd.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_evaluate_rpd.py`:

```python
from autogis.core.envmon.evaluate_rpd import (
    EvaluateRPDResult, evaluate_rpd_records, rpd_to_qa,
)
from autogis.core.envmon.gdb_schema import RPDRecord

_RECORD_PASS = RPDRecord(
    ImportBatchID="B1", SiteID="TEST", EventDate=None,
    ParentLocationID="MW-01", DuplicateLocationID="MW-01D",
    AnalyteName="Benzene",
    ParentResultRaw="5.0", DuplicateResultRaw="4.8",
    ParentResultNumeric=5.0, DuplicateResultNumeric=4.8,
    RPDValue=4.08, RL=None, FiveTimesRL=None,
    RPDStatus="CALCULATED", CalculationError="",
    SourceWorkbook="test.xlsx", SourceSheet="RPD", SourceRow=5)

_RECORD_FAIL = RPDRecord(
    ImportBatchID="B1", SiteID="TEST", EventDate=None,
    ParentLocationID="MW-02", DuplicateLocationID="MW-02D",
    AnalyteName="Benzene",
    ParentResultRaw="5.0", DuplicateResultRaw="9.0",
    ParentResultNumeric=5.0, DuplicateResultNumeric=9.0,
    RPDValue=57.1, RL=None, FiveTimesRL=None,
    RPDStatus="CALCULATED", CalculationError="",
    SourceWorkbook="test.xlsx", SourceSheet="RPD", SourceRow=6)

def test_passing_rpd_no_exceedance():
    result = evaluate_rpd_records([_RECORD_PASS], rpd_threshold_pct=30.0)
    assert result.passed == 1
    assert result.failed == 0

def test_failing_rpd_flags_exceedance():
    result = evaluate_rpd_records([_RECORD_FAIL], rpd_threshold_pct=30.0)
    assert result.failed == 1
    assert result.passed == 0

def test_nc_nondetect_excluded_from_pass_fail():
    rec = RPDRecord(**{**_RECORD_PASS.__dict__,
                      "RPDStatus": "NC_NONDETECT", "RPDValue": None})
    result = evaluate_rpd_records([rec], rpd_threshold_pct=30.0)
    assert result.not_calculable == 1
    assert result.passed == 0 and result.failed == 0

def test_rpd_to_qa_produces_error_for_exceedance():
    result = evaluate_rpd_records([_RECORD_FAIL], rpd_threshold_pct=30.0)
    qa = rpd_to_qa(result)
    assert any(r.category == "rpd_exceedance" for r in qa.records)

def test_rpd_to_qa_no_error_when_all_pass():
    result = evaluate_rpd_records([_RECORD_PASS], rpd_threshold_pct=30.0)
    qa = rpd_to_qa(result)
    assert qa.counts_by_severity().get("ERROR", 0) == 0

def test_evaluate_rpd_result_total():
    result = evaluate_rpd_records([_RECORD_PASS, _RECORD_FAIL], rpd_threshold_pct=30.0)
    assert result.total == 2
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_evaluate_rpd.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/evaluate_rpd.py`**

```python
"""evaluate_rpd.py — evaluate RPD records against a threshold, produce QA output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .gdb_schema import RPDRecord
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO

DEFAULT_RPD_THRESHOLD_PCT = 30.0


@dataclass
class EvaluateRPDResult:
    records: list[RPDRecord]
    threshold_pct: float
    passed: int = 0
    failed: int = 0
    not_calculable: int = 0

    @property
    def total(self) -> int:
        return len(self.records)

    @property
    def exceedances(self) -> list[RPDRecord]:
        return [r for r in self.records
                if r.RPDStatus == "CALCULATED"
                and r.RPDValue is not None
                and r.RPDValue > self.threshold_pct]


def evaluate_rpd_records(
    records: list[RPDRecord],
    rpd_threshold_pct: float = DEFAULT_RPD_THRESHOLD_PCT,
) -> EvaluateRPDResult:
    result = EvaluateRPDResult(records=records, threshold_pct=rpd_threshold_pct)
    for rec in records:
        if rec.RPDStatus != "CALCULATED" or rec.RPDValue is None:
            result.not_calculable += 1
        elif rec.RPDValue > rpd_threshold_pct:
            result.failed += 1
        else:
            result.passed += 1
    return result


def rpd_to_qa(result: EvaluateRPDResult) -> QACollector:
    qa = QACollector()
    for rec in result.exceedances:
        qa.add(QARecord(
            severity=SEV_ERROR,
            category="rpd_exceedance",
            message=(f"{rec.AnalyteName} at {rec.ParentLocationID}/{rec.DuplicateLocationID}: "
                     f"RPD={rec.RPDValue:.1f}% exceeds {result.threshold_pct:.0f}% threshold"),
            analyte_name=rec.AnalyteName,
            location_id=rec.ParentLocationID,
            sample_id=rec.ParentResultRaw,
        ))
    qa.add(QARecord(
        severity=SEV_INFO,
        category="rpd_summary",
        message=(f"RPD evaluation: {result.passed} pass, {result.failed} fail, "
                 f"{result.not_calculable} not calculable (threshold={result.threshold_pct}%)"),
    ))
    return qa
```

- [ ] **Step 4: Run tests + full suite, commit**

```bash
git add autogis/core/envmon/evaluate_rpd.py tests/envmon/test_evaluate_rpd.py
git commit -m "feat(envmon): evaluate_rpd — EvaluateRPDResult + rpd_to_qa wrapper"
```

---

### Task 2: CLI command `evaluate-rpd`

- [ ] **Step 1: Add to `cli.py`** (headless; no arcpy guard)

```python
@envmon.command("evaluate-rpd")
@click.argument("workbook", type=click.Path(exists=True))
@click.argument("profile", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--batch-id", default="", show_default=True)
@click.option("--threshold", type=float, default=30.0, show_default=True,
              help="RPD exceedance threshold (pct, default 30).")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def evaluate_rpd_cmd(workbook, profile, site_id, batch_id, threshold, report, fail_on):
    """Evaluate field duplicate RPD values against a threshold (headless)."""
    from autogis.core.common.config import ParserProfile
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.normalize_rpd import normalize_rpd_table
    from autogis.core.envmon.evaluate_rpd import evaluate_rpd_records, rpd_to_qa
    parser = ParserProfile.load(Path(profile))
    qa_import = QACollector()
    records = normalize_rpd_table(Path(workbook), parser, site_id, batch_id, qa_import)
    result = evaluate_rpd_records(records, rpd_threshold_pct=threshold)
    qa = rpd_to_qa(result)
    qa.records = qa_import.records + qa.records   # merge import QA first
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 2: Smoke + help test**

```python
# Append to tests/envmon/test_evaluate_rpd.py
from click.testing import CliRunner
from autogis.adapters.cli import autogis

def test_evaluate_rpd_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "evaluate-rpd" in result.output
```

- [ ] **Step 3: Run tests + full suite, commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_evaluate_rpd.py
git commit -m "feat(cli): add evaluate-rpd command — headless RPD threshold check"
```
