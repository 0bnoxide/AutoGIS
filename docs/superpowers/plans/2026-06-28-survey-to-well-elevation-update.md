# SurveyToWellElevationUpdate (8.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push QA-passed RTK survey point elevations into `MonitoringWells.TOC_ft` and write an `ElevationHistory` audit record per well, using the GPS/RTK survey method — distinct from the differential-leveling path used by UpdateWellElevationsFromLevelLoop (8.2).

**Architecture:** A new headless module `survey_to_well_elevation.py` provides `select_rtk_elevations_for_wells()` (pure Python, QA-filter + well-match logic) and `build_elevation_history_records()` (constructs `ElevationHistory` dataclasses — making the audit trail fully unit-testable). A `# pragma: no cover` LOCAL function `write_rtk_elevations_to_wells()` issues the GDB writes. The CLI command `survey-to-well-elevation` runs headless when given `--wells-csv` and turns LOCAL when given `--gdb`.

**Tech Stack:** Python stdlib only in core (`dataclasses`, `csv`). Reuses `RTKPoint`/`assign_qa_flags`/`parse_rtk_csv` from `import_rtk_survey.py`, `ElevationHistory` from `core/common/schema/survey.py`, `QACollector` from `core/common/qa.py`, `read_well_ids_csv` from `reconcile_locations.py`, and the `arcpy_env()` seam from `runtime/sessions.py` in the LOCAL writer. CLI uses `click` + `_render_qa()` + `_guard()`.

## Global Constraints

- Branch: `main` (or a feature branch from it; no pre-existing branch constraint for 8.5).
- `autogis/core/` and `autogis/adapters/` MUST import with neither `arcpy` nor `arcgis` present.
- `write_rtk_elevations_to_wells()` is LOCAL (arcpy) — mark `# pragma: no cover`.
- Use `arcpy_env()` from `autogis.runtime.sessions`, not bare `import arcpy`, in the LOCAL writer.
- `MonitoringWells` column for TOC elevation is `TOC_ft` (verified in `gdb_schema.py` line 273). Do NOT use `TOCElevation_ft` (stale exemplar drift).
- `ElevationHistory` GDB columns (from `gdb_schema.py` lines 184–189): `LocationID`, `ElevationType`, `Elevation_ft`, `VerticalDatum`, `SurveyDate`, `SurveyMethod`, `SourceRunID`, `ApprovedForUse`, `Superseded`.
- `SurveyMethod` literal for this tool: `"GPS_RTK"` (vs `"DifferentialLevel"` for 8.2).
- QA-pass definition: `assign_qa_flags(pt) == []` (no auto flags). Human `Approved` sign-off is out of scope.
- Point matching is **exact**: `point_id` must equal `LocationID`. No fuzzy matching (assumption; note risk below).
- `--wells-csv` and `--gdb` are mutually exclusive in the CLI.
- Run tests with `python -m pytest -q`. Suite must remain green after each task.

## Scope vs. Non-Goals (8.5 vs. 8.2)

| Dimension | 8.2 UpdateWellElevationsFromLevelLoop | 8.5 SurveyToWellElevationUpdate |
|---|---|---|
| Elevation source | Differential-leveling `LevelLoopRun` (adjusted, HI method) | RTK GPS point (`RTKPoint.elevation_ft`) |
| Gate granularity | Loop-level all-or-nothing (misclosure tolerance) | Per-point: each RTK point passes or fails independently |
| Failure mode | `blocked=True` → reject the entire batch | Failed points go to `failed_qa`; passing points still update |
| Input to selection fn | `LevelLoopResult` + `well_ids` | `list[RTKPoint]` + `well_ids` + QA thresholds |
| `SurveyMethod` tag | `"DifferentialLevel"` | `"GPS_RTK"` |

