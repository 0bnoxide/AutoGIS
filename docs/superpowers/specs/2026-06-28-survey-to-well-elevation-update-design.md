# SurveyToWellElevationUpdate Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** SurveyToWellElevationUpdate (Phase 4 / Tool 8.5)
**Priority:** HIGH — closes the survey → water-level calculation chain

---

## Problem

After a level-loop survey produces adjusted elevations (via `ProcessLevelLoop`)
or an RTK survey imports precise coordinates (via `ImportRTKSurveyPoints`), the
canonical well elevation fields in the `Env_Wells` table need to be updated with
the new surveyed values. Currently this is done manually — overwriting a
spreadsheet column with no versioning and no audit trail.

`UpdateWellElevationsFromLevelLoop` (already planned) handles the level-loop path.
This tool handles the **RTK / total-station survey path**: given a validated
`SurveyPoints_QA` CSV, it computes the update delta, writes a history row to
`Env_WellElevationHistory`, and outputs an update script (CSV patch) for import.

---

## Approach

**Chosen:** Headless update-delta generator. Reads `SurveyPoints_QA` CSV
(from `ValidateRTKSurvey`), joins against current `Env_Wells` CSV (or a minimal
flat file), computes the change in `GroundElev_ft`, `TOC_Elev_ft`, and
`TOC_Offset_ft`, flags large changes (> threshold), and writes:
1. A patch CSV (`Env_Wells_update.csv`) with updated rows only
2. An audit row per well to `Env_WellElevationHistory.csv`
3. A QA report

No arcpy at compute time; the LOCAL `.pyt` toolbox applies the patch to the GDB.

**Rejected: Direct GDB writes.** Requires arcpy. Patch CSV approach keeps the
core headless and testable.

---

## Architecture

```
autogis/
  core/envmon/
    survey_well_elevation_update.py   ← NEW
  adapters/
    cli.py                            ← add survey-to-well-elevations command (headless)
tests/envmon/
  test_survey_well_elevation_update.py ← NEW
```

---

## Public API (`survey_well_elevation_update.py`)

```python
@dataclass
class WellElevationDelta:
    location_id: str
    prior_ground_elev: float | None
    new_ground_elev: float | None
    prior_toc_elev: float | None
    new_toc_elev: float | None
    delta_ground_elev: float | None   # new - prior
    delta_toc_elev: float | None
    survey_date: str
    survey_point_id: str
    is_large_change: bool             # |delta| > large_change_threshold
    status: str                       # updated | no_change | no_survey_point | error

@dataclass
class ElevationUpdateResult:
    deltas: list[WellElevationDelta]
    update_count: int
    no_change_count: int
    missing_count: int
    qa: QACollector

def compute_elevation_deltas(
    survey_points: list[dict],    # SurveyPoints_QA rows
    well_rows: list[dict],        # Env_Wells rows
    *,
    large_change_threshold_ft: float = 0.5,
    qa: QACollector | None = None,
) -> ElevationUpdateResult:
    """
    Join survey points to wells by location_id.
    Compute deltas; flag large changes.
    """

def write_well_elevation_patch(
    result: ElevationUpdateResult,
    patch_path: Path,
    history_path: Path,
    survey_batch_id: str = "",
) -> None:
    """
    Write updated rows to patch CSV (only wells with changes).
    Append audit rows to history CSV.
    """
```

---

## Column Mapping (SurveyPoints_QA → Env_Wells)

| Survey column | Well column |
|---|---|
| `location_id` | `LocationID` (join key) |
| `northing_adj` | `Northing` |
| `easting_adj` | `Easting` |
| `ground_elev_ft` | `GroundElev_ft` |
| `toc_elev_ft` | `TOC_Elev_ft` |

`TOC_Offset_ft = TOC_Elev_ft - GroundElev_ft` (recomputed from new values).

---

## Audit History Schema

`Env_WellElevationHistory.csv` columns:
```
history_id, location_id, survey_date, survey_batch_id,
prior_ground_elev, new_ground_elev, delta_ground_elev,
prior_toc_elev, new_toc_elev, delta_toc_elev,
updated_at, updated_by, notes
```

---

## CLI Command

```
autogis envmon survey-to-well-elevations \
  --survey-points <survey_points_qa.csv> \
  --wells <env_wells.csv> \
  --patch-out <env_wells_update.csv> \
  --history-out <env_well_elevation_history.csv> \
  [--large-change-threshold 0.5] \
  [--batch-id <survey_batch_id>] \
  [--report <qa.md>] \
  [--fail-on error|warning]
```

Headless.

---

## Test Strategy

`tests/envmon/test_survey_well_elevation_update.py` — arcpy-free:

1. `compute_elevation_deltas` joins survey point to well by location_id
2. `delta_ground_elev` = new - prior (correct arithmetic)
3. `is_large_change=True` when |delta| > threshold
4. Well with no matching survey point → status=`no_survey_point`, WARNING in QA
5. Well with matching survey but unchanged values → status=`no_change`
6. `write_well_elevation_patch` writes only changed wells to patch CSV
7. History CSV appended with audit row per updated well
8. `TOC_Offset_ft` recomputed from new toc - new ground
