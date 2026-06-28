# ValidateRTKSurvey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ValidateRTKSurvey` — RTK QA checks: precision thresholds, datum
consistency, control point residuals, duplicate point detection. Wraps `import_rtk_survey.py`
and adds a `validate-rtk-survey` CLI command. Output via `QACollector`.

**Architecture:**
- New: `autogis/core/envmon/validate_rtk_survey.py`
- Modify: `autogis/adapters/cli.py` — add `validate-rtk-survey` command (headless)
- New: `tests/envmon/test_validate_rtk_survey.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- Arcpy-free — operates on `RTKPoint` list from `import_rtk_survey.parse_rtk_csv()`.
- Depends on `import_rtk_survey.py` (Phase 4.1c plan).
- Run tests with `python -m pytest -q`.

---

### Task 1: `validate_rtk_survey.py` + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_validate_rtk_survey.py`:

```python
from autogis.core.envmon.import_rtk_survey import RTKPoint
from autogis.core.envmon.validate_rtk_survey import validate_rtk_points

_POINTS_OK = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-02", 4527750.00, 293900.00, 509.12,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]

_POINTS_POOR = [
    RTKPoint("MW-03", 4527700.00, 293850.00, 508.00,
             hrms_ft=0.15, vrms_ft=0.20, fix_type="AUTONOMOUS"),
]

_POINTS_DUP = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-01", 4527893.10, 293847.53, 512.36,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]


def test_valid_points_no_errors():
    qa = validate_rtk_points(_POINTS_OK)
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_poor_precision_warns():
    qa = validate_rtk_points(_POINTS_POOR)
    cats = [r.category for r in qa.records]
    assert "hrms_exceeds_threshold" in cats or "fix_type_not_rtk" in cats


def test_autonomous_fix_warns():
    qa = validate_rtk_points(_POINTS_POOR)
    assert any(r.category == "fix_type_not_rtk" for r in qa.records)


def test_duplicate_point_id_warns():
    qa = validate_rtk_points(_POINTS_DUP)
    assert any(r.category == "duplicate_point_id" for r in qa.records)


def test_no_points_no_error():
    qa = validate_rtk_points([])
    assert qa.counts_by_severity().get("ERROR", 0) == 0


def test_summary_record_present():
    qa = validate_rtk_points(_POINTS_OK)
    assert any(r.category == "validation_complete" for r in qa.records)


def test_custom_thresholds():
    point = RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
                     hrms_ft=0.05, vrms_ft=0.04, fix_type="RTK_FIXED")
    qa = validate_rtk_points([point], hrms_threshold_ft=0.02, vrms_threshold_ft=0.02)
    cats = [r.category for r in qa.records]
    assert "hrms_exceeds_threshold" in cats
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_validate_rtk_survey.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/validate_rtk_survey.py`**

```python
"""validate_rtk_survey.py — RTK QA checks (arcpy-free).

Operates on list[RTKPoint] from import_rtk_survey.parse_rtk_csv().
"""
from __future__ import annotations

from collections import Counter

from .import_rtk_survey import RTKPoint, assign_qa_flags
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO

_RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


def validate_rtk_points(
    points: list[RTKPoint],
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> QACollector:
    qa = QACollector()

    if not points:
        qa.add(QARecord(SEV_INFO, "validation_complete",
                        "RTK validation: 0 points — nothing to check."))
        return qa

    # Duplicate point IDs
    id_counts = Counter(p.point_id for p in points)
    for pid, n in id_counts.items():
        if n > 1:
            qa.add(QARecord(SEV_WARNING, "duplicate_point_id",
                            f"PointID {pid!r} appears {n} times."))

    # Per-point QA
    passed = 0
    for pt in points:
        flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
        if not flags:
            passed += 1
            continue
        for flag in flags:
            qa.add(QARecord(SEV_WARNING, flag,
                            f"{pt.point_id}: {flag} "
                            f"(HRMS={pt.hrms_ft}, VRMS={pt.vrms_ft}, "
                            f"FixType={pt.fix_type})"))

    qa.add(QARecord(SEV_INFO, "validation_complete",
                    f"RTK validation: {passed}/{len(points)} points QA pass."))
    return qa
```

- [ ] **Step 4: Run tests + full suite + commit**

```bash
git add autogis/core/envmon/validate_rtk_survey.py tests/envmon/test_validate_rtk_survey.py
git commit -m "feat(envmon): validate_rtk_survey — precision + fix_type + duplicate QA checks"
```

---

### Task 2: CLI command `validate-rtk-survey`

```python
@envmon.command("validate-rtk-survey")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True)
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="warning")
def validate_rtk_survey_cmd(csv_path, hrms_threshold, vrms_threshold, report, fail_on):
    """Validate an RTK survey CSV for precision and fix-type QA (headless)."""
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.validate_rtk_survey import validate_rtk_points
    points = parse_rtk_csv(Path(csv_path))
    qa = validate_rtk_points(points, hrms_threshold, vrms_threshold)
    _render_qa(qa, report, fail_on)
```

Commit:
```bash
git add autogis/adapters/cli.py tests/envmon/test_validate_rtk_survey.py
git commit -m "feat(cli): add validate-rtk-survey command (headless, default fail-on=warning)"
```