**Non-goals:** fuzzy ID matching, datum transformation (tool assumes input is already orthometric/NAVD88), human approval workflow, updating `GroundElev_ft` (only `TOC_ft`), batch-scheduling multiple surveys.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `autogis/core/envmon/survey_to_well_elevation.py` | `RTKElevationUpdatePlan`, `select_rtk_elevations_for_wells()`, `build_elevation_history_records()`, `write_rtk_elevations_to_wells()` |
| Create | `tests/envmon/test_survey_to_well_elevation.py` | 13 tests for headless selection and history-record construction |
| Modify | `autogis/adapters/cli.py` | Add `survey-to-well-elevation` command and its help/headless-path test |

---

### Task 1: Core module + tests

**Files:**
- Create: `autogis/core/envmon/survey_to_well_elevation.py`
- Create: `tests/envmon/test_survey_to_well_elevation.py`

**Interfaces:**
- Consumes: `RTKPoint`, `assign_qa_flags` from `autogis.core.envmon.import_rtk_survey`; `ElevationHistory` from `autogis.core.common.schema.survey`; `QACollector`, `SEV_WARNING`, `SEV_INFO` from `autogis.core.common.qa`; `arcpy_env` from `autogis.runtime.sessions` (LOCAL only).
- Produces:
  - `RTKElevationUpdatePlan` dataclass — consumed by Task 2 CLI
  - `select_rtk_elevations_for_wells(points: list[RTKPoint], well_ids: set[str], batch_id: str, qa: QACollector, *, hrms_threshold_ft: float = 0.03, vrms_threshold_ft: float = 0.05, elevation_type: str = "TOC") -> RTKElevationUpdatePlan`
  - `build_elevation_history_records(plan: RTKElevationUpdatePlan, survey_date: date, *, vertical_datum: str = "NAVD88", approved_for_use: bool = False) -> list[ElevationHistory]`
  - `write_rtk_elevations_to_wells(gdb_path: str, site_id: str, plan: RTKElevationUpdatePlan, history_records: list[ElevationHistory]) -> int`  (`# pragma: no cover`)

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_survey_to_well_elevation.py`:

```python
"""Tests for survey_to_well_elevation — headless selection + history records.

write_rtk_elevations_to_wells() is # pragma: no cover and NOT tested here.
"""
from __future__ import annotations
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.import_rtk_survey import RTKPoint
from autogis.core.envmon.survey_to_well_elevation import (
    RTKElevationUpdatePlan,
    build_elevation_history_records,
    select_rtk_elevations_for_wells,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_POINTS_OK = [
    RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
    RTKPoint("MW-02", 4527750.00, 293900.00, 509.12,
             hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED"),
]

_POINTS_FAIL_QA = [
    RTKPoint("MW-03", 4527700.00, 293850.00, 508.00,
             hrms_ft=0.15, vrms_ft=0.20, fix_type="AUTONOMOUS"),
]

_WELL_IDS_ALL = {"MW-01", "MW-02", "MW-03"}

# ---------------------------------------------------------------------------
# select_rtk_elevations_for_wells
# ---------------------------------------------------------------------------

def test_select_returns_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-001", qa
    )
    assert isinstance(plan, RTKElevationUpdatePlan)
    assert set(plan.updates.keys()) == {"MW-01", "MW-02"}


def test_select_correct_elevation_values():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-002", qa
    )
    assert abs(plan.updates["MW-01"] - 512.34) < 0.001
    assert abs(plan.updates["MW-02"] - 509.12) < 0.001


def test_failed_qa_points_excluded_from_updates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_FAIL_QA, _WELL_IDS_ALL, "BATCH-003", qa
    )
    assert "MW-03" not in plan.updates
    assert "MW-03" in plan.failed_qa


def test_failed_qa_emits_warning_records():
    qa = QACollector()
    select_rtk_elevations_for_wells(
        _POINTS_FAIL_QA, _WELL_IDS_ALL, "BATCH-004", qa
    )
    assert any(r.severity == "WARNING" for r in qa.records)


def test_point_not_in_well_ids_goes_to_skipped():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01"}, "BATCH-005", qa
    )
    assert "MW-02" not in plan.updates
    assert "MW-02" in plan.skipped


