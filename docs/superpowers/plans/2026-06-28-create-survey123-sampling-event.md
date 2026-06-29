# CreateSurvey123SamplingEvent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a headless pre-field event generator (roadmap #2.7) that takes a well list + event metadata + analyte dict and produces a three-sheet planning workbook: expected-sample table, crew assignment, and chain-of-custody draft.

**Architecture:** A new core module `create_sampling_event.py` owns all planner logic (dataclasses + round-robin crew assignment + field-dup injection + COC numbering). A separate writer module `sampling_event_writer.py` translates the plan into a single three-sheet openpyxl workbook. The CLI command `envmon create-sampling-event` wires both together; it is headless (no arcpy) and writes to an output directory.

**Tech Stack:** Python stdlib only + openpyxl (already required by core). No arcpy, no arcgis, no PyYAML required beyond what the existing `load_config` loader already handles.

## Global Constraints

- Branch: create on a feature branch, e.g. `feat/create-sampling-event-2.7`
- `autogis/core/` and `autogis/adapters/` must import with NEITHER `arcpy` NOR `arcgis` present — CI enforces this.
- Run tests with `python -m pytest -q`. All new tests must be arcpy-free.
- `SiteConfig` is canonical in `autogis/core/common/config.py`; load it with `SiteConfig.load(path)`.
- `load_analyte_dictionary(path)` is in `autogis/core/common/config.py`; returns `{analyte_name: {abbreviation, analytical_group, default_units_by_matrix, ...}}`. The analyte dict has **no** container/preservative/hold_time fields — those belong in the event config's `group_sampling` section.
- `analyte_groups` key in event_config stays as `{group_name: [analyte_names]}` exactly as consumed by `survey123_form_builder.build_xlsform()`. Do NOT change that structure or you silently break shared event configs passed to the form builder.
- SampleID format: `{WellID}-{YYYYMMDD}-{Matrix}` for primary samples, `{WellID}-{YYYYMMDD}-{Matrix}-FD` for field duplicates. This matches the Survey123 form builder's `concat(${WellID},"-",date,"-",${Matrix})` calculation so downstream `ReconcileSurvey123AndLabResults` (2.6) can reconcile by ID.
- **Scope is the planning artifact only.** This tool generates the pre-field Excel workbook. It does NOT submit to Survey123, does not call the AGOL REST API, and is not the live webhook router `RouteSurvey123Submission` (7.1b). It also does not replace `CreateSamplingEventPlan` (7.2), which is a separate GIS-backed planning tool.
- **QA samples policy (documented non-goals for v1):** Field duplicates are included at a configurable frequency (`dup_frequency`, default=10 → one dup per 10 wells). Trip blanks and equipment blanks are non-goal for v1 — the COC has an `extra_bottles` free-text column for field crews to note them manually.
- Output: one `.xlsx` workbook with three sheets (`Expected_Samples`, `Crew_Assignment`, `COC_Draft`), filename `{site_id}_{event_name}_sampling_plan.xlsx`.
- `run_id` (UUID) and `event_date` are injected as parameters to `build_sampling_event_plan()` — never use `uuid.uuid4()` or `datetime.now()` internally — so tests produce deterministic output.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `autogis/core/envmon/create_sampling_event.py` | Dataclasses + planner logic |
| Create | `autogis/core/envmon/sampling_event_writer.py` | openpyxl three-sheet writer |
| Modify | `autogis/adapters/cli.py` | Add `create-sampling-event` command |
| Create | `tests/envmon/test_create_sampling_event.py` | Core planner tests |
| Create | `tests/envmon/test_sampling_event_writer.py` | Writer tests |
| Create | `tests/envmon/test_cli_create_sampling_event.py` | CLI smoke tests |

---

## Event Config YAML Shape (reference — no new loader needed; `load_config()` handles it)

```yaml
# autogis/config/events/h281-2026-q2.yaml  (example; not created by this plan)
event_name: "2026-Q2"
event_date: "2026-07-15"          # ISO date string; planner converts to YYYYMMDD for IDs
coc_prefix: "H281-COC"
lab_name: "TestAmerica Seattle"
matrices: ["GW"]
location_ids: ["MW-1", "MW-2", "MW-3", "MW-4", "MW-5"]
crew_list: ["Alice Smith", "Bob Jones"]
dup_frequency: 10                  # 1 field dup per N wells; 0 = no dups
analyte_groups:                    # dict[str, list[str]] — SAME as form builder; do not enrich
  VOCs: ["Benzene", "Toluene", "Xylenes"]
  Metals: ["Arsenic", "Barium"]
group_sampling:                    # additive sampling metadata; NOT in form builder's analyte_groups
  VOCs:
    container: "40mL VOA"
    preservative: "HCl"
    hold_time_hr: 14
    bottles: 1
  Metals:
    container: "250mL PP"
    preservative: "HNO3"
    hold_time_hr: 180
    bottles: 1
```

---

### Task 1: Core planner — `create_sampling_event.py`

**Files:**
- Create: `autogis/core/envmon/create_sampling_event.py`
- Create: `tests/envmon/test_create_sampling_event.py`

