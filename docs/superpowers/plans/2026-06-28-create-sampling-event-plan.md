# CreateSamplingEventPlan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `CreateSamplingEventPlan` (roadmap 7.2) — a headless, arcpy-free module that determines which wells and analytes are due for a proposed sampling event based on monitoring frequency rules and prior sampling history, and emits the event schedule YAML consumed by downstream tools.

**Architecture:**
- New: `autogis/core/envmon/sampling_event_plan.py` — all frequency logic, dataclasses, CSV/YAML writers (no arcpy, no GDB write tier).
- New: `autogis/config/monitoring_schedules/monitoring_program.example.yaml` — canonical input format example.
- New: `tests/envmon/test_sampling_event_plan.py` — unit tests + three-consumer round-trip integration tests.
- Modify: `autogis/adapters/cli.py` — add `envmon create-sampling-event-plan` command.

**Tech Stack:** Python stdlib (`csv`, `dataclasses`, `pathlib`, `datetime`), PyYAML (already in ArcGIS Pro conda env), `click` (CLI), no `arcpy`/`arcgis`.

## Global Constraints

- **Arcpy-free invariant:** `autogis/core/` and `autogis/adapters/` must import with neither `arcpy` nor `arcgis` present — all code in this plan must satisfy this.
- **TDD:** every step writes the failing test first, confirms it fails, then writes the implementation.
- **Tests run with:** `python -m pytest -q`
- **PyYAML import:** guarded behind `import yaml` inside functions (same pattern as `schedule_vs_actual.py`), not at module top level.
- **Output contract (non-negotiable):** `write_event_schedule_yaml()` must emit exactly `site_id`, `event_label`, `wells`, `required_analytes`, `well_analytes` — the keys consumed verbatim by `validate_schedule`, `schedule_vs_actual`, and `data_gaps`.
- **Scope — 7.2 vs 2.7:** This plan implements the event PLAN (which wells/analytes are due). `CreateSurvey123SamplingEvent` (2.7) is a separate downstream tool that consumes 7.2's output YAML to generate Survey123 records, AGOL hosted layer rows, crew assignments, and full COC tables. Do not implement 2.7's scope here.
- **Non-goals (out of scope for this plan):**
  - Roadmap "field map layer" output (requires arcpy — belongs to a LOCAL tier if ever added).
  - AGOL/Survey123 write operations (belong to 2.7).
  - GDB table write tier (no `SamplingEventPlan` table exists in schema; this is a file-output-only tool).
  - Calendar-quarter boundary logic (Q1 = Jan–Mar, etc.) — day-threshold model is an acceptable simplification, documented inline.

---

## File Layout

| Path | Create / Modify | Responsibility |
|---|---|---|
| `autogis/core/envmon/sampling_event_plan.py` | Create | All core logic: dataclasses, frequency constants, loaders, `create_sampling_event_plan()`, CSV/YAML writers |
| `autogis/config/monitoring_schedules/monitoring_program.example.yaml` | Create | Canonical example of the monitoring program input YAML |
| `tests/envmon/test_sampling_event_plan.py` | Create | Unit tests (Tasks 1–2) + round-trip integration tests (Task 2) |
| `autogis/adapters/cli.py` | Modify | Add `envmon create-sampling-event-plan` command (Task 3) |

---

### Task 1: Core module — dataclasses, frequency logic, loaders, writers

**Files:**
- Create: `autogis/core/envmon/sampling_event_plan.py`
- Create: `autogis/config/monitoring_schedules/monitoring_program.example.yaml`
- Test: `tests/envmon/test_sampling_event_plan.py`

**Interfaces:**
- Produces for Task 2:
  - `MonitoringProgram`, `SamplingEventPlan`, `PlannedSampleRow` dataclasses
  - `load_monitoring_program_yaml(path: Path) -> MonitoringProgram`
  - `load_prior_events_csv(path: Path) -> Dict[str, date]`
  - `_is_due(frequency: str, last_sampled: Optional[date], event_date: date) -> Tuple[bool, str]`
  - `create_sampling_event_plan(program, event_date, prior_dates, event_label, *, qa) -> SamplingEventPlan`
  - `write_plan_csv(plan: SamplingEventPlan, path: Path) -> None`
  - `write_coc_csv(plan: SamplingEventPlan, path: Path) -> None`
  - `write_event_schedule_yaml(plan: SamplingEventPlan, path: Path) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_sampling_event_plan.py`:

```python
"""Unit tests for sampling_event_plan.py (Tool 7.2 — CreateSamplingEventPlan).

Integration / round-trip tests (using validate_schedule, schedule_vs_actual,
data_gaps) live in Task 2 below; they are in this same file so all tests
run in one pytest pass.
"""
import csv
import pytest
from datetime import date
from pathlib import Path
from typing import Dict

import yaml

from autogis.core.envmon.sampling_event_plan import (
    FREQUENCY_THRESHOLDS_DAYS,
    AnalyteGroupDef,
    MonitoringProgram,
    PlannedSampleRow,
    SamplingEventPlan,
    WellSchedule,
    _is_due,
    create_sampling_event_plan,
    load_monitoring_program_yaml,
    load_prior_events_csv,
    write_coc_csv,
    write_event_schedule_yaml,
    write_plan_csv,
)
from autogis.core.common.qa import QACollector, SEV_WARNING


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_program() -> MonitoringProgram:
    """Minimal two-well program for unit tests."""
    vocs = AnalyteGroupDef(name="VOCs", analytes=["Benzene", "Toluene"],
                           bottles=2, preservation="HCl")
    metals = AnalyteGroupDef(name="Metals", analytes=["Arsenic", "Iron"],
                             bottles=1, preservation="HNO3")
    return MonitoringProgram(
        site_id="H281",
        program_name="Test Program",
        analyte_groups={"VOCs": vocs, "Metals": metals},
        wells=[
            WellSchedule(location_id="MW-1", frequency="quarterly",
                         analyte_groups=["VOCs", "Metals"], matrix="GW"),
            WellSchedule(location_id="MW-2", frequency="semi-annual",
                         analyte_groups=["VOCs"], matrix="GW"),
        ],
    )


_EVENT_DATE = date(2026, 6, 15)


def _make_plan(program=None, prior_dates=None, event_label="2026-Q2") -> SamplingEventPlan:
    prog = program or _make_program()
    prior = prior_dates if prior_dates is not None else {}
    qa = QACollector()
    return create_sampling_event_plan(
        prog, _EVENT_DATE, prior, event_label, qa=qa
    )


# ---------------------------------------------------------------------------
# Task 1a: load_monitoring_program_yaml
# ---------------------------------------------------------------------------

_PROG_YAML = """\
site_id: H281
program_name: H281 Test

analyte_groups:
  VOCs:
    analytes: [Benzene, Toluene]
    bottles: 2
    preservation: HCl
  Metals:
    analytes: [Arsenic, Iron]
    bottles: 1
    preservation: HNO3

wells:
  - location_id: MW-1
    frequency: quarterly
    analyte_groups: [VOCs, Metals]
    matrix: GW
    access_note: ""
  - location_id: MW-2
    frequency: semi-annual
    analyte_groups: [VOCs]
    matrix: GW
"""


def test_load_monitoring_program_yaml(tmp_path):
    p = tmp_path / "prog.yaml"
    p.write_text(_PROG_YAML, encoding="utf-8")
    prog = load_monitoring_program_yaml(p)
    assert prog.site_id == "H281"
    assert prog.program_name == "H281 Test"
    assert len(prog.wells) == 2
    assert prog.wells[0].location_id == "MW-1"
    assert prog.wells[0].frequency == "quarterly"
    assert prog.wells[0].analyte_groups == ["VOCs", "Metals"]
    assert "VOCs" in prog.analyte_groups
    assert prog.analyte_groups["VOCs"].bottles == 2
    assert prog.analyte_groups["Metals"].analytes == ["Arsenic", "Iron"]


def test_load_monitoring_program_yaml_access_note(tmp_path):
    yaml_with_note = _PROG_YAML.replace('access_note: ""',
                                        'access_note: "Requires landowner access"')
    p = tmp_path / "prog_note.yaml"
    p.write_text(yaml_with_note, encoding="utf-8")
    prog = load_monitoring_program_yaml(p)
    assert prog.wells[0].access_note == "Requires landowner access"


# ---------------------------------------------------------------------------
# Task 1b: load_prior_events_csv
# ---------------------------------------------------------------------------

def test_load_prior_events_csv(tmp_path):
    p = tmp_path / "prior.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "last_sampled_date"])
        w.writeheader()
        w.writerow({"location_id": "MW-1", "last_sampled_date": "2026-03-10"})
        w.writerow({"location_id": "MW-2", "last_sampled_date": "2025-12-01"})
    prior = load_prior_events_csv(p)
    assert prior["MW-1"] == date(2026, 3, 10)
    assert prior["MW-2"] == date(2025, 12, 1)


def test_load_prior_events_csv_skips_bad_dates(tmp_path):
    p = tmp_path / "prior_bad.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "last_sampled_date"])
        w.writeheader()
        w.writerow({"location_id": "MW-1", "last_sampled_date": "not-a-date"})
        w.writerow({"location_id": "MW-2", "last_sampled_date": ""})
    prior = load_prior_events_csv(p)
    assert "MW-1" not in prior
    assert "MW-2" not in prior


# ---------------------------------------------------------------------------
# Task 1c: _is_due
# ---------------------------------------------------------------------------

def test_is_due_never_sampled():
    is_due, reason = _is_due("quarterly", None, _EVENT_DATE)
    assert is_due is True
    assert reason == "never_sampled"


def test_is_due_always_ignores_elapsed_time():
    # Even if sampled yesterday, "always" means due.
    is_due, reason = _is_due("always", date(2026, 6, 14), _EVENT_DATE)
    assert is_due is True
    assert reason == "always_due"


def test_is_due_quarterly_elapsed():
    # 97 days elapsed > 75-day threshold → due.
    last = date(2026, 3, 10)  # 97 days before 2026-06-15
    is_due, reason = _is_due("quarterly", last, _EVENT_DATE)
    assert is_due is True
    assert reason == "frequency_elapsed"


def test_is_due_quarterly_not_elapsed():
    # 30 days elapsed < 75-day threshold → not due.
    last = date(2026, 5, 16)  # 30 days before 2026-06-15
    is_due, reason = _is_due("quarterly", last, _EVENT_DATE)
    assert is_due is False
    assert reason == "not_due"


def test_is_due_semi_annual_elapsed():
    # 200 days elapsed > 150-day threshold → due.
    last = date(2025, 11, 27)  # 200 days before 2026-06-15
    is_due, reason = _is_due("semi-annual", last, _EVENT_DATE)
    assert is_due is True
    assert reason == "frequency_elapsed"


def test_is_due_annual_elapsed():
    # 365 days elapsed > 335-day threshold → due.
    last = date(2025, 6, 15)  # 365 days before 2026-06-15
    is_due, reason = _is_due("annual", last, _EVENT_DATE)
    assert is_due is True
    assert reason == "frequency_elapsed"


def test_is_due_annual_not_elapsed():
    # 280 days elapsed < 335-day threshold → not due.
    last = date(2025, 9, 8)  # 280 days before 2026-06-15
    is_due, reason = _is_due("annual", last, _EVENT_DATE)
    assert is_due is False
    assert reason == "not_due"


def test_is_due_biennial_elapsed():
    # 700 days elapsed > 660-day threshold → due.
    last = date(2024, 6, 10)  # ~736 days
    is_due, reason = _is_due("biennial", last, _EVENT_DATE)
    assert is_due is True
    assert reason == "frequency_elapsed"


# ---------------------------------------------------------------------------
# Task 1d: create_sampling_event_plan
# ---------------------------------------------------------------------------

def test_create_plan_no_prior_all_wells_due():
    """With no prior events every well is planned as due."""
    plan = _make_plan(prior_dates={})
    assert set(plan.due_wells) == {"MW-1", "MW-2"}
    assert plan.excluded_wells == []


def test_create_plan_frequency_filters_mw2():
    """MW-2 semi-annual: 30 days elapsed → not due; MW-1 quarterly: 97 days → due."""
    prior = {
        "MW-1": date(2026, 3, 10),  # 97 days → quarterly due
        "MW-2": date(2026, 5, 16),  # 30 days → semi-annual NOT due
    }
    plan = _make_plan(prior_dates=prior)
    assert "MW-1" in plan.due_wells
    assert "MW-2" not in plan.due_wells
    assert "MW-2" in plan.not_due_wells


def test_create_plan_access_constrained_well_excluded():
    prog = _make_program()
    prog.wells[0] = WellSchedule(location_id="MW-1", frequency="quarterly",
                                 analyte_groups=["VOCs"], matrix="GW",
                                 access_note="Locked gate — crew cannot access")
    plan = _make_plan(program=prog, prior_dates={})
    assert "MW-1" not in plan.due_wells
    assert "MW-1" in plan.excluded_wells
    # Access-constrained wells still appear in rows (for visibility).
    constrained = [r for r in plan.rows if r.LocationID == "MW-1"]
    assert constrained, "access-constrained well must still appear in rows"
    assert all(r.DueReason == "access_constraint" for r in constrained)


def test_create_plan_never_sampled_emits_qa_warning():
    qa = QACollector()
    prog = _make_program()
    create_sampling_event_plan(prog, _EVENT_DATE, {}, "2026-Q2", qa=qa)
    warnings = [r for r in qa.records if r.severity == SEV_WARNING
                and r.category == "no_prior_event_data"]
    assert len(warnings) >= 2, "Expected one warning per never-sampled well"
    loc_ids = {r.location_id for r in warnings}
    assert "MW-1" in loc_ids
    assert "MW-2" in loc_ids


def test_create_plan_unknown_analyte_group_emits_warning():
    qa = QACollector()
    prog = _make_program()
    # Give MW-1 a group that doesn't exist in program.analyte_groups.
    prog.wells[0] = WellSchedule(location_id="MW-1", frequency="always",
                                 analyte_groups=["UNKNOWN_GROUP"], matrix="GW")
    create_sampling_event_plan(prog, _EVENT_DATE, {}, "2026-Q2", qa=qa)
    cats = {r.category for r in qa.records if r.severity == SEV_WARNING}
    assert "unknown_analyte_group" in cats


def test_create_plan_row_fields():
    """Spot-check field values on a due row."""
    prior = {"MW-1": date(2026, 3, 10)}  # 97 days → quarterly due
    plan = _make_plan(prior_dates=prior)
    mw1_rows = [r for r in plan.rows if r.LocationID == "MW-1" and r.IsDue]
    assert mw1_rows, "MW-1 should have at least one due row"
    row = mw1_rows[0]
    assert row.SiteID == "H281"
    assert row.Matrix == "GW"
    assert row.EstimatedBottles > 0
    assert row.DaysSinceLastSampled == 97


# ---------------------------------------------------------------------------
# Task 1e: write_plan_csv
# ---------------------------------------------------------------------------

def test_write_plan_csv_roundtrip(tmp_path):
    plan = _make_plan(prior_dates={})
    out = tmp_path / "plan.csv"
    write_plan_csv(plan, out)
    assert out.exists()
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(plan.rows)
    # Every row must have LocationID and AnalyteCanonicalName.
    for row in rows:
        assert row["LocationID"]
        assert row["AnalyteCanonicalName"]


def test_write_plan_csv_contains_due_and_not_due(tmp_path):
    """Plan CSV includes all rows (due, not-due, excluded) for full visibility."""
    prior = {
        "MW-1": date(2026, 3, 10),  # due
        "MW-2": date(2026, 5, 16),  # not due
    }
    plan = _make_plan(prior_dates=prior)
    out = tmp_path / "plan_mixed.csv"
    write_plan_csv(plan, out)
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    due_reasons = {r["DueReason"] for r in rows}
    assert "frequency_elapsed" in due_reasons
    assert "not_due" in due_reasons


# ---------------------------------------------------------------------------
# Task 1f: write_coc_csv
# ---------------------------------------------------------------------------

def test_write_coc_csv_only_due_wells(tmp_path):
    """COC draft must not include not-due or access-constrained wells."""
    prior = {
        "MW-1": date(2026, 3, 10),  # due
        "MW-2": date(2026, 5, 16),  # not due
    }
    plan = _make_plan(prior_dates=prior)
    out = tmp_path / "coc.csv"
    write_coc_csv(plan, out)
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    locs = {r["LocationID"] for r in rows}
    assert "MW-1" in locs
    assert "MW-2" not in locs


def test_write_coc_csv_draft_sample_id_pattern(tmp_path):
    plan = _make_plan(prior_dates={})
    out = tmp_path / "coc2.csv"
    write_coc_csv(plan, out)
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        # SampleID_Draft must contain site_id, event_label, LocationID, Matrix.
        sid = row["SampleID_Draft"]
        assert "H281" in sid
        assert "2026-Q2" in sid
        assert row["LocationID"] in sid


def test_write_coc_csv_has_all_required_columns(tmp_path):
    plan = _make_plan(prior_dates={})
    out = tmp_path / "coc3.csv"
    write_coc_csv(plan, out)
    with out.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames is not None
        for col in ["SiteID", "EventLabel", "ProposedEventDate", "LocationID",
                    "Matrix", "SampleID_Draft", "AnalyteGroup",
                    "AnalyteCanonicalName", "EstimatedBottles", "Preservation"]:
            assert col in reader.fieldnames, f"Missing COC column: {col}"


# ---------------------------------------------------------------------------
# Task 1g: write_event_schedule_yaml — output contract tests
# ---------------------------------------------------------------------------

def test_write_event_schedule_yaml_has_required_keys(tmp_path):
    """Output YAML must contain exactly the keys consumed by downstream tools."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "schedule.yaml"
    write_event_schedule_yaml(plan, out)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for key in ("site_id", "event_label", "wells", "required_analytes", "well_analytes"):
        assert key in doc, f"Missing key in output YAML: {key!r}"


def test_write_event_schedule_yaml_only_due_wells(tmp_path):
    """wells list must contain only due + accessible wells."""
    prior = {
        "MW-1": date(2026, 3, 10),  # due
        "MW-2": date(2026, 5, 16),  # not due
    }
    plan = _make_plan(prior_dates=prior)
    out = tmp_path / "schedule2.yaml"
    write_event_schedule_yaml(plan, out)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "MW-1" in doc["wells"]
    assert "MW-2" not in doc["wells"]


def test_write_event_schedule_yaml_every_due_well_in_well_analytes(tmp_path):
    """Every well in 'wells' must also appear in 'well_analytes'."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "schedule3.yaml"
    write_event_schedule_yaml(plan, out)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for well in doc["wells"]:
        assert well in doc["well_analytes"], (
            f"Well {well!r} in 'wells' but missing from 'well_analytes' — "
            "downstream consumers (data_gaps, validate_schedule) will use the "
            "fallback required_analytes instead of the per-well list."
        )


def test_write_event_schedule_yaml_required_analytes_non_empty(tmp_path):
    """required_analytes must be non-empty to avoid validate_schedule WARNING."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "schedule4.yaml"
    write_event_schedule_yaml(plan, out)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["required_analytes"], "required_analytes must not be empty"


def test_write_event_schedule_yaml_well_analytes_is_superset(tmp_path):
    """Each well's analyte list in well_analytes must include all due analytes for that well."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "schedule5.yaml"
    write_event_schedule_yaml(plan, out)
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    for well in doc["wells"]:
        # Compute expected analytes for this well from the plan rows.
        expected = {r.AnalyteCanonicalName for r in plan.rows
                    if r.LocationID == well and r.IsDue
                    and r.DueReason != "access_constraint"}
        actual = set(doc["well_analytes"][well])
        assert actual >= expected, (
            f"well_analytes[{well!r}] is missing analytes: {expected - actual}"
        )
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest tests/envmon/test_sampling_event_plan.py -v
```