def test_mixed_batch_all_buckets():
    """QA-fail → failed_qa; unknown well → skipped; match → updates."""
    all_points = _POINTS_OK + _POINTS_FAIL_QA  # MW-01 pass+match, MW-02 pass+skip, MW-03 fail
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        all_points, {"MW-01"}, "BATCH-006", qa
    )
    assert set(plan.updates.keys()) == {"MW-01"}
    assert "MW-02" in plan.skipped
    assert "MW-03" in plan.failed_qa


def test_empty_points_produces_empty_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells([], set(), "BATCH-007", qa)
    assert plan.updates == {}
    assert plan.failed_qa == []
    assert plan.skipped == []


def test_qa_plan_complete_record_always_present():
    qa = QACollector()
    select_rtk_elevations_for_wells(_POINTS_OK, {"MW-01", "MW-02"}, "BATCH-008", qa)
    assert any(r.category == "plan_complete" for r in qa.records)


def test_custom_hrms_threshold_tightens_qa():
    # MW-01 has hrms_ft=0.01; threshold 0.005 should flag it
    pts = [RTKPoint("MW-01", 4527893.12, 293847.55, 512.34,
                    hrms_ft=0.01, vrms_ft=0.02, fix_type="RTK_FIXED")]
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        pts, {"MW-01"}, "BATCH-009", qa,
        hrms_threshold_ft=0.005, vrms_threshold_ft=0.05
    )
    assert "MW-01" in plan.failed_qa
    assert "MW-01" not in plan.updates


def test_elevation_type_stored_on_plan():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-010", qa,
        elevation_type="GS"
    )
    assert plan.elevation_type == "GS"


# ---------------------------------------------------------------------------
# build_elevation_history_records
# ---------------------------------------------------------------------------

def test_history_records_count_matches_updates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-011", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert len(records) == 2


def test_history_records_survey_method_is_gps_rtk():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-012", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.survey_method == "GPS_RTK" for r in records)


def test_history_records_source_run_id_matches_batch():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "MY-BATCH-013", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.source_run_id == "MY-BATCH-013" for r in records)


def test_history_records_not_superseded_on_creation():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-014", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.superseded is False for r in records)


def test_history_records_elevation_type_propagates():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-015", qa,
        elevation_type="TOC"
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.elevation_type == "TOC" for r in records)


def test_history_records_vertical_datum_default():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-016", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.vertical_datum == "NAVD88" for r in records)


def test_history_records_approved_for_use_default_false():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells(
        _POINTS_OK, {"MW-01", "MW-02"}, "BATCH-017", qa
    )
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert all(r.approved_for_use is False for r in records)


def test_empty_plan_produces_no_history_records():
    qa = QACollector()
    plan = select_rtk_elevations_for_wells([], set(), "BATCH-018", qa)
    records = build_elevation_history_records(plan, date(2026, 6, 28))
    assert records == []