**Interfaces:**
- Produces:
  - `SamplingEventConfig` — parsed event config dataclass (used by Task 2 writer)
  - `ExpectedSampleRow` — one row per (well × analyte_group × matrix); includes FD rows
  - `CrewAssignmentRow` — one row per well showing assigned crew and bottle count
  - `SamplingEventPlan` — the root output holding all rows + metadata
  - `build_sampling_event_plan(site_config_dict, event_config_dict, analyte_dict, run_id) -> SamplingEventPlan`
  - `load_event_config(path: Path) -> dict` — thin wrapper around `load_config`

---

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_create_sampling_event.py`:

```python
"""Tests for create_sampling_event — fully arcpy-free."""
import pytest

from autogis.core.envmon.create_sampling_event import (
    build_sampling_event_plan,
    SamplingEventPlan,
    ExpectedSampleRow,
    CrewAssignmentRow,
)

# ── fixtures ──────────────────────────────────────────────────────────────

SITE = {"site_id": "H281", "site_name": "H281 Glasgow"}

EVENT_BASE = {
    "event_name": "2026-Q2",
    "event_date": "2026-07-15",
    "coc_prefix": "H281-COC",
    "lab_name": "TestAmerica Seattle",
    "matrices": ["GW"],
    "location_ids": ["MW-1", "MW-2", "MW-3"],
    "crew_list": ["Alice Smith", "Bob Jones"],
    "dup_frequency": 0,  # off for most tests — enable selectively
    "analyte_groups": {
        "VOCs": ["Benzene", "Toluene"],
        "Metals": ["Arsenic"],
    },
    "group_sampling": {
        "VOCs": {"container": "40mL VOA", "preservative": "HCl",
                 "hold_time_hr": 14, "bottles": 1},
        "Metals": {"container": "250mL PP", "preservative": "HNO3",
                   "hold_time_hr": 180, "bottles": 1},
    },
}

ADICT = {
    "Benzene": {"abbreviation": "B", "analytical_group": "VPH_VOC",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 10},
    "Toluene": {"abbreviation": "T", "analytical_group": "VPH_VOC",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 20},
    "Arsenic": {"abbreviation": "As", "analytical_group": "METALS",
                "default_units_by_matrix": {"GW": "ug/L"}, "display_order": 30},
}

FIXED_RUN_ID = "test-run-001"


def _plan(event_overrides=None) -> SamplingEventPlan:
    event = {**EVENT_BASE, **(event_overrides or {})}
    return build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


# ── row count ─────────────────────────────────────────────────────────────

def test_expected_row_count_no_dups():
    """3 wells × 2 analyte groups × 1 matrix = 6 rows with dup_frequency=0."""
    plan = _plan()
    primary = [r for r in plan.expected_samples if r.sample_type == "Regular"]
    assert len(primary) == 6


def test_field_dup_added_at_frequency():
    """dup_frequency=2 → every 2nd well gets a FD row per analyte_group."""
    # 3 wells ["MW-1","MW-2","MW-3"], freq=2:
    # position 1 (MW-1): 1 % 2 != 0 → no dup
    # position 2 (MW-2): 2 % 2 == 0 → dup
    # position 3 (MW-3): 3 % 2 != 0 → no dup
    # → 1 dup well (MW-2) × 2 groups = 2 FD rows
    plan = _plan({"dup_frequency": 2})
    fd_rows = [r for r in plan.expected_samples if r.sample_type == "Field Duplicate"]
    assert len(fd_rows) == 2
    assert all(r.location_id == "MW-2" for r in fd_rows)


def test_no_field_dups_when_frequency_zero():
    plan = _plan({"dup_frequency": 0})
    assert not any(r.sample_type == "Field Duplicate" for r in plan.expected_samples)


# ── sample ID format ──────────────────────────────────────────────────────

def test_sample_id_format_primary():
    """Primary SampleID = {WellID}-{YYYYMMDD}-{Matrix}."""
    plan = _plan()
    row = next(r for r in plan.expected_samples
               if r.location_id == "MW-1" and r.sample_type == "Regular")
    assert row.sample_id == "MW-1-20260715-GW"


def test_sample_id_format_field_dup():
    """Field dup SampleID = {WellID}-{YYYYMMDD}-{Matrix}-FD."""
    plan = _plan({"dup_frequency": 1})  # every well gets a dup
    row = next(r for r in plan.expected_samples
               if r.location_id == "MW-1" and r.sample_type == "Field Duplicate")
    assert row.sample_id == "MW-1-20260715-GW-FD"


# ── COC numbering ─────────────────────────────────────────────────────────

def test_coc_numbers_are_sequential():
    """Each well gets its own COC number; numbers are unique and sequential."""
    plan = _plan()
    coc_by_well = {}
    for row in plan.expected_samples:
        coc_by_well.setdefault(row.location_id, row.coc_number)
    coc_nums = list(coc_by_well.values())
    assert len(set(coc_nums)) == 3                        # one per well
    assert coc_nums[0] == "H281-COC-001"
    assert coc_nums[1] == "H281-COC-002"
    assert coc_nums[2] == "H281-COC-003"


# ── crew assignment ───────────────────────────────────────────────────────

def test_crew_round_robin_covers_all_wells():
    """Every well appears in crew_assignments exactly once."""
    plan = _plan()
    assigned = {r.location_id for r in plan.crew_assignments}
    assert assigned == {"MW-1", "MW-2", "MW-3"}