Expected: `ImportError: cannot import name 'sampling_event_plan' from 'autogis.core.envmon'` (module does not exist yet).

- [ ] **Step 3: Create the example YAML config**

Create `autogis/config/monitoring_schedules/monitoring_program.example.yaml`:

```yaml
# Monitoring program configuration — CreateSamplingEventPlan (Tool 7.2) input.
# Copy this file and edit for your site. Reference with --program on the CLI.
#
# Key: monitoring_program.yaml defines WHAT to sample at WHAT frequency.
#      The CLI derives WHICH wells are due for a specific event date from this.
#
# Downstream: write_event_schedule_yaml() converts this plan into the event
# schedule format consumed by validate_schedule, schedule_vs_actual, data_gaps.

site_id: H281
program_name: "H281 Glasgow Quarterly Monitoring"

# Analyte group definitions.
# Each group names the canonical analytes (must match analyte_dictionary.yaml),
# estimated bottle count per sample location, and preservation method.
analyte_groups:
  VOCs:
    analytes:
      - Benzene
      - Toluene
      - Ethylbenzene
      - "Total Xylenes"
      - MTBE
    bottles: 2          # two 40 mL VOA vials per well
    preservation: "HCl"

  Metals:
    analytes:
      - Arsenic
      - Iron
      - Manganese
    bottles: 1
    preservation: "HNO3"

  FieldParameters:
    analytes:
      - pH
      - Temperature
      - Specific Conductance
      - DO
      - ORP
    bottles: 0          # field measurements — no lab bottles
    preservation: ""

# Per-well monitoring requirements.
# frequency: always | quarterly | semi-annual | annual | biennial
# analyte_groups: list of group names defined in analyte_groups above
# access_note: leave empty ("") if accessible; populate if constrained
wells:
  - location_id: MW-1
    frequency: quarterly
    analyte_groups: [VOCs, Metals, FieldParameters]
    matrix: GW
    access_note: ""

  - location_id: MW-2
    frequency: quarterly
    analyte_groups: [VOCs, FieldParameters]
    matrix: GW
    access_note: ""

  - location_id: MW-3
    frequency: semi-annual
    analyte_groups: [VOCs, FieldParameters]
    matrix: GW
    access_note: ""

  - location_id: MW-4
    frequency: annual
    analyte_groups: [VOCs, Metals, FieldParameters]
    matrix: GW
    access_note: "Requires landowner access — contact 30 days prior"

  - location_id: MW-5
    frequency: always       # sentinel well — always sampled regardless of schedule
    analyte_groups: [VOCs, FieldParameters]
    matrix: GW
    access_note: ""
```

- [ ] **Step 4: Create `autogis/core/envmon/sampling_event_plan.py`**

