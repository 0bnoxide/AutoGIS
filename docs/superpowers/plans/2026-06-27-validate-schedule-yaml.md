# ValidateScheduleYAML (Tool 10.2 extension) — Implementation Plan

**Goal:** Add a headless `envmon validate-schedule` CLI command + core module that
reads a monitoring schedule YAML (used by `identify-data-gaps`, Tool 4.10) and
validates its structure: required fields present, all well IDs are non-empty strings,
required analytes reference known canonical names from the analyte dictionary, and
no duplicate entries. Produces a QA report without touching the actual results data.

**Architecture:** New pure-core module `autogis/core/envmon/validate_schedule.py`
with `validate_schedule(schedule, analyte_dict, *, qa) -> bool`. Returns True if
no ERRORs. A `click` command loads the YAML + optional analyte dict CSV, calls the
function, renders QA + exit via `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, `pyyaml`, stdlib `csv`, `pytest`.
Reuses: `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `validate-schedule`. Register as `Runtime.CLOUD`.
- Schedule YAML schema (same as used by `identify-data-gaps`):
  ```yaml
  site_id: "H281"
  event_label: "2026Q2"
  wells: ["MW-1", "MW-2"]
  required_analytes: ["Benzene", "Toluene"]
  well_analytes:         # optional per-well override
    MW-3: ["Ethylbenzene"]
  ```
- Validation checks:
  - `site_id` present and non-empty (ERROR `missing_site_id`)
  - `event_label` present and non-empty (ERROR `missing_event_label`)
  - `wells` is a non-empty list (ERROR `missing_wells`)
  - `required_analytes` is a list; may be empty (WARNING `no_required_analytes`)
  - Duplicate well IDs in `wells` (WARNING `duplicate_well`)
  - Unknown analyte names (not in dict) emit WARNING `unknown_analyte`
  - `well_analytes` keys not in `wells` emit WARNING `unknown_well_in_overrides`

---

### Task 1: Core module `validate_schedule.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/validate_schedule.py`
- Create: `tests/test_validate_schedule.py`

**Complete code:**

```python
"""Validate a monitoring schedule YAML (Tool 10.2 extension)."""
from __future__ import annotations
from typing import Dict, Any, Optional, Set
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def validate_schedule(
    schedule: Dict[str, Any],
    analyte_dict: Optional[Set[str]],
    *,
    qa: QACollector,
) -> bool:
    """Validate schedule dict; return True if no ERRORs emitted."""
    errors_before = sum(1 for r in qa.records
                        if r.severity in ("ERROR", "CRITICAL"))

    site_id = schedule.get("site_id", "")
    if not site_id:
        qa.add(SEV_ERROR, "missing_site_id", "Schedule missing 'site_id'")

    event_label = schedule.get("event_label", "")
    if not event_label:
        qa.add(SEV_ERROR, "missing_event_label", "Schedule missing 'event_label'")

    wells = schedule.get("wells") or []
    if not wells:
        qa.add(SEV_ERROR, "missing_wells", "Schedule 'wells' is absent or empty")
    else:
        seen = set()
        for w in wells:
            if w in seen:
                qa.add(SEV_WARNING, "duplicate_well",
                       f"Duplicate well ID {w!r} in wells list",
                       site_id=site_id)
            seen.add(w)

    required_analytes = schedule.get("required_analytes") or []
    if not required_analytes:
        qa.add(SEV_WARNING, "no_required_analytes",
               "Schedule has no required_analytes; all wells count as sampled",
               site_id=site_id)
    elif analyte_dict:
        for a in required_analytes:
            if a not in analyte_dict:
                qa.add(SEV_WARNING, "unknown_analyte",
                       f"Analyte {a!r} not in analyte dictionary",
                       site_id=site_id, analyte_name=a)

    well_analytes = schedule.get("well_analytes") or {}
    well_set = set(wells)
    for w, analytes in well_analytes.items():
        if w not in well_set:
            qa.add(SEV_WARNING, "unknown_well_in_overrides",
                   f"well_analytes key {w!r} not in wells list",
                   site_id=site_id)
        if analyte_dict:
            for a in (analytes or []):
                if a not in analyte_dict:
                    qa.add(SEV_WARNING, "unknown_analyte",
                           f"Analyte {a!r} in well_analytes override not in dict",
                           site_id=site_id, analyte_name=a)

    errors_after = sum(1 for r in qa.records
                       if r.severity in ("ERROR", "CRITICAL"))
    new_errors = errors_after - errors_before
    qa.add(SEV_INFO, "validate_schedule_complete",
           f"Schedule validation for {site_id!r} event {event_label!r}: "
           f"{new_errors} error(s)")
    return new_errors == 0
```

**Test file `tests/test_validate_schedule.py`:**

```python
"""Unit tests for validate_schedule (Tool 10.2)."""
from autogis.core.common.qa import QACollector
from autogis.core.envmon.validate_schedule import validate_schedule

GOOD = {
    "site_id": "H281",
    "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
}
DICT = {"Benzene", "Toluene", "Ethylbenzene"}


def test_valid_schedule():
    qa = QACollector()
    ok = validate_schedule(GOOD, DICT, qa=qa)
    assert ok is True
    assert not any(r.severity == "ERROR" for r in qa.records)


def test_missing_site_id():
    s = {**GOOD, "site_id": ""}
    qa = QACollector()
    ok = validate_schedule(s, DICT, qa=qa)
    assert ok is False
    assert any(r.category == "missing_site_id" for r in qa.records)


def test_duplicate_well_warns():
    s = {**GOOD, "wells": ["MW-1", "MW-1"]}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "duplicate_well" for r in qa.records)


def test_unknown_analyte_warns():
    s = {**GOOD, "required_analytes": ["Benzene", "Xylene"]}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "unknown_analyte" for r in qa.records)


def test_no_analyte_dict_skips_analyte_check():
    s = {**GOOD, "required_analytes": ["Unknown"]}
    qa = QACollector()
    ok = validate_schedule(s, None, qa=qa)
    assert ok is True  # no ERROR, just no dict to check against


def test_well_analytes_unknown_well_warns():
    s = {**GOOD, "well_analytes": {"MW-99": ["Benzene"]}}
    qa = QACollector()
    validate_schedule(s, DICT, qa=qa)
    assert any(r.category == "unknown_well_in_overrides" for r in qa.records)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `validate_schedule.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("validate-schedule")
@click.option("--schedule", "schedule_path", required=True,
              type=click.Path(exists=True))
@click.option("--analyte-dict", default=None, type=click.Path(exists=True),
              help="CSV with AnalyteCanonicalName column; optional.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def validate_schedule_cmd(schedule_path, analyte_dict, report, fail_on):
    """Tool 10.2: validate monitoring schedule YAML structure and analyte names."""
    ...
```

`capabilities.py`: `"validate-schedule": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): validate-schedule — schedule YAML structure/analyte validation (Tool 10.2)`