def test_crew_assignment_is_round_robin():
    """With 3 wells and 2 crew, distribution is [2, 1] or [1, 2]."""
    plan = _plan()
    from collections import Counter
    counts = Counter(r.assigned_to for r in plan.crew_assignments)
    totals = sorted(counts.values(), reverse=True)
    assert totals in ([2, 1], [1, 2])


def test_crew_assignment_has_correct_sample_count():
    """bottle count per well = number of analyte_groups × bottles_per_group."""
    plan = _plan()
    row = next(r for r in plan.crew_assignments if r.location_id == "MW-1")
    # 2 groups × 1 bottle each = 2
    assert row.bottle_count == 2


# ── group_sampling metadata propagates ───────────────────────────────────

def test_group_sampling_container_propagated():
    plan = _plan()
    row = next(r for r in plan.expected_samples
               if r.analyte_group == "VOCs" and r.sample_type == "Regular")
    assert row.container_type == "40mL VOA"
    assert row.preservative == "HCl"
    assert row.hold_time_hr == 14


def test_missing_group_sampling_falls_back_to_defaults():
    """If group_sampling omits a group, defaults are empty-string / 0."""
    event = {**EVENT_BASE, "group_sampling": {}}
    plan = build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)
    row = next(r for r in plan.expected_samples if r.analyte_group == "VOCs")
    assert row.container_type == ""
    assert row.preservative == ""
    assert row.hold_time_hr == 0


# ── plan metadata ─────────────────────────────────────────────────────────

def test_plan_run_id_is_injected():
    plan = _plan()
    assert plan.run_id == FIXED_RUN_ID


def test_plan_site_id_sourced_from_site_config():
    plan = _plan()
    assert plan.site_id == "H281"


# ── validation guards ─────────────────────────────────────────────────────

def test_empty_crew_list_raises():
    with pytest.raises(ValueError, match="crew_list"):
        _plan({"crew_list": []})


def test_empty_location_ids_raises():
    with pytest.raises(ValueError, match="location_ids"):
        _plan({"location_ids": []})


def test_missing_event_name_raises():
    event = {k: v for k, v in EVENT_BASE.items() if k != "event_name"}
    with pytest.raises(KeyError):
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


def test_unknown_analyte_in_analyte_groups_raises():
    """Misspelled analyte that's not in the analyte_dict raises ValueError."""
    event = {**EVENT_BASE, "analyte_groups": {"VOCs": ["Benzene", "Benzine"]}}
    with pytest.raises(ValueError, match="Benzine"):
        build_sampling_event_plan(SITE, event, ADICT, run_id=FIXED_RUN_ID)


def test_dup_well_bottle_count_includes_fd_bottles():
    """CrewAssignmentRow.bottle_count must count both primary and FD bottles."""
    # dup_frequency=1 → every well gets a FD
    plan = _plan({"dup_frequency": 1})
    row = next(r for r in plan.crew_assignments if r.location_id == "MW-1")
    # 2 groups × 1 bottle each × 2 (primary + FD) = 4
    assert row.bottle_count == 4
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_create_sampling_event.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create `autogis/core/envmon/create_sampling_event.py`**