```python
"""sampling_event_plan.py — CreateSamplingEventPlan (Tool 7.2).

Determines which wells and analytes are due for a proposed sampling event
based on monitoring frequency rules and prior sampling history.

Strictly headless (no arcpy, no AGOL, no GDB write tier).

Scope boundary
--------------
7.2 (this module) — event PLAN: which wells/analytes are DUE based on
  frequency rules and prior history. Primary output is an event schedule
  YAML consumable by validate_schedule, schedule_vs_actual, and data_gaps.
  Secondary outputs: planned-wells CSV, optional COC draft CSV.

2.7 (CreateSurvey123SamplingEvent) — Survey123 pre-field package builder:
  takes the planned event YAML produced here and generates Survey123
  feature records, AGOL hosted layer rows, field crew assignments, and
  final COC tables. Not in scope here.

Roadmap "field map layer" output requires arcpy and is intentionally
deferred to a LOCAL-tier addition; it is not part of this module.

Output contract
---------------
write_event_schedule_yaml() emits a YAML with these exact keys (required
by all three downstream consumers — validate_schedule, schedule_vs_actual,
data_gaps):

    site_id:            str
    event_label:        str
    wells:              list[str]          # due + accessible wells ONLY
    required_analytes:  list[str]          # union of all due analytes (non-empty
                                           # fallback; well_analytes covers every well)
    well_analytes:      dict[str, list[str]]  # every due well with its exact analyte list

WHY well_analytes covers every well: both schedule_vs_actual.py and
data_gaps.py compute `required = well_analytes.get(well, required_analytes)`.
Putting every due well in well_analytes ensures the per-well exact list is
used rather than the union fallback. required_analytes remains non-empty so
validate_schedule does not emit a 'no_required_analytes' WARNING.
"""
from __future__ import annotations

import csv
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING


# ---------------------------------------------------------------------------
# Frequency thresholds (day-threshold model)
# Assumption: no calendar-quarter logic (Q1 = Jan–Mar, etc.). A well is "due"
# when the elapsed days since last sampling >= threshold. Thresholds include a
# ~10 % grace window so slightly early prior sampling does not push a well
# out of scope for the current event.
# To switch to calendar-quarter logic, replace _is_due() and update these
# constants accordingly.
# ---------------------------------------------------------------------------
FREQUENCY_THRESHOLDS_DAYS: Dict[str, int] = {
    "always":      0,    # due regardless of elapsed time
    "quarterly":   75,   # nominally 90 days; 15-day grace window
    "semi-annual": 150,  # nominally 180 days; 30-day grace window
    "annual":      335,  # nominally 365 days; 30-day grace window
    "biennial":    660,  # nominally 730 days; 70-day grace window
}


@dataclass
class AnalyteGroupDef:
    """Definition of a reusable analyte group."""
    name: str
    analytes: List[str]
    bottles: int = 1
    preservation: str = ""


@dataclass
class WellSchedule:
    """Per-well monitoring requirements for a monitoring program."""
    location_id: str
    frequency: str              # key in FREQUENCY_THRESHOLDS_DAYS
    analyte_groups: List[str]   # group names from MonitoringProgram.analyte_groups
    matrix: str = "GW"
    access_note: str = ""       # empty = accessible; non-empty = flagged as constrained


@dataclass
class MonitoringProgram:
    """Full monitoring program configuration loaded from YAML."""
    site_id: str
    program_name: str
    analyte_groups: Dict[str, AnalyteGroupDef]
    wells: List[WellSchedule]


@dataclass
class PlannedSampleRow:
    """One row in the planned sampling event table (one well × one analyte)."""
    SiteID: str
    LocationID: str
    Matrix: str
    FrequencyRule: str
    DaysSinceLastSampled: Optional[int]  # None = never sampled before this event
    IsDue: bool
    DueReason: str  # "never_sampled" | "frequency_elapsed" | "always_due"
                    # | "not_due" | "access_constraint"
    AnalyteGroup: str
    AnalyteCanonicalName: str
    EstimatedBottles: int       # 0 for not-due or access-constrained rows
    Preservation: str
    AccessNote: str             # populated only for access_constraint rows


@dataclass
class SamplingEventPlan:
    """Output of create_sampling_event_plan()."""
    site_id: str
    event_label: str
    proposed_event_date: date
    rows: List[PlannedSampleRow]

    @property
    def due_wells(self) -> List[str]:
        """LocationIDs that are due and accessible (ordered)."""
        return sorted({r.LocationID for r in self.rows
                       if r.IsDue and r.DueReason != "access_constraint"})

    @property
    def excluded_wells(self) -> List[str]:
        """LocationIDs excluded due to access constraints (ordered)."""
        return sorted({r.LocationID for r in self.rows
                       if r.DueReason == "access_constraint"})

    @property
    def not_due_wells(self) -> List[str]:
        """LocationIDs present in program but not due this event (ordered)."""
        return sorted({r.LocationID for r in self.rows
                       if r.DueReason == "not_due"})


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_monitoring_program_yaml(path: Path) -> MonitoringProgram:
    """Load a monitoring program configuration from a YAML file.

    See autogis/config/monitoring_schedules/monitoring_program.example.yaml
    for the required format.
    """
    import yaml  # PyYAML — deferred import, always present in ArcGIS Pro env

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    ag_raw = raw.get("analyte_groups") or {}
    analyte_groups: Dict[str, AnalyteGroupDef] = {}
    for name, ag in ag_raw.items():
        analyte_groups[name] = AnalyteGroupDef(
            name=name,
            analytes=list(ag.get("analytes") or []),
            bottles=int(ag.get("bottles", 1)),
            preservation=str(ag.get("preservation") or ""),
        )

    wells: List[WellSchedule] = []
    for w in (raw.get("wells") or []):
        wells.append(WellSchedule(
            location_id=str(w.get("location_id") or ""),
            frequency=str(w.get("frequency") or "always").lower(),
            analyte_groups=list(w.get("analyte_groups") or []),
            matrix=str(w.get("matrix") or "GW"),
            access_note=str(w.get("access_note") or ""),
        ))

    return MonitoringProgram(
        site_id=str(raw.get("site_id") or ""),
        program_name=str(raw.get("program_name") or ""),
        analyte_groups=analyte_groups,
        wells=wells,
    )


def load_prior_events_csv(path: Path) -> Dict[str, date]:
    """Load last-sampled dates from a two-column CSV (location_id, last_sampled_date).

    Rows with missing or unparseable dates are skipped silently.
    Alternative: derive prior dates from a full Env_AnalyticalResults CSV using
    derive_prior_dates_from_results() if a full results export is available.
    """
    prior: Dict[str, date] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            loc = (row.get("location_id") or "").strip()
            raw_d = (row.get("last_sampled_date") or "").strip()
            if not loc or not raw_d:
                continue
            try:
                prior[loc] = date.fromisoformat(raw_d)
            except ValueError:
                pass
    return prior


# ---------------------------------------------------------------------------
# Frequency logic
# ---------------------------------------------------------------------------

def _is_due(
    frequency: str,
    last_sampled: Optional[date],
    event_date: date,
) -> Tuple[bool, str]:
    """Return (is_due, due_reason) for a well.

    Args:
        frequency: key in FREQUENCY_THRESHOLDS_DAYS ("quarterly", etc.).
        last_sampled: date of most recent prior sampling, or None if never sampled.
        event_date: proposed event date.

    Returns:
        (True, "never_sampled")       — never sampled; treat as due.
        (True, "always_due")          — frequency == "always".
        (True, "frequency_elapsed")   — elapsed days >= threshold.
        (False, "not_due")            — elapsed days < threshold.
    """
    if last_sampled is None:
        return True, "never_sampled"
    threshold = FREQUENCY_THRESHOLDS_DAYS.get(frequency, 0)
    if threshold == 0:
        return True, "always_due"
    elapsed = (event_date - last_sampled).days
    if elapsed >= threshold:
        return True, "frequency_elapsed"
    return False, "not_due"


# ---------------------------------------------------------------------------
# Core planner
# ---------------------------------------------------------------------------

def create_sampling_event_plan(
    program: MonitoringProgram,
    proposed_event_date: date,
    prior_dates: Dict[str, date],
    event_label: str,
    *,
    qa: QACollector,
) -> SamplingEventPlan:
    """Compute the planned sampling event from a monitoring program and prior dates.

    For each well in the program:
      - access_note non-empty  → included in rows with DueReason="access_constraint",
                                  IsDue=False. QA WARNING emitted.
      - never in prior_dates   → IsDue=True, DueReason="never_sampled". QA WARNING.
      - frequency rule says due → IsDue=True, DueReason="frequency_elapsed"/"always_due".
      - otherwise              → IsDue=False, DueReason="not_due".

    Rows include every (well × analyte) combination — both due and not-due — for
    full visibility. write_event_schedule_yaml() filters to due-only wells.

    Args:
        program: MonitoringProgram loaded from YAML.
        proposed_event_date: date of the planned event.
        prior_dates: dict of LocationID → last sampled date (empty = treat all as first event).
        event_label: short label for the event (e.g. "2026-Q2"); written to output YAML.
        qa: QACollector for warnings and summary messages.

    Returns:
        SamplingEventPlan with rows for every well × analyte.
    """
    rows: List[PlannedSampleRow] = []

    for ws in program.wells:
        loc = ws.location_id

        # Access-constrained: include rows for visibility but mark as excluded.
        if ws.access_note:
            for group_name in ws.analyte_groups:
                ag = program.analyte_groups.get(group_name)
                if ag is None:
                    continue
                for analyte in ag.analytes:
                    rows.append(PlannedSampleRow(
                        SiteID=program.site_id,
                        LocationID=loc,
                        Matrix=ws.matrix,
                        FrequencyRule=ws.frequency,
                        DaysSinceLastSampled=None,
                        IsDue=False,
                        DueReason="access_constraint",
                        AnalyteGroup=group_name,
                        AnalyteCanonicalName=analyte,
                        EstimatedBottles=0,
                        Preservation="",
                        AccessNote=ws.access_note,
                    ))
            qa.add(SEV_WARNING, "access_constraint",
                   f"Well {loc!r} excluded from plan: {ws.access_note}",
                   site_id=program.site_id, location_id=loc)
            continue

        # Warn when no prior sampling history is available.
        last_sampled = prior_dates.get(loc)
        if last_sampled is None:
            qa.add(SEV_WARNING, "no_prior_event_data",
                   f"Well {loc!r} has no prior sampling history; planned as due. "
                   f"Confirm this is the first event for this well.",
                   site_id=program.site_id, location_id=loc)

        is_due, due_reason = _is_due(ws.frequency, last_sampled, proposed_event_date)
        days_elapsed = (
            (proposed_event_date - last_sampled).days if last_sampled else None
        )

        for group_name in ws.analyte_groups:
            ag = program.analyte_groups.get(group_name)
            if ag is None:
                qa.add(SEV_WARNING, "unknown_analyte_group",
                       f"Well {loc!r}: analyte group {group_name!r} is not defined "
                       f"in the monitoring program's analyte_groups.",
                       site_id=program.site_id, location_id=loc)
                continue
            for analyte in ag.analytes:
                rows.append(PlannedSampleRow(
                    SiteID=program.site_id,
                    LocationID=loc,
                    Matrix=ws.matrix,
                    FrequencyRule=ws.frequency,
                    DaysSinceLastSampled=days_elapsed,
                    IsDue=is_due,
                    DueReason=due_reason,
                    AnalyteGroup=group_name,
                    AnalyteCanonicalName=analyte,
                    EstimatedBottles=ag.bottles if is_due else 0,
                    Preservation=ag.preservation if is_due else "",
                    AccessNote="",
                ))

    n_due = len({r.LocationID for r in rows
                 if r.IsDue and r.DueReason != "access_constraint"})
    n_excluded = len({r.LocationID for r in rows
                      if r.DueReason == "access_constraint"})
    n_not_due = len({r.LocationID for r in rows if r.DueReason == "not_due"})
    qa.add(SEV_INFO, "create_sampling_event_plan_complete",
           f"Sampling event plan for {program.site_id!r} event {event_label!r}: "
           f"{n_due} well(s) due, {n_not_due} not due, {n_excluded} excluded "
           f"(access constraint)")

    return SamplingEventPlan(
        site_id=program.site_id,
        event_label=event_label,
        proposed_event_date=proposed_event_date,
        rows=rows,
    )


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_plan_csv(plan: SamplingEventPlan, path: Path) -> None:
    """Write all planned sample rows to CSV (includes due, not-due, and excluded)."""
    fields = [f.name for f in dataclasses.fields(PlannedSampleRow)]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in plan.rows:
            d = dataclasses.asdict(row)
            w.writerow(d)


def write_coc_csv(plan: SamplingEventPlan, path: Path) -> None:
    """Write a COC draft table for due + accessible wells only.

    Columns: SiteID, EventLabel, ProposedEventDate, LocationID, Matrix,
             SampleID_Draft, AnalyteGroup, AnalyteCanonicalName,
             EstimatedBottles, Preservation.

    SampleID_Draft is a placeholder ({site_id}-{event_label}-{loc}-{matrix})
    for the lab submission form. Field crews assign final IDs on-site.
    Full COC formatting (lab code, matrix, cooling requirements) belongs
    to CreateSurvey123SamplingEvent (2.7), which consumes this plan.
    """
    fields = [
        "SiteID", "EventLabel", "ProposedEventDate", "LocationID", "Matrix",
        "SampleID_Draft", "AnalyteGroup", "AnalyteCanonicalName",
        "EstimatedBottles", "Preservation",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    due_rows = [r for r in plan.rows
                if r.IsDue and r.DueReason != "access_constraint"]
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in due_rows:
            sample_id_draft = (
                f"{plan.site_id}-{plan.event_label}-{row.LocationID}-{row.Matrix}"
            )
            w.writerow({
                "SiteID": plan.site_id,
                "EventLabel": plan.event_label,
                "ProposedEventDate": plan.proposed_event_date.isoformat(),
                "LocationID": row.LocationID,
                "Matrix": row.Matrix,
                "SampleID_Draft": sample_id_draft,
                "AnalyteGroup": row.AnalyteGroup,
                "AnalyteCanonicalName": row.AnalyteCanonicalName,
                "EstimatedBottles": row.EstimatedBottles,
                "Preservation": row.Preservation,
            })


def write_event_schedule_yaml(plan: SamplingEventPlan, path: Path) -> None:
    """Write the event schedule YAML consumed by validate_schedule, schedule_vs_actual, data_gaps.

    Output contract — exact keys required by downstream consumers:
        site_id:            str
        event_label:        str
        wells:              list[str]             # due + accessible wells ONLY
        required_analytes:  list[str]             # union of all due analytes; non-empty
                                                  # (validate_schedule emits WARNING if empty)
        well_analytes:      dict[str, list[str]]  # every due well with its exact analyte list

    well_analytes covers EVERY due well (not just per-well overrides) because
    schedule_vs_actual.py and data_gaps.py use:
        required = well_analytes.get(well, required_analytes)
    Putting every well in well_analytes guarantees the per-well exact set is used.
    required_analytes is the never-used fallback — kept non-empty for validator compat.
    """
    import yaml  # PyYAML — deferred import

    due_rows = [r for r in plan.rows
                if r.IsDue and r.DueReason != "access_constraint"]

    # Build per-well analyte list preserving sorted order for determinism.
    well_analytes: Dict[str, List[str]] = {}
    for row in due_rows:
        well_analytes.setdefault(row.LocationID, [])
        if row.AnalyteCanonicalName not in well_analytes[row.LocationID]:
            well_analytes[row.LocationID].append(row.AnalyteCanonicalName)
    well_analytes = {loc: sorted(analytes) for loc, analytes in well_analytes.items()}

    all_due_analytes: List[str] = sorted({r.AnalyteCanonicalName for r in due_rows})

    doc = {
        "site_id": plan.site_id,
        "event_label": plan.event_label,
        "wells": plan.due_wells,
        "required_analytes": all_due_analytes,
        "well_analytes": well_analytes,
    }

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.dump(doc, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/envmon/test_sampling_event_plan.py -v
```