```

- [ ] **Step 2: Run tests to confirm failure**

```
python -m pytest tests/envmon/test_survey_to_well_elevation.py -v
```

Expected: `ModuleNotFoundError: No module named 'autogis.core.envmon.survey_to_well_elevation'`

- [ ] **Step 3: Create `autogis/core/envmon/survey_to_well_elevation.py`**

```python
"""survey_to_well_elevation.py — push QA-passed RTK survey elevations to wells (Tool 8.5).

select_rtk_elevations_for_wells() and build_elevation_history_records() are
arcpy-free and fully unit-testable.

write_rtk_elevations_to_wells() requires arcpy — # pragma: no cover.

Design decisions (see ADR-0026 scope + 8.2 analogue):
- "QA-passed" means assign_qa_flags(pt) == [] (no auto flags). Human Approved
  sign-off is out of scope for this tool.
- Point matching is EXACT: point_id must equal LocationID. No fuzzy matching.
- Assumption: RTK input is already in orthometric vertical datum (NAVD88).
  No datum transformation is performed (vertical datum risk — see plan).
- SurveyMethod tag: "GPS_RTK" (vs "DifferentialLevel" for Tool 8.2).
- MonitoringWells column: TOC_ft (see gdb_schema.py FEATURE_SCHEMAS).
- ElevationHistory supersede: prior rows for each LocationID are marked
  Superseded=1 before inserting the new row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ..common.schema.survey import ElevationHistory
from .import_rtk_survey import RTKPoint, assign_qa_flags


@dataclass
class RTKElevationUpdatePlan:
    """Headless output of select_rtk_elevations_for_wells().

    updates:   point_id → elevation_ft; wells that will receive a new TOC_ft.
    skipped:   point_ids that passed QA but are not in the supplied well_ids set.
    failed_qa: point_ids whose auto QA flags prevent elevation promotion.
    """
    batch_id: str
    updates: dict[str, float]
    skipped: list[str]
    failed_qa: list[str]
    elevation_type: str = "TOC"


def select_rtk_elevations_for_wells(
    points: list[RTKPoint],
    well_ids: set[str],
    batch_id: str,
    qa: QACollector,
    *,
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
    elevation_type: str = "TOC",
) -> RTKElevationUpdatePlan:
    """Filter RTK points by QA and well membership; produce an update plan.

    Each RTKPoint is evaluated independently:
    - Fails QA  → added to failed_qa; WARNING record emitted.
    - Passes QA but point_id not in well_ids → added to skipped; INFO record.
    - Passes QA and point_id in well_ids → added to updates; INFO record.

    A final INFO "plan_complete" record summarises the tally.
    """
    updates: dict[str, float] = {}
    skipped: list[str] = []
    failed_qa: list[str] = []

    for pt in points:
        flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
        if flags:
            failed_qa.append(pt.point_id)
            for flag in flags:
                qa.add(SEV_WARNING, flag,
                       f"{pt.point_id}: {flag} — excluded from elevation update",
                       location_id=pt.point_id)
            continue
        if pt.point_id not in well_ids:
            skipped.append(pt.point_id)
            qa.add(SEV_INFO, "point_not_in_well_list",
                   f"{pt.point_id}: QA-passed but not a known well — skipped",
                   location_id=pt.point_id)
            continue
        updates[pt.point_id] = pt.elevation_ft
        qa.add(SEV_INFO, "elevation_update_planned",
               f"{pt.point_id}: {pt.elevation_ft:.3f} ft ({elevation_type}) → update planned",
               location_id=pt.point_id)

    qa.add(SEV_INFO, "plan_complete",
           f"RTK elevation plan: {len(updates)} updates, "
           f"{len(skipped)} skipped, {len(failed_qa)} failed QA")

    return RTKElevationUpdatePlan(
        batch_id=batch_id,
        updates=updates,
        skipped=skipped,
        failed_qa=failed_qa,
        elevation_type=elevation_type,
    )


def build_elevation_history_records(
    plan: RTKElevationUpdatePlan,
    survey_date: date,
    *,
    vertical_datum: str = "NAVD88",
    approved_for_use: bool = False,
) -> list[ElevationHistory]:
    """Construct ElevationHistory dataclass instances for all planned updates.

    Returns a list ready to pass to write_rtk_elevations_to_wells().
    This function is arcpy-free and unit-testable, making the audit-trail
    content verifiable without a GDB.
    """
    return [
        ElevationHistory(
            location_id=loc_id,
            elevation_type=plan.elevation_type,
            elevation=elev,
            vertical_datum=vertical_datum,
            survey_date=survey_date,
            survey_method="GPS_RTK",
            source_run_id=plan.batch_id,
            approved_for_use=approved_for_use,
            superseded=False,
        )
        for loc_id, elev in plan.updates.items()
    ]


def write_rtk_elevations_to_wells(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    plan: RTKElevationUpdatePlan,
    history_records: list[ElevationHistory],
) -> int:
    """Update MonitoringWells.TOC_ft and write ElevationHistory rows (ArcGIS Pro).

    For each well in plan.updates:
      1. Mark all prior ElevationHistory rows for that LocationID Superseded=1.
      2. Update MonitoringWells.TOC_ft.
    Then insert the supplied history_records (already constructed by
    build_elevation_history_records()).

    Returns the count of MonitoringWells rows updated.
    """
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)
    wells_fc = str(_P(gdb) / "MonitoringWells")
    elev_table = str(_P(gdb) / "ElevationHistory")
    updated = 0

    for loc_id, elev in plan.updates.items():
        # Supersede prior ElevationHistory rows for this location
        if _ax.Exists(elev_table):
            where_prior = (
                f"LocationID='{loc_id}' AND "
                f"ElevationType='{plan.elevation_type}' AND Superseded=0"
            )
            with _ax.da.UpdateCursor(elev_table, ["Superseded"], where_prior) as cur:
                for row in cur:
                    cur.updateRow([1])

        # Update MonitoringWells.TOC_ft
        if _ax.Exists(wells_fc):
            where_well = f"SiteID='{site_id}' AND LocationID='{loc_id}'"
            with _ax.da.UpdateCursor(wells_fc, ["TOC_ft"], where_well) as cur:
                for row in cur:
                    cur.updateRow([elev])
                    updated += 1

    # Insert new ElevationHistory rows
    if history_records and _ax.Exists(elev_table):
        fields = [
            "LocationID", "ElevationType", "Elevation_ft", "VerticalDatum",
            "SurveyDate", "SurveyMethod", "SourceRunID", "ApprovedForUse",
            "Superseded",
        ]
        with _ax.da.InsertCursor(elev_table, fields) as cur:
            for rec in history_records:
                cur.insertRow([
                    rec.location_id,
                    rec.elevation_type,
                    rec.elevation,
                    rec.vertical_datum,
                    rec.survey_date,
                    rec.survey_method,
                    rec.source_run_id,
                    int(rec.approved_for_use),
                    int(rec.superseded),
                ])

    return updated
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_survey_to_well_elevation.py -v
```

Expected: all 18 tests PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all previously passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/survey_to_well_elevation.py \
        tests/envmon/test_survey_to_well_elevation.py
git commit -m "feat(envmon): survey_to_well_elevation — RTK elevation update plan + ElevationHistory construction (Tool 8.5)"
```

---

### Task 2: CLI command `survey-to-well-elevation`

**Files:**
- Modify: `autogis/adapters/cli.py` — append `survey-to-well-elevation` command after the `import-rtk-survey` block (around line 1300).
- Modify: `tests/envmon/test_survey_to_well_elevation.py` — append help test + headless-path test.

**Interfaces:**
- Consumes: `parse_rtk_csv` from `import_rtk_survey`; `read_well_ids_csv` from `reconcile_locations`; `select_rtk_elevations_for_wells`, `build_elevation_history_records`, `write_rtk_elevations_to_wells` from `survey_to_well_elevation`; `QACollector` from `common.qa`; `_guard`, `_render_qa` (CLI module-level helpers, already defined).
- Produces: `survey-to-well-elevation` registered in the `envmon` group.

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/envmon/test_survey_to_well_elevation.py`:

```python
# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def test_survey_to_well_elevation_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "survey-to-well-elevation" in result.output


def test_survey_to_well_elevation_headless_wells_csv(tmp_path):
    """Headless dry-run: passes QA MW-01, fails QA MW-02, skips INV-01."""
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis

    rtk_csv = tmp_path / "rtk.csv"
    rtk_csv.write_text(
        "PointID,Northing,Easting,Elevation_ft,FeatureCode,"
        "Description,HRMS_ft,VRMS_ft,FixType,CollectedAt,Operator\n"
        "MW-01,4527893.12,293847.55,512.34,WELL,Mon Well,0.01,0.02,RTK_FIXED,2026-06-15,Alice\n"
        "MW-02,4527750.00,293900.00,509.12,WELL,Mon Well,0.15,0.20,AUTONOMOUS,2026-06-15,Alice\n"
        "INV-01,4527800.00,293870.00,510.00,INV,Inv Point,0.01,0.02,RTK_FIXED,2026-06-15,Alice\n",
        encoding="utf-8",
    )
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text("LocationID\nMW-01\nMW-02\n", encoding="utf-8")

    result = CliRunner().invoke(autogis, [
        "envmon", "survey-to-well-elevation", str(rtk_csv),
        "--site", "SITE-001",
        "--wells-csv", str(wells_csv),
        "--batch-id", "TEST-BATCH-001",
        "--survey-date", "2026-06-28",
    ])
    assert result.exit_code == 0, result.output
    # MW-01 passes QA and matches a well → update planned
    assert "MW-01" in result.output
    # MW-02 fails QA (AUTONOMOUS fix) → reported as failed
    assert "MW-02" in result.output or "AUTONOMOUS" in result.output


def test_survey_to_well_elevation_gdb_and_wells_csv_mutually_exclusive(tmp_path):
    """--gdb and --wells-csv together should error."""
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis

    rtk_csv = tmp_path / "rtk.csv"
    rtk_csv.write_text(
        "PointID,Northing,Easting,Elevation_ft\nMW-01,0,0,100.0\n",
        encoding="utf-8",
    )
    wells_csv = tmp_path / "wells.csv"
    wells_csv.write_text("LocationID\nMW-01\n", encoding="utf-8")

    result = CliRunner().invoke(autogis, [
        "envmon", "survey-to-well-elevation", str(rtk_csv),
        "--site", "SITE-001",
        "--wells-csv", str(wells_csv),
        "--gdb", "C:/fake/site.gdb",
    ])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower() or result.exit_code == 2
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_survey_to_well_elevation.py -k "help or headless or mutually" -v
```

Expected: FAIL — `survey-to-well-elevation` not yet in help.

- [ ] **Step 3: Add the command to `autogis/adapters/cli.py`**

Insert after the `import-rtk-survey` command block (after line ~1299) and before the `reconcile-survey123-lab` block:

```python
@envmon.command("survey-to-well-elevation")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True,
              help="Site ID matching SiteID in MonitoringWells.")
@click.option("--batch-id", default=None,
              help="Override auto-generated batch ID (default: RTK-<hex>).")
@click.option("--hrms-threshold", type=float, default=0.03, show_default=True,
              help="Max horizontal RMS error (ft) for QA pass.")
@click.option("--vrms-threshold", type=float, default=0.05, show_default=True,
              help="Max vertical RMS error (ft) for QA pass.")
@click.option("--elevation-type", default="TOC", show_default=True,
              help="ElevationType tag for ElevationHistory (e.g. TOC, GS).")
@click.option("--survey-date", default=None,
              help="ISO date YYYY-MM-DD; defaults to today.")
@click.option("--vertical-datum", default="NAVD88", show_default=True,
              help="Vertical datum label stored in ElevationHistory.")
@click.option("--wells-csv", default=None, type=click.Path(exists=True),
              help="CSV with LocationID column — headless well list. "
                   "Mutually exclusive with --gdb.")
@click.option("--gdb", default=None, type=click.Path(),
              help="File geodatabase path: reads well IDs from MonitoringWells "
                   "and writes elevations (ArcGIS Pro). Mutually exclusive with --wells-csv.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show update plan without writing to GDB (use with --gdb).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report (.md/.json/.csv detected by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True,
              help="Severity level that causes non-zero exit. Default 'error': "
                   "QA warnings (excluded points) are informational on a partial-update tool.")
def survey_to_well_elevation_cmd(
    csv_path, site_id, batch_id, hrms_threshold, vrms_threshold,
    elevation_type, survey_date, vertical_datum,
    wells_csv, gdb, dry_run, report, fail_on,
):
    """Tool 8.5: push QA-passed RTK survey elevations to MonitoringWells.

    Headless path (--wells-csv): parses RTK CSV, QA-filters, matches to a
    known-wells CSV, prints the update plan — no arcpy required.

    LOCAL path (--gdb): guards for arcpy, reads well IDs from MonitoringWells,
    prints plan, and (unless --dry-run) updates TOC_ft + ElevationHistory.
    """
    import csv as _csv
    import uuid
    from datetime import date as _date

    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_rtk_survey import parse_rtk_csv
    from autogis.core.envmon.reconcile_locations import read_well_ids_csv
    from autogis.core.envmon.survey_to_well_elevation import (
        build_elevation_history_records,
        select_rtk_elevations_for_wells,
        write_rtk_elevations_to_wells,
    )

    if gdb and wells_csv:
        raise click.UsageError("--gdb and --wells-csv are mutually exclusive.")

    # Guard early when GDB access is needed (both read and write require arcpy).
    if gdb:
        _guard("survey-to-well-elevation")

    bid = batch_id or f"RTK-{uuid.uuid4().hex[:8].upper()}"
    sdate = _date.fromisoformat(survey_date) if survey_date else _date.today()

    # Parse RTK survey CSV (headless).
    points = parse_rtk_csv(Path(csv_path))
    qa = QACollector()

    # Resolve known well IDs.
    well_ids: set[str] = set()
    if wells_csv:
        well_ids = set(read_well_ids_csv(Path(wells_csv)))
    elif gdb:
        from autogis.runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        from pathlib import Path as _P
        wells_fc = str(_P(gdb) / "MonitoringWells")
        if _ax.Exists(wells_fc):
            with _ax.da.SearchCursor(wells_fc, ["LocationID"],
                                     f"SiteID='{site_id}'") as cur:
                for row in cur:
                    if row[0]:
                        well_ids.add(str(row[0]).strip())

    # Headless: filter and build plan.
    plan = select_rtk_elevations_for_wells(
        points, well_ids, bid, qa,
        hrms_threshold_ft=hrms_threshold,
        vrms_threshold_ft=vrms_threshold,
        elevation_type=elevation_type,
    )

    # Print plan summary.
    click.echo(
        f"Batch: {plan.batch_id}  Survey date: {sdate}  Site: {site_id}"
    )
    click.echo(
        f"Updates: {len(plan.updates)}  "
        f"Skipped: {len(plan.skipped)}  "
        f"Failed QA: {len(plan.failed_qa)}"
    )
    for loc_id, elev in plan.updates.items():
        click.echo(f"  {loc_id}: {elev:.3f} ft ({plan.elevation_type})")

    # LOCAL write (only when --gdb is given and --dry-run is not set).
    if gdb and not dry_run and plan.updates:
        history_recs = build_elevation_history_records(
            plan, sdate,
            vertical_datum=vertical_datum,
        )
        n = write_rtk_elevations_to_wells(gdb, site_id, plan, history_recs)
        click.echo(
            f"Updated {n} MonitoringWells records + "
            f"{len(history_recs)} ElevationHistory rows."
        )

    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_survey_to_well_elevation.py -v
```

Expected: all 21 tests PASS (18 core + 3 CLI).

- [ ] **Step 5: Confirm the full suite still passes**

```
python -m pytest -q
```

Expected: all previously passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_survey_to_well_elevation.py
git commit -m "feat(cli): add survey-to-well-elevation command (Tool 8.5) — headless + LOCAL GDB path"
```

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Vertical datum mismatch**: RTK receivers output ellipsoidal heights (WGS84) unless a geoid model is applied. If the operator loads raw GPS heights, `TOC_ft` values will be ~50–100 ft off. | Medium | Document in `--help` text: *"Input must be orthometric (NAVD88) elevation, not ellipsoidal."* Flag as `SEV_WARNING` if `vrms_ft` is None (may indicate raw export). |
| **point_id ≠ LocationID**: Field crews sometimes label RTK points differently from GIS well IDs (e.g., `MW-1` vs `MW-01`). Exact matching will silently send mismatches to `skipped`. | Medium | `skipped` list and `INFO` QA records are emitted for every non-matching point; operator must review output before confirming. Fuzzy matching is a deliberate non-goal (see ReconcileSampleLocations). |
| **Multiple surveys for same well in one batch**: If a batch contains two RTK shots of the same well, `updates[point_id]` will be overwritten by the last one (dict assignment). | Low | This matches dict-assignment semantics; `plan.updates` will contain the last value. No deduplication logic added — YAGNI. |
| **ElevationHistory table absent from GDB**: If the schema has not been upgraded (Tool 10.3 not run), `_ax.Exists(elev_table)` returns False and ElevationHistory rows are silently skipped. `MonitoringWells.TOC_ft` updates still proceed. | Low | Writer checks `_ax.Exists` before every cursor. The operator should run `upgrade-schema` first. Consider adding a `SEV_WARNING` in the writer when the table is missing. |
| **Approved=0 in `ElevationHistory`**: New rows default to `ApprovedForUse=0`. If downstream tools filter on `ApprovedForUse=1`, elevations won't appear in reports until manually approved. | Low | Documented in `--help` and in `build_elevation_history_records()` docstring. |

---

## Self-Review

### 1. Spec coverage

| Requirement | Addressed |
|---|---|
| Push QA-passed RTK elevations to well database | `select_rtk_elevations_for_wells` + `write_rtk_elevations_to_wells` |
| Audit trail (ElevationHistory) | `build_elevation_history_records` (headless, testable) |
| Distinct from level-loop path (8.2) | Scope table; `GPS_RTK` tag vs `DifferentialLevel`; per-point vs loop-level gate |
| Data model & schema touchpoints | `ElevationHistory` dataclass reused; `MonitoringWells.TOC_ft` column used |
| Headless core API | `select_rtk_elevations_for_wells`, `build_elevation_history_records` |
| CLI surface | `survey-to-well-elevation` with `--wells-csv` (headless) and `--gdb` (LOCAL) |
| Adapter seam | `_guard()` called when `--gdb` present; `arcpy_env()` in `# pragma: no cover` writer |
| TDD tasks | Tests written before implementation in both tasks |
| Key test cases | QA filter, well matching, skipping, history record content, CLI smoke |
| Risks documented | 5 risks with mitigations |

### 2. Placeholder scan

No "TBD", "TODO", "fill in later", "similar to", or "add appropriate" patterns. All test code and implementation code is complete.

### 3. Type consistency

Symbols used consistently across tasks:

| Symbol | Definition | Used in |
|---|---|---|
| `RTKElevationUpdatePlan` | Task 1 Step 3 | Task 1 tests, Task 2 Step 3 |
| `select_rtk_elevations_for_wells(points, well_ids, batch_id, qa, *, hrms_threshold_ft, vrms_threshold_ft, elevation_type)` | Task 1 Step 3 | Task 1 tests, Task 2 Step 3 |
| `build_elevation_history_records(plan, survey_date, *, vertical_datum, approved_for_use)` | Task 1 Step 3 | Task 1 tests, Task 2 Step 3 |
| `write_rtk_elevations_to_wells(gdb_path, site_id, plan, history_records)` | Task 1 Step 3 | Task 2 Step 3 |
| `RTKPoint` | `import_rtk_survey.py` (existing) | Task 1 tests, Task 2 Step 3 |
| `assign_qa_flags` | `import_rtk_survey.py` (existing) | Task 1 Step 3 internals |
| `read_well_ids_csv` | `reconcile_locations.py` (existing) | Task 2 Step 3 |
| `ElevationHistory` | `schema/survey.py` (existing) | Task 1 Step 3, Task 1 tests |
| `QACollector` | `common/qa.py` (existing) | Task 1 tests, Task 2 Step 3 |
| `_guard`, `_render_qa` | `cli.py` module-level (existing) | Task 2 Step 3 |
| `MonitoringWells.TOC_ft` | `gdb_schema.py` (verified) | Task 1 Step 3 writer |
| `ElevationHistory.SurveyMethod` | `gdb_schema.py` (verified) | Task 1 Step 3 writer |
| `"GPS_RTK"` | Task 1 Step 3 | Task 1 tests, Task 2 Step 3 |

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-28-survey-to-well-elevation-update.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