```python
"""create_sampling_event.py — pre-field sampling event planner.

Headless (arcpy-free, openpyxl-free). Pure stdlib + the existing
load_config loader.  Outputs a SamplingEventPlan that the writer
module serialises to XLSX.

Design decisions:
- run_id and event_date injected as parameters for deterministic tests.
- analyte_groups stays as {group: [names]} (form-builder contract; ADR-019).
- group_sampling is a separate additive section for container/preservative/hold_time.
- dup_frequency: 1 FD well per N wells, 0-based position: wells at 1-based
  positions [N, 2N, 3N, …] receive field duplicates.
- Trip/equipment blanks: non-goal for v1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..common.config import load_config


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExpectedSampleRow:
    sample_id: str
    location_id: str
    event_date: str         # ISO "YYYY-MM-DD"
    matrix: str
    analyte_group: str
    sample_type: str        # "Regular" or "Field Duplicate"
    container_type: str
    preservative: str
    hold_time_hr: int
    bottle_count: int
    coc_number: str
    assigned_to: str


@dataclass
class CrewAssignmentRow:
    location_id: str
    assigned_to: str
    bottle_count: int       # total bottles at this well across all groups


@dataclass
class SamplingEventPlan:
    event_name: str
    event_date: str
    site_id: str
    site_name: str
    lab_name: str
    coc_prefix: str
    run_id: str
    expected_samples: List[ExpectedSampleRow]
    crew_assignments: List[CrewAssignmentRow]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _date_to_yyyymmdd(iso_date: str) -> str:
    """'2026-07-15' → '20260715'."""
    m = _ISO_RE.match(iso_date.strip())
    if not m:
        raise ValueError(
            f"event_date must be ISO format YYYY-MM-DD, got: {iso_date!r}")
    return m.group(1) + m.group(2) + m.group(3)


def _sample_id(location_id: str, date_compact: str, matrix: str,
               is_dup: bool) -> str:
    base = f"{location_id}-{date_compact}-{matrix}"
    return f"{base}-FD" if is_dup else base


def _coc_number(prefix: str, seq: int) -> str:
    return f"{prefix}-{seq:03d}"


def _round_robin(items: List[str], crew: List[str]) -> Dict[str, str]:
    """Assign each item to a crew member in round-robin order."""
    return {item: crew[i % len(crew)] for i, item in enumerate(items)}


def _dup_wells(location_ids: List[str], dup_frequency: int) -> set:
    """Return the set of location_ids that should receive field duplicates.

    With dup_frequency=N, the Nth, 2Nth, … (1-based) wells get a dup.
    """
    if dup_frequency <= 0:
        return set()
    return {loc for i, loc in enumerate(location_ids, start=1)
            if i % dup_frequency == 0}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_event_config(path: Path) -> dict:
    """Load and return an event config dict from YAML or JSON."""
    return load_config(Path(path))


def build_sampling_event_plan(
    site_config_dict: dict,
    event_config: dict,
    analyte_dict: dict,
    *,
    run_id: str,
) -> SamplingEventPlan:
    """Build a SamplingEventPlan from site + event + analyte configs.

    Parameters
    ----------
    site_config_dict:
        Dict with at least ``site_id`` and ``site_name``.
        Pass ``SiteConfig.data`` when you have a loaded SiteConfig.
    event_config:
        Dict loaded from the event YAML. Required keys: event_name,
        event_date, coc_prefix, lab_name, matrices, location_ids,
        crew_list, analyte_groups, group_sampling.
        Optional key: dup_frequency (default 10; 0 = none).
    analyte_dict:
        Dict returned by ``load_analyte_dictionary()``. Every analyte name
        listed in ``event_config["analyte_groups"]`` is validated against
        this dict — raises ``ValueError`` if any analyte is unknown. This
        catches misspellings before the crew reaches the field.
    run_id:
        Caller-supplied UUID string (inject for tests; use
        ``str(uuid.uuid4())`` in production callers).
    """
    # ── required keys ──
    event_name: str = event_config["event_name"]
    event_date: str = event_config["event_date"]
    coc_prefix: str = event_config["coc_prefix"]
    lab_name: str = event_config.get("lab_name", "")
    matrices: List[str] = event_config.get("matrices", ["GW"])
    location_ids: List[str] = event_config.get("location_ids", [])
    crew_list: List[str] = event_config.get("crew_list", [])
    analyte_groups: Dict[str, List[str]] = event_config.get("analyte_groups", {})
    group_sampling: Dict[str, dict] = event_config.get("group_sampling", {})
    dup_frequency: int = int(event_config.get("dup_frequency", 10))

    if not location_ids:
        raise ValueError("event_config must have at least one entry in location_ids")
    if not crew_list:
        raise ValueError("event_config must have at least one entry in crew_list")

    # Validate every analyte in analyte_groups exists in analyte_dict
    unknown = {
        analyte
        for names in analyte_groups.values()
        if isinstance(names, list)
        for analyte in names
        if analyte not in analyte_dict
    }
    if unknown:
        raise ValueError(
            f"Unknown analyte(s) in analyte_groups (not in analyte_dict): "
            f"{', '.join(sorted(unknown))}"
        )

    site_id: str = site_config_dict.get("site_id", "SITE")
    site_name: str = site_config_dict.get("site_name", site_id)

    date_compact = _date_to_yyyymmdd(event_date)
    primary_matrix = matrices[0] if matrices else "GW"
    crew_map = _round_robin(location_ids, crew_list)
    dup_set = _dup_wells(location_ids, dup_frequency)

    expected_samples: List[ExpectedSampleRow] = []
    crew_bottle_totals: Dict[str, int] = {loc: 0 for loc in location_ids}

    for seq, location_id in enumerate(location_ids, start=1):
        coc_num = _coc_number(coc_prefix, seq)
        assigned = crew_map[location_id]
        is_dup_well = location_id in dup_set

        for group_name, _analyte_names in analyte_groups.items():
            sampling_meta = group_sampling.get(group_name, {})
            container = sampling_meta.get("container", "")
            preservative = sampling_meta.get("preservative", "")
            hold_time_hr = int(sampling_meta.get("hold_time_hr", 0))
            bottles = int(sampling_meta.get("bottles", 1))

            # Primary sample
            expected_samples.append(ExpectedSampleRow(
                sample_id=_sample_id(location_id, date_compact,
                                     primary_matrix, False),
                location_id=location_id,
                event_date=event_date,
                matrix=primary_matrix,
                analyte_group=group_name,
                sample_type="Regular",
                container_type=container,
                preservative=preservative,
                hold_time_hr=hold_time_hr,
                bottle_count=bottles,
                coc_number=coc_num,
                assigned_to=assigned,
            ))
            crew_bottle_totals[location_id] += bottles

            # Field duplicate (counts as real bottles for crew logistics)
            if is_dup_well:
                expected_samples.append(ExpectedSampleRow(
                    sample_id=_sample_id(location_id, date_compact,
                                         primary_matrix, True),
                    location_id=location_id,
                    event_date=event_date,
                    matrix=primary_matrix,
                    analyte_group=group_name,
                    sample_type="Field Duplicate",
                    container_type=container,
                    preservative=preservative,
                    hold_time_hr=hold_time_hr,
                    bottle_count=bottles,
                    coc_number=coc_num,
                    assigned_to=assigned,
                ))
                crew_bottle_totals[location_id] += bottles

    crew_assignments = [
        CrewAssignmentRow(
            location_id=loc,
            assigned_to=crew_map[loc],
            bottle_count=crew_bottle_totals[loc],
        )
        for loc in location_ids
    ]

    return SamplingEventPlan(
        event_name=event_name,
        event_date=event_date,
        site_id=site_id,
        site_name=site_name,
        lab_name=lab_name,
        coc_prefix=coc_prefix,
        run_id=run_id,
        expected_samples=expected_samples,
        crew_assignments=crew_assignments,
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_create_sampling_event.py -v
```