Expected: all unit tests PASS (integration tests added in Task 2 are not yet in the file).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/sampling_event_plan.py \
        autogis/config/monitoring_schedules/monitoring_program.example.yaml \
        tests/envmon/test_sampling_event_plan.py
git commit -m "feat(envmon): sampling_event_plan — frequency-driven event planner (Tool 7.2)"
```

---

### Task 2: Round-trip integration tests — 7.2 output through all three consumers

**Files:**
- Modify: `tests/envmon/test_sampling_event_plan.py` (append integration tests)

**Interfaces:**
- Consumes from Task 1: `create_sampling_event_plan`, `write_event_schedule_yaml`, `SamplingEventPlan`
- Consumes from existing codebase:
  - `autogis.core.envmon.validate_schedule.validate_schedule(schedule, analyte_dict, *, qa) -> bool`
  - `autogis.core.envmon.schedule_vs_actual.compare_schedule_vs_actual(results, schedule, *, event_date, window_days, qa) -> List[ScheduleGapRecord]`
  - `autogis.core.envmon.data_gaps.identify_data_gaps(results, schedule, *, event_date, window_days, dry_wells, qa) -> List[DataGapRecord]`
  - `autogis.core.envmon.gdb_schema.AnalyticalResultRecord` (dataclass)

- [ ] **Step 1: Append integration tests to the existing test file**

Open `tests/envmon/test_sampling_event_plan.py` and append the following section **after** the last existing test (`test_write_event_schedule_yaml_well_analytes_is_superset`):

```python
# ===========================================================================
# Task 2: Round-trip integration tests
# 7.2 output schedule YAML → downstream consumers
# ===========================================================================