Expected: all 18 PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all existing tests still pass (new module adds nothing that conflicts).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/create_sampling_event.py \
        tests/envmon/test_create_sampling_event.py
git commit -m "feat(envmon): create_sampling_event — pre-field planner dataclasses and logic"
```

---

### Task 2: XLSX writer — `sampling_event_writer.py`

**Files:**
- Create: `autogis/core/envmon/sampling_event_writer.py`
- Create: `tests/envmon/test_sampling_event_writer.py`

**Interfaces:**
- Consumes: `SamplingEventPlan`, `ExpectedSampleRow`, `CrewAssignmentRow` from Task 1
- Produces:
  - `write_sampling_event_workbook(plan: SamplingEventPlan, out_path: Path) -> Path`
    Returns the path written so the CLI can echo it.
  - Three sheets: `Expected_Samples`, `Crew_Assignment`, `COC_Draft`

**Sheet column specs:**

`Expected_Samples` columns (row per `ExpectedSampleRow`):
`SampleID | LocationID | EventDate | Matrix | AnalyteGroup | SampleType | ContainerType | Preservative | HoldTime_hr | BottleCount | COCNumber | AssignedTo`

`Crew_Assignment` columns (row per `CrewAssignmentRow`):
`LocationID | AssignedTo | BottleCount`

`COC_Draft` columns (one row per `ExpectedSampleRow`, formatted for field use):
`COCNumber | SampleID | LocationID | EventDate | Matrix | AnalyteGroup | SampleType | ContainerType | Preservative | HoldTime_hr | BottleCount | LabName | ExtraBottles | SamplerSignature | DateTimeSampled`
(`ExtraBottles`, `SamplerSignature`, `DateTimeSampled` are blank columns for field crew to fill in)

---

- [ ] **Step 1: Write failing writer tests**

Create `tests/envmon/test_sampling_event_writer.py`:

```python
"""Tests for sampling_event_writer — arcpy-free, openpyxl only."""
import pytest
from pathlib import Path

from autogis.core.envmon.create_sampling_event import (
    build_sampling_event_plan,
)
from autogis.core.envmon.sampling_event_writer import (
    write_sampling_event_workbook,
)

SITE = {"site_id": "H281", "site_name": "H281 Glasgow"}
EVENT = {
    "event_name": "2026-Q2",
    "event_date": "2026-07-15",
    "coc_prefix": "H281-COC",
    "lab_name": "TestAmerica Seattle",
    "matrices": ["GW"],
    "location_ids": ["MW-1", "MW-2"],
    "crew_list": ["Alice Smith"],
    "dup_frequency": 0,
    "analyte_groups": {
        "VOCs": ["Benzene", "Toluene"],
        "Metals": ["Arsenic"],
    },
    "group_sampling": {
        "VOCs": {"container": "40mL VOA", "preservative": "HCl",
                 "hold_time_hr": 14, "bottles": 1},
        "Metals": {"container": "250mL PP", "preservative": "HNO3",
                   "hold_time_hr": 180, "bottles": 1},
    },
}
ADICT = {
    "Benzene": {"abbreviation": "B", "display_order": 10,
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Toluene": {"abbreviation": "T", "display_order": 20,
                "default_units_by_matrix": {"GW": "ug/L"}},
    "Arsenic": {"abbreviation": "As", "display_order": 30,
                "default_units_by_matrix": {"GW": "ug/L"}},
}


@pytest.fixture
def plan():
    return build_sampling_event_plan(SITE, EVENT, ADICT, run_id="writer-test-001")


@pytest.fixture
def wb_path(plan, tmp_path):
    out = tmp_path / "H281_2026-Q2_sampling_plan.xlsx"
    write_sampling_event_workbook(plan, out)
    return out


def test_file_is_created(wb_path):
    assert wb_path.exists()
    assert wb_path.stat().st_size > 0


def test_workbook_has_three_sheets(wb_path):
    import openpyxl
    wb = openpyxl.load_workbook(wb_path)
    assert set(wb.sheetnames) == {"Expected_Samples", "Crew_Assignment", "COC_Draft"}


def test_expected_samples_header(wb_path):
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["Expected_Samples"]
    headers = [ws.cell(1, c).value for c in range(1, 13)]
    assert "SampleID" in headers
    assert "AnalyteGroup" in headers
    assert "COCNumber" in headers


def test_expected_samples_row_count(wb_path):
    """2 wells × 2 groups = 4 primary rows + 1 header = 5 rows total."""
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["Expected_Samples"]
    # max_row includes header
    assert ws.max_row == 5