from autogis.core.envmon.validate_schedule import validate_schedule
from autogis.core.envmon.schedule_vs_actual import (
    compare_schedule_vs_actual, ScheduleGapRecord,
)
from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _make_analytic_result(
    loc: str,
    analyte: str,
    sample_date: date = date(2026, 6, 15),
    is_not_analyzed: bool = False,
) -> AnalyticalResultRecord:
    """Minimal AnalyticalResultRecord for integration tests."""
    return AnalyticalResultRecord(
        ImportBatchID="BATCH01",
        SiteID="H281",
        Matrix="GW",
        LocationID=loc,
        SampleID=f"{loc}-001",
        ParentSampleID=None,
        SampleDate=sample_date,
        DepthTop_ft=None,
        DepthBottom_ft=None,
        DepthIntervalText=None,
        AnalyticalGroup="VOC",
        MethodGroup=None,
        AnalyteName=analyte,
        AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=None,
        ResultRawText="5.0",
        ResultNumeric=5.0,
        ReportingLimit=None,
        DetectionLimit=None,
        Units="ug/L",
        Qualifier=None,
        IsNonDetect=False,
        IsDetected=True,
        IsEstimated=False,
        IsDiluted=False,
        IsNotAnalyzed=is_not_analyzed,
        IsNotSampled=False,
        IsNotMeasured=False,
        ScreeningLevel=None,
        ScreeningLevelSource=None,
        ExceedsScreeningLevel=None,
        DisplayText="5.0",
        DisplayColorClass=None,
        SourceWorkbook=None,
        SourceSheet=None,
        SourceRow=None,
        SourceColumn=None,
        SourceCell=None,
    )


def test_roundtrip_validate_schedule(tmp_path):
    """7.2 output YAML passes validate_schedule with no ERRORs."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched.yaml"
    write_event_schedule_yaml(plan, out)

    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))
    qa = QACollector()
    result = validate_schedule(schedule, analyte_dict=None, qa=qa)

    errors = [r for r in qa.records if r.severity in ("ERROR", "CRITICAL")]
    assert result is True, (
        f"validate_schedule returned False — errors: "
        + ", ".join(r.message for r in errors)
    )
    assert not errors, f"validate_schedule produced ERRORs: {errors}"


def test_roundtrip_validate_schedule_no_warning_for_required_analytes(tmp_path):
    """required_analytes must be non-empty so validate_schedule does not warn."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched_warn.yaml"
    write_event_schedule_yaml(plan, out)

    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))
    qa = QACollector()
    validate_schedule(schedule, analyte_dict=None, qa=qa)

    no_analyte_warnings = [
        r for r in qa.records
        if r.category == "no_required_analytes"
    ]
    assert not no_analyte_warnings, (
        "required_analytes is empty — validate_schedule emitted 'no_required_analytes' WARNING"
    )


def test_roundtrip_compare_schedule_vs_actual_full_match(tmp_path):
    """When all due wells are sampled, compare_schedule_vs_actual has no MISSING rows."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched.yaml"
    write_event_schedule_yaml(plan, out)
    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Simulate perfect sampling: every due well × analyte has a result.
    results: List[AnalyticalResultRecord] = []
    for well in plan.due_wells:
        due_analytes = {r.AnalyteCanonicalName for r in plan.rows
                        if r.LocationID == well and r.IsDue
                        and r.DueReason != "access_constraint"}
        for analyte in due_analytes:
            results.append(_make_analytic_result(well, analyte))

    qa = QACollector()
    gap_rows = compare_schedule_vs_actual(
        results, schedule,
        event_date=_EVENT_DATE, window_days=30, qa=qa,
    )
    missing = [r for r in gap_rows if r.Status == "MISSING"]
    assert not missing, (
        f"Expected no MISSING rows when all due wells are sampled, got: {missing}"
    )


def test_roundtrip_compare_schedule_vs_actual_detects_gap(tmp_path):
    """compare_schedule_vs_actual detects MISSING when an analyte is absent from results."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched2.yaml"
    write_event_schedule_yaml(plan, out)
    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Only supply Benzene for MW-1; omit Toluene and all Metals.
    results = [_make_analytic_result("MW-1", "Benzene")]

    qa = QACollector()
    gap_rows = compare_schedule_vs_actual(
        results, schedule,
        event_date=_EVENT_DATE, window_days=30, qa=qa,
    )
    missing = [r for r in gap_rows if r.Status == "MISSING"]
    missing_analytes = {r.AnalyteName for r in missing}

    # Toluene must be detected as missing for MW-1 (it is in the due analyte list).
    assert "Toluene" in missing_analytes, (
        f"Expected Toluene to be flagged MISSING; got missing set: {missing_analytes}"
    )