def test_crew_assignment_header(wb_path):
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["Crew_Assignment"]
    headers = [ws.cell(1, c).value for c in range(1, 4)]
    assert "LocationID" in headers
    assert "AssignedTo" in headers
    assert "BottleCount" in headers


def test_crew_assignment_row_count(wb_path):
    """2 wells = 2 data rows + 1 header = 3 rows."""
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["Crew_Assignment"]
    assert ws.max_row == 3


def test_coc_draft_header(wb_path):
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["COC_Draft"]
    headers = [ws.cell(1, c).value for c in range(1, 16)]
    assert "COCNumber" in headers
    assert "SampleID" in headers
    assert "SamplerSignature" in headers
    assert "DateTimeSampled" in headers


def test_coc_draft_row_count(wb_path):
    """Same row count as Expected_Samples (1-to-1 map)."""
    import openpyxl
    wb = openpyxl.load_workbook(wb_path)
    es_rows = wb["Expected_Samples"].max_row
    coc_rows = wb["COC_Draft"].max_row
    assert coc_rows == es_rows


def test_returns_written_path(plan, tmp_path):
    out = tmp_path / "plan.xlsx"
    returned = write_sampling_event_workbook(plan, out)
    assert returned == out


def test_sample_id_in_expected_samples_sheet(wb_path):
    import openpyxl
    ws = openpyxl.load_workbook(wb_path)["Expected_Samples"]
    col_a = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
    assert "MW-1-20260715-GW" in col_a
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_sampling_event_writer.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create `autogis/core/envmon/sampling_event_writer.py`**

```python
"""sampling_event_writer.py — serialize a SamplingEventPlan to XLSX.

Three-sheet workbook:
  Expected_Samples  — one row per (well × analyte_group), includes FD rows
  Crew_Assignment   — one row per well
  COC_Draft         — same rows as Expected_Samples, formatted for field crew

Headless: openpyxl only, no arcpy.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import openpyxl
from openpyxl.styles import Font, PatternFill

from .create_sampling_event import SamplingEventPlan, ExpectedSampleRow, CrewAssignmentRow

_HEADER_FONT = Font(bold=True)
_HEADER_FILL = PatternFill(fill_type="solid", fgColor="D9E1F2")

_ES_HEADERS = [
    "SampleID", "LocationID", "EventDate", "Matrix", "AnalyteGroup",
    "SampleType", "ContainerType", "Preservative", "HoldTime_hr",
    "BottleCount", "COCNumber", "AssignedTo",
]

_CA_HEADERS = ["LocationID", "AssignedTo", "BottleCount"]

_COC_HEADERS = [
    "COCNumber", "SampleID", "LocationID", "EventDate", "Matrix",
    "AnalyteGroup", "SampleType", "ContainerType", "Preservative",
    "HoldTime_hr", "BottleCount", "LabName", "ExtraBottles",
    "SamplerSignature", "DateTimeSampled",
]


def _write_header(ws, headers: List[str]) -> None:
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(1, col, h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL


def _row_es(r: ExpectedSampleRow) -> list:
    return [
        r.sample_id, r.location_id, r.event_date, r.matrix,
        r.analyte_group, r.sample_type, r.container_type, r.preservative,
        r.hold_time_hr, r.bottle_count, r.coc_number, r.assigned_to,
    ]


def _row_ca(r: CrewAssignmentRow) -> list:
    return [r.location_id, r.assigned_to, r.bottle_count]


def _row_coc(r: ExpectedSampleRow, lab_name: str) -> list:
    return [
        r.coc_number, r.sample_id, r.location_id, r.event_date,
        r.matrix, r.analyte_group, r.sample_type, r.container_type,
        r.preservative, r.hold_time_hr, r.bottle_count,
        lab_name,
        "",   # ExtraBottles — blank for field crew
        "",   # SamplerSignature — blank for field crew
        "",   # DateTimeSampled — blank for field crew
    ]


def write_sampling_event_workbook(
    plan: SamplingEventPlan,
    out_path: Path,
) -> Path:
    """Write the plan to a three-sheet XLSX workbook and return out_path."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default empty sheet

    # ── Expected_Samples ──
    ws_es = wb.create_sheet("Expected_Samples")
    _write_header(ws_es, _ES_HEADERS)
    for row_idx, sample in enumerate(plan.expected_samples, start=2):
        for col, val in enumerate(_row_es(sample), start=1):
            ws_es.cell(row_idx, col, val)

    # ── Crew_Assignment ──
    ws_ca = wb.create_sheet("Crew_Assignment")
    _write_header(ws_ca, _CA_HEADERS)
    for row_idx, assignment in enumerate(plan.crew_assignments, start=2):
        for col, val in enumerate(_row_ca(assignment), start=1):
            ws_ca.cell(row_idx, col, val)

    # ── COC_Draft ──
    ws_coc = wb.create_sheet("COC_Draft")
    _write_header(ws_coc, _COC_HEADERS)
    for row_idx, sample in enumerate(plan.expected_samples, start=2):
        for col, val in enumerate(_row_coc(sample, plan.lab_name), start=1):
            ws_coc.cell(row_idx, col, val)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return out_path
```

- [ ] **Step 4: Run writer tests**

```
python -m pytest tests/envmon/test_sampling_event_writer.py -v
```

Expected: all 10 PASS.

- [ ] **Step 5: Run the full suite**

```
python -m pytest -q
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/sampling_event_writer.py \
        tests/envmon/test_sampling_event_writer.py
git commit -m "feat(envmon): sampling_event_writer — three-sheet XLSX workbook for field plan"
```

---

### Task 3: CLI command — `envmon create-sampling-event`

**Files:**
- Modify: `autogis/adapters/cli.py`
- Create: `tests/envmon/test_cli_create_sampling_event.py`

**Interfaces:**
- Consumes: `build_sampling_event_plan`, `write_sampling_event_workbook`, `load_event_config` from Tasks 1–2
- Produces: CLI exit 0 with workbook path echoed; exit 1 on `ConfigError` or `ValueError`

**CLI surface:**

```
autogis envmon create-sampling-event \
    --site  path/to/site.yaml \
    --event path/to/event.yaml \
    --analytes path/to/analyte_dictionary.yaml \
    --out-dir path/to/output/dir
```

All four options are required. Output filename is `{site_id}_{event_name}_sampling_plan.xlsx` inside `--out-dir`.

---

- [ ] **Step 1: Write failing CLI tests**

Create `tests/envmon/test_cli_create_sampling_event.py`:

```python
"""CLI smoke tests for envmon create-sampling-event — arcpy-free."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


# ── helpers ───────────────────────────────────────────────────────────────

def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_site(tmp_path: Path) -> Path:
    p = tmp_path / "site.json"
    _write_json(p, {
        "site_id": "H281",
        "site_name": "H281 Glasgow",
        "project_number": "P-001",
        "address": "1 Test St",
        "city": "Glasgow",
        "state": "MT",
        "coordinate_system": "NAD83 / UTM Zone 12N",
        "default_gdb": "H281.gdb",
        "default_aprx_template": "template.aprx",
        "monitoring_wells_fc": "MonitoringWells",
        "soil_borings_fc": "SoilBorings",
        "site_boundary_fc": "SiteBoundary",
    })
    return p


def _minimal_event(tmp_path: Path) -> Path:
    p = tmp_path / "event.json"
    _write_json(p, {
        "event_name": "2026-Q2",
        "event_date": "2026-07-15",
        "coc_prefix": "H281-COC",
        "lab_name": "TestAmerica",
        "matrices": ["GW"],
        "location_ids": ["MW-1", "MW-2"],
        "crew_list": ["Alice Smith"],
        "dup_frequency": 0,
        "analyte_groups": {"VOCs": ["Benzene"]},
        "group_sampling": {
            "VOCs": {"container": "40mL VOA", "preservative": "HCl",
                     "hold_time_hr": 14, "bottles": 1}
        },
    })
    return p


def _minimal_analytes(tmp_path: Path) -> Path:
    p = tmp_path / "analytes.json"
    _write_json(p, {
        "analytes": {
            "Benzene": {"abbreviation": "B", "display_order": 10,
                        "default_units_by_matrix": {"GW": "ug/L"}}
        }
    })
    return p


# ── tests ─────────────────────────────────────────────────────────────────

def test_command_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "create-sampling-event" in result.output


def test_create_sampling_event_exit_zero(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output


def test_create_sampling_event_writes_workbook(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    xlsx_files = list(out_dir.glob("*.xlsx"))
    assert len(xlsx_files) == 1
    assert xlsx_files[0].name == "H281_2026-Q2_sampling_plan.xlsx"


def test_create_sampling_event_echoes_path(tmp_path):
    site = _minimal_site(tmp_path)
    event = _minimal_event(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(event),
        "--analytes", str(analytes),
        "--out-dir", str(out_dir),
    ])
    assert "sampling_plan.xlsx" in result.output


def test_missing_location_ids_exits_nonzero(tmp_path):
    site = _minimal_site(tmp_path)
    analytes = _minimal_analytes(tmp_path)
    bad_event = tmp_path / "bad_event.json"
    _write_json(bad_event, {
        "event_name": "2026-Q2",
        "event_date": "2026-07-15",
        "coc_prefix": "H281-COC",
        "lab_name": "TestAmerica",
        "matrices": ["GW"],
        "location_ids": [],   # empty — should fail
        "crew_list": ["Alice Smith"],
        "dup_frequency": 0,
        "analyte_groups": {"VOCs": ["Benzene"]},
        "group_sampling": {},
    })
    result = CliRunner().invoke(autogis, [
        "envmon", "create-sampling-event",
        "--site", str(site),
        "--event", str(bad_event),
        "--analytes", str(analytes),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_cli_create_sampling_event.py -v
```

Expected: `FAIL` — command not registered yet.

- [ ] **Step 3: Add command to `autogis/adapters/cli.py`**

Find the block after `build_survey_form` command (search for `@envmon.command("build-survey-form")`). Add after its closing line:

```python
@envmon.command("create-sampling-event")
@click.option("--site", "site_path", required=True, type=click.Path(exists=True),
              help="Path to site config YAML or JSON.")
@click.option("--event", "event_path", required=True, type=click.Path(exists=True),
              help="Path to event config YAML or JSON.")
@click.option("--analytes", "analytes_path", required=True,
              type=click.Path(exists=True),
              help="Path to analyte dictionary YAML or JSON.")
@click.option("--out-dir", "out_dir", required=True, type=click.Path(),
              help="Output directory for the sampling plan workbook.")
def create_sampling_event_cmd(site_path, event_path, analytes_path, out_dir):
    """Tool 2.7: generate pre-field sampling event plan (headless).

    Reads a well list + event metadata + analyte dict and writes a
    three-sheet planning workbook: expected samples, crew assignment,
    and COC draft.
    """
    import uuid
    from autogis.core.common.config import (
        SiteConfig, load_analyte_dictionary, ConfigError)
    from autogis.core.envmon.create_sampling_event import (
        build_sampling_event_plan, load_event_config)
    from autogis.core.envmon.sampling_event_writer import (
        write_sampling_event_workbook)

    try:
        site_cfg = SiteConfig.load(Path(site_path))
        event_cfg = load_event_config(Path(event_path))
        analyte_dict = load_analyte_dictionary(Path(analytes_path))
    except ConfigError as exc:
        raise click.ClickException(str(exc))

    try:
        plan = build_sampling_event_plan(
            site_cfg.data, event_cfg, analyte_dict,
            run_id=str(uuid.uuid4()),
        )
    except (ValueError, KeyError) as exc:
        raise click.ClickException(str(exc))

    out = Path(out_dir) / f"{plan.site_id}_{plan.event_name}_sampling_plan.xlsx"
    write_sampling_event_workbook(plan, out)
    click.echo(f"Sampling plan written: {out}")
    click.echo(f"  {len(plan.expected_samples)} expected sample rows "
               f"({sum(1 for r in plan.expected_samples if r.sample_type == 'Regular')} primary, "
               f"{sum(1 for r in plan.expected_samples if r.sample_type == 'Field Duplicate')} field dups)")
    click.echo(f"  {len(plan.crew_assignments)} wells assigned across "
               f"{len({r.assigned_to for r in plan.crew_assignments})} crew member(s)")
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_cli_create_sampling_event.py -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

Expected: all tests pass, no regressions.

- [ ] **Step 6: Verify help text via CliRunner**

Add to `tests/envmon/test_cli_create_sampling_event.py`:

```python
def test_help_text_shows_required_options():
    result = CliRunner().invoke(autogis,
                                ["envmon", "create-sampling-event", "--help"])
    assert result.exit_code == 0
    assert "--site" in result.output
    assert "--event" in result.output
    assert "--analytes" in result.output
    assert "--out-dir" in result.output
    assert "Tool 2.7" in result.output
```

Run: `python -m pytest tests/envmon/test_cli_create_sampling_event.py::test_help_text_shows_required_options -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py \
        tests/envmon/test_cli_create_sampling_event.py
git commit -m "feat(cli): add create-sampling-event command (headless, Tool 2.7)"
```

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| SiteConfig.load() requires all SITE_REQUIRED keys including GIS paths (default_gdb, monitoring_wells_fc, etc.) that aren't needed for this headless tool | Certain | CLI tests use JSON with all SITE_REQUIRED keys (see `_minimal_site` fixture). If this is painful in production, a future task can add `SiteConfig.load_minimal()` — out of scope here. |
| event_config.analyte_groups callers pass dict-of-dicts instead of dict-of-lists | Low | `build_sampling_event_plan` skips non-list values in the analyte validation loop (`if isinstance(names, list)`), so it won't crash — but it will also silently omit the group's analytes from validation. Future hardening: add an explicit type guard; out of scope for v1. |
| Output filename has characters invalid on Windows if event_name contains slashes or colons | Low | Future hardening: sanitize with `re.sub(r'[^\w\-]', '_', plan.event_name)` in the CLI before building `out`. Out of scope for v1; event configs should use safe names (e.g. "2026-Q2"). |

## Self-Review Checklist

**Spec coverage:**
- [x] Well list → expected samples: Task 1, `build_sampling_event_plan()`, `ExpectedSampleRow`
- [x] Crew assignment: Task 1, `CrewAssignmentRow`, round-robin `_assign_crew`
- [x] COC draft: Task 2, `COC_Draft` sheet in writer
- [x] Headless (no arcpy): no arcpy import anywhere in plan; `_guard()` not called
- [x] Inputs from site config + event metadata + analyte dict: Task 3 CLI wires all three
- [x] CLI surface: Task 3 `create-sampling-event` command
- [x] TDD order: tests written before implementation in each task
- [x] QA samples: `dup_frequency` documented; trip/equipment blanks explicit non-goal
- [x] SampleID format matches form builder: `{WellID}-{YYYYMMDD}-{Matrix}`
- [x] `analyte_groups` contract preserved: stays `{group: [names]}`
- [x] `analyte_dict` used: validates all analyte names exist before plan is built; `test_unknown_analyte_raises` covers the error path
- [x] dup bottle count correct: `crew_bottle_totals` incremented for both primary and FD rows; `test_dup_well_bottle_count_includes_fd_bottles` covers it
- [x] `run_id` injected, not internal: deterministic tests possible

**Placeholder scan:** none found.

**Type consistency:** `SamplingEventPlan`, `ExpectedSampleRow`, `CrewAssignmentRow` defined in Task 1 and imported by name in Tasks 2 and 3 — consistent.