def test_roundtrip_data_gaps_full_sampling_no_gaps(tmp_path):
    """identify_data_gaps reports zero gaps when all due wells are fully sampled."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched3.yaml"
    write_event_schedule_yaml(plan, out)
    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))

    results: List[AnalyticalResultRecord] = []
    for well in plan.due_wells:
        due_analytes = {r.AnalyteCanonicalName for r in plan.rows
                        if r.LocationID == well and r.IsDue
                        and r.DueReason != "access_constraint"}
        for analyte in due_analytes:
            results.append(_make_analytic_result(well, analyte))

    qa = QACollector()
    gaps = identify_data_gaps(
        results, schedule,
        event_date=_EVENT_DATE, window_days=30, dry_wells={}, qa=qa,
    )
    errors = [g for g in gaps if g.GapType in ("MISSING_WELL", "MISSED_ANALYTE")]
    assert not errors, (
        f"Expected no gap errors when all due wells fully sampled; got: {errors}"
    )


def test_roundtrip_data_gaps_missing_well_detected(tmp_path):
    """identify_data_gaps reports MISSING_WELL when a due well has no results."""
    plan = _make_plan(prior_dates={})
    out = tmp_path / "sched4.yaml"
    write_event_schedule_yaml(plan, out)
    schedule = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Provide results for MW-1 only; MW-2 completely absent.
    results = [_make_analytic_result("MW-1", "Benzene"),
               _make_analytic_result("MW-1", "Toluene")]

    qa = QACollector()
    gaps = identify_data_gaps(
        results, schedule,
        event_date=_EVENT_DATE, window_days=30, dry_wells={}, qa=qa,
    )
    missing_wells = {g.LocationID for g in gaps if g.GapType == "MISSING_WELL"}
    assert "MW-2" in missing_wells, (
        f"Expected MW-2 to be MISSING_WELL; got: {missing_wells}"
    )
```

- [ ] **Step 2: Verify AnalyticalResultRecord constructor matches the fields used**

Check `autogis/core/envmon/gdb_schema.py` for the `AnalyticalResultRecord` dataclass definition. If the dataclass uses `@dataclass` field ordering different from the keyword arguments in `_make_analytic_result()`, adjust the keyword argument names to match. (The gdb_schema module defines `AnalyticalResultRecord` as a dataclass with all fields named exactly as they appear in `TABLE_SCHEMAS["Env_AnalyticalResults"]`.)

- [ ] **Step 3: Run all tests in the file**

```
python -m pytest tests/envmon/test_sampling_event_plan.py -v
```

Expected: all existing unit tests + all integration tests PASS.

- [ ] **Step 4: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all previously-passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add tests/envmon/test_sampling_event_plan.py
git commit -m "test(envmon): add round-trip integration tests — 7.2 output through validate_schedule, schedule_vs_actual, data_gaps"
```

---

### Task 3: CLI command `create-sampling-event-plan`

**Files:**
- Modify: `autogis/adapters/cli.py` — insert after the `identify-data-gaps` command block (near line 550)

**Interfaces:**
- Consumes from Task 1:
  - `load_monitoring_program_yaml(path) -> MonitoringProgram`
  - `load_prior_events_csv(path) -> Dict[str, date]`
  - `create_sampling_event_plan(program, event_date, prior_dates, event_label, *, qa) -> SamplingEventPlan`
  - `write_plan_csv(plan, path) -> None`
  - `write_coc_csv(plan, path) -> None`
  - `write_event_schedule_yaml(plan, path) -> None`

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/envmon/test_sampling_event_plan.py` (after the integration tests added in Task 2):

```python
# ===========================================================================
# Task 3: CLI tests
# ===========================================================================

from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_create_sampling_event_plan_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "create-sampling-event-plan" in result.output


def test_cli_create_sampling_event_plan_basic(tmp_path):
    """End-to-end CLI: two-well program, no prior events, all wells due."""
    prog_yaml = tmp_path / "program.yaml"
    prog_yaml.write_text(_PROG_YAML, encoding="utf-8")

    plan_csv = tmp_path / "plan.csv"
    sched_yaml = tmp_path / "schedule.yaml"
    coc_csv = tmp_path / "coc.csv"
    qa_report = tmp_path / "qa.md"

    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event-plan",
        "--program", str(prog_yaml),
        "--event-date", "2026-06-15",
        "--event-label", "2026-Q2",
        "--plan-output", str(plan_csv),
        "--schedule-output", str(sched_yaml),
        "--coc-output", str(coc_csv),
        "--report", str(qa_report),
    ])
    assert result.exit_code == 0, (
        f"CLI exited with code {result.exit_code}.\nOutput:\n{result.output}"
    )
    assert plan_csv.exists(), "plan CSV was not created"
    assert sched_yaml.exists(), "schedule YAML was not created"
    assert coc_csv.exists(), "COC CSV was not created"

    # Verify the output YAML is well-formed and contains expected keys.
    sched = yaml.safe_load(sched_yaml.read_text(encoding="utf-8"))
    assert sched["site_id"] == "H281"
    assert sched["event_label"] == "2026-Q2"
    assert "MW-1" in sched["wells"]
    assert "MW-2" in sched["wells"]


def test_cli_create_sampling_event_plan_with_prior_events(tmp_path):
    """MW-2 not due (30 days since last sampled); MW-1 due (97 days elapsed)."""
    prog_yaml = tmp_path / "prog.yaml"
    prog_yaml.write_text(_PROG_YAML, encoding="utf-8")

    prior_csv = tmp_path / "prior.csv"
    with prior_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["location_id", "last_sampled_date"])
        w.writeheader()
        w.writerow({"location_id": "MW-1", "last_sampled_date": "2026-03-10"})
        w.writerow({"location_id": "MW-2", "last_sampled_date": "2026-05-16"})

    plan_csv = tmp_path / "plan.csv"
    sched_yaml = tmp_path / "schedule.yaml"

    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event-plan",
        "--program", str(prog_yaml),
        "--event-date", "2026-06-15",
        "--event-label", "2026-Q2",
        "--prior-events", str(prior_csv),
        "--plan-output", str(plan_csv),
        "--schedule-output", str(sched_yaml),
    ])
    assert result.exit_code == 0, result.output

    sched = yaml.safe_load(sched_yaml.read_text(encoding="utf-8"))
    assert "MW-1" in sched["wells"]
    assert "MW-2" not in sched["wells"]
    assert "MW-1" in result.output   # summary echoed
```

- [ ] **Step 2: Run CLI tests to confirm failures**

```
python -m pytest tests/envmon/test_sampling_event_plan.py::test_create_sampling_event_plan_in_help tests/envmon/test_sampling_event_plan.py::test_cli_create_sampling_event_plan_basic tests/envmon/test_sampling_event_plan.py::test_cli_create_sampling_event_plan_with_prior_events -v
```

Expected: FAIL — `autogis envmon --help` output does not yet contain `create-sampling-event-plan`.

- [ ] **Step 3: Add the CLI command to `autogis/adapters/cli.py`**

Find the `identify-data-gaps` command block (the `identify_data_gaps_cmd` function and the line `click.echo(f"Written: {out} ...`). Insert the following block **immediately after** that function (before any blank lines leading to the next `@envmon.command`):

```python
@envmon.command("create-sampling-event-plan")
@click.option("--program", "program_path", required=True,
              type=click.Path(exists=True),
              help="Monitoring program YAML (see monitoring_program.example.yaml).")
@click.option("--event-date", required=True,
              help="Proposed event date ISO format YYYY-MM-DD.")
@click.option("--event-label", default=None,
              help="Short event label (e.g. 2026-Q2). Defaults to event-date.")
@click.option("--prior-events", "prior_events_path", default=None,
              type=click.Path(exists=True),
              help="CSV with columns location_id,last_sampled_date. "
                   "Omit to treat all wells as never sampled.")
@click.option("--plan-output", "plan_output", required=True,
              type=click.Path(),
              help="Path for the planned-samples CSV (all wells, all analytes).")
@click.option("--schedule-output", "schedule_output", default=None,
              type=click.Path(),
              help="Path for the event schedule YAML consumed by validate_schedule, "
                   "schedule_vs_actual, and identify-data-gaps.")
@click.option("--coc-output", "coc_output", default=None,
              type=click.Path(),
              help="Path for the COC draft CSV (due wells only).")
@click.option("--report", default=None, type=click.Path(),
              help="QA report path (.md / .json / .csv).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def create_sampling_event_plan_cmd(
    program_path, event_date, event_label, prior_events_path,
    plan_output, schedule_output, coc_output, report, fail_on,
):
    """Tool 7.2: determine which wells/analytes are due for a sampling event.

    Reads a monitoring program YAML (well network + analyte groups + frequency
    rules) and optional prior-event history CSV, then produces:
      - planned-samples CSV (all wells; IsDue column shows due/not-due)
      - event schedule YAML for downstream tools (validate-schedule,
        compare-schedule-vs-actual, identify-data-gaps)
      - COC draft CSV (due wells only)

    Headless: no arcpy, no AGOL. Survey123 record generation belongs to
    CreateSurvey123SamplingEvent (2.7), which consumes --schedule-output.
    """
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.sampling_event_plan import (
        load_monitoring_program_yaml,
        load_prior_events_csv,
        create_sampling_event_plan,
        write_plan_csv,
        write_coc_csv,
        write_event_schedule_yaml,
    )

    event_date_obj = _date.fromisoformat(event_date)
    label = event_label or event_date

    program = load_monitoring_program_yaml(Path(program_path))
    prior_dates = (
        load_prior_events_csv(Path(prior_events_path))
        if prior_events_path else {}
    )

    qa = QACollector()
    plan = create_sampling_event_plan(
        program, event_date_obj, prior_dates, label, qa=qa
    )

    write_plan_csv(plan, Path(plan_output))
    click.echo(f"Plan CSV written: {plan_output}  ({len(plan.rows)} row(s))")
    click.echo(
        f"Due wells ({len(plan.due_wells)}): {', '.join(plan.due_wells) or 'none'}"
    )
    if plan.excluded_wells:
        click.echo(
            f"Excluded (access constraint) ({len(plan.excluded_wells)}): "
            f"{', '.join(plan.excluded_wells)}"
        )
    if plan.not_due_wells:
        click.echo(
            f"Not due this event ({len(plan.not_due_wells)}): "
            f"{', '.join(plan.not_due_wells)}"
        )

    if schedule_output:
        write_event_schedule_yaml(plan, Path(schedule_output))
        click.echo(f"Event schedule YAML written: {schedule_output}")

    if coc_output:
        write_coc_csv(plan, Path(coc_output))
        click.echo(f"COC draft CSV written: {coc_output}")

    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_sampling_event_plan.py::test_create_sampling_event_plan_in_help tests/envmon/test_sampling_event_plan.py::test_cli_create_sampling_event_plan_basic tests/envmon/test_sampling_event_plan.py::test_cli_create_sampling_event_plan_with_prior_events -v
```

Expected: all three PASS.

- [ ] **Step 5: Run full test suite**

```
python -m pytest -q
```

Expected: all previously-passing tests still pass, new tests now also pass.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_sampling_event_plan.py
git commit -m "feat(cli): add create-sampling-event-plan command (Tool 7.2 — headless)"
```

---

## Self-Review

### 1. Spec coverage

| Roadmap requirement | Covered by |
|---|---|
| Well network input | `MonitoringProgram.wells` + YAML loader |
| Required analyte groups | `MonitoringProgram.analyte_groups` + per-well `analyte_groups` list |
| Sampling frequency | `FREQUENCY_THRESHOLDS_DAYS` + `_is_due()` |
| Prior event data | `load_prior_events_csv()` + `prior_dates` dict |
| Access constraints | `WellSchedule.access_note` → `DueReason="access_constraint"` |
| Planned sample list | `write_plan_csv()` |
| Bottle count estimate | `PlannedSampleRow.EstimatedBottles` = `AnalyteGroupDef.bottles` |
| Field map layer | **Intentionally deferred** — arcpy, LOCAL tier, not in scope |
| COC draft table | `write_coc_csv()` |
| Missing-prior-data warnings | QA `SEV_WARNING` category `no_prior_event_data` |
| Downstream contract (validate_schedule / schedule_vs_actual / data_gaps) | `write_event_schedule_yaml()` output contract; verified by integration tests |

### 2. Placeholder scan

No placeholders found. All steps contain complete code.

### 3. Type consistency

- `load_monitoring_program_yaml() -> MonitoringProgram` — used in Task 1 tests and Task 3 CLI ✓
- `load_prior_events_csv() -> Dict[str, date]` — used in Task 1 tests and Task 3 CLI ✓
- `_is_due(frequency, last_sampled, event_date) -> Tuple[bool, str]` — consistent across Task 1 tests and implementation ✓
- `create_sampling_event_plan(program, date, dict, str, *, qa) -> SamplingEventPlan` — consistent across all tasks ✓
- `SamplingEventPlan.due_wells -> List[str]` — used in Task 2 integration tests and Task 3 CLI ✓
- `write_event_schedule_yaml(plan, path) -> None` — used in Task 1 tests, Task 2 integration tests, Task 3 CLI ✓
- `write_plan_csv(plan, path) -> None`, `write_coc_csv(plan, path) -> None` — consistent ✓
- `AnalyteGroupDef`, `WellSchedule`, `MonitoringProgram` — all defined in Task 1, used in tests and integration ✓

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `AnalyticalResultRecord` constructor argument names differ from the keyword names in `_make_analytic_result()` | Low–Medium | Step 2 of Task 2 explicitly flags this check; adjust keywords to match actual dataclass field names in `gdb_schema.py` |
| PyYAML absent in test environment | Very low | PyYAML is a standard ArcGIS Pro dependency and is listed in `schedule_vs_actual.py` as the established pattern |
| `schedule_vs_actual.compare_schedule_vs_actual` signature changes | Low | Integration test will fail immediately and point to the exact mismatch |
| Frequency thresholds too aggressive for real regulatory schedules | Medium | Thresholds documented as assumptions; named constants are centralized for easy override; note recommends calendar-aware replacement if needed |
| `well_analytes` override contract misunderstood by 2.7 implementer | Low | Docstring on `write_event_schedule_yaml` and inline comments in the output YAML explicitly explain the override-not-additive semantics |

---

## Usage example

```bash
# Generate a plan for the 2026-Q2 event:
python -m autogis envmon create-sampling-event-plan \
  --program autogis/config/monitoring_schedules/monitoring_program.example.yaml \
  --event-date 2026-06-15 \
  --event-label "2026-Q2" \
  --prior-events prior_events.csv \
  --plan-output output/2026-Q2_planned_samples.csv \
  --schedule-output output/2026-Q2_event_schedule.yaml \
  --coc-output output/2026-Q2_coc_draft.csv \
  --report output/2026-Q2_qa.md

# Validate the output schedule (round-trip check):
python -m autogis envmon validate-config H281_Glasgow.yaml \
  --schedule output/2026-Q2_event_schedule.yaml

# Feed to identify-data-gaps after sampling is complete:
python -m autogis envmon identify-data-gaps \
  --results-csv results_export.csv \
  --schedule output/2026-Q2_event_schedule.yaml \
  --output output/2026-Q2_data_gaps.csv
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-28-create-sampling-event-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans` with checkpoints.

**Which approach?**
