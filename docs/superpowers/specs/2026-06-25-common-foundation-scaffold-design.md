# Common Foundation Scaffold Design

**Date:** 2026-06-25  
**Status:** Approved  
**Unblocks:** Phase 1 foundation, all 18 fast-track tools, Lab EDD Importer, numpy integration

---

## Problem

The established priority tools (Phase 1-4, 18 fast-track items, Lab EDD Importer, Dan Patterson numpy integration) share three foundation pieces that do not yet exist in `autogis/core/common/`:

1. **`run_history.py`** — every tool needs to log its execution; missing = Phase 1 blocker
2. **`schema/`** — ~27 new table definitions (boring, survey, drone, elevation history, dashboard marts) needed before fast-track tools can write or read data
3. **`npg/` + `numpy_geom.py`** — absorbed Dan Patterson numpy geometry code + clean AutoGIS public API

Without these, every downstream tool has to either re-invent the wheel or defer to a future "we'll add logging later" patch cycle.

---

## Approach: Option A — Domain-Split Modules

Add three focused additions to `autogis/core/common/`, matching the existing grain of the codebase (`config.py`, `qa.py`, `units.py` are each standalone single-purpose modules).

### Final Structure

```
autogis/core/common/
  run_history.py          ← new, standalone
  numpy_geom.py           ← new, standalone public API over npg/
  npg/                    ← absorbed from Dan Patterson, modified in place
    __init__.py
    npg_maths.py
    npg_geom_ops.py
    npg_analysis.py
  schema/                 ← new package
    __init__.py           ← re-exports all dataclasses
    envmon.py
    boring.py
    survey.py
    drone.py
    dashboard.py
```

No new sub-packages in `core/common/` beyond `schema/` and `npg/`. No arcpy imports anywhere in this layer.

---

## Section 1: `run_history.py`

### Purpose

Single append-and-query log for every tool execution. Consumed by `EvaluateReportReadiness`, `RunEnvJobQueue`, dashboard data mart tools, and any audit query.

### Data Model

```python
@dataclass
class RunRecord:
    run_id: str           # UUID4, generated at tool start
    tool_name: str        # e.g. "ImportLabEDD"
    site_id: str
    event_id: str | None  # None for non-event tools (schema migration, etc.)
    started_at: datetime
    finished_at: datetime
    status: str           # "success" | "warning" | "error" | "cancelled"
    inputs: dict          # key → value of all tool inputs
    outputs: dict         # key → path/count/URL of all produced outputs
    qa_count_error: int
    qa_count_warning: int
    qa_count_info: int
    message: str          # human-readable one-line summary
```

### `RunHistory` Class

```python
class RunHistory:
    def __init__(self, path: Path): ...

    def write(self, record: RunRecord) -> None:
        """Append one record. Creates file if absent."""

    def query(
        self,
        site_id: str | None = None,
        tool_name: str | None = None,
        since: datetime | None = None,
        status: str | None = None,
    ) -> list[RunRecord]:
        """Filter records. All parameters optional."""

    def latest(self, tool_name: str, site_id: str) -> RunRecord | None:
        """Most recent record for a given tool + site."""
```

### Storage

- Default backend: **CSV** (one row per record, `inputs`/`outputs` JSON-encoded in their columns)
- Path configured in `SiteConfig` under `run_history_path`; falls back to `<project_root>/run_history.csv`
- No arcpy dependency; works in tests without a GDB

### Error Handling

- `write()` is best-effort: logs but does not raise if the file is unwritable (tool should not fail because of logging)
- `query()` raises `RunHistoryError` if file exists but is corrupt/unparseable

---

## Section 2: `schema/` Package

### Purpose

Canonical Python dataclass definitions for every table the fast-track tools read or write. Arcpy-free. The arcpy adapter in `autogis/adapters/` converts these to GDB field specs at materialization time.

### Contract Every Dataclass Satisfies

```python
@dataclass
class SomeRecord:
    table_name: ClassVar[str] = "SomeRecord"  # GDB table name

    def to_row(self) -> dict:
        """Return {field_name: value} dict. Used by arcpy adapter."""
```

### `schema/envmon.py` — Existing Normalized Tables (Formalized)

| Class | Table | Key Fields |
|---|---|---|
| `EnvSample` | `Env_Samples` | site_id, location_id, event_date, matrix, sample_id |
| `EnvAnalyticalResult` | `Env_AnalyticalResults` | sample_id, analyte, result, units, qualifier, reporting_limit |
| `EnvImportQA` | `Env_ImportQA` | run_id, severity, category, message, source_row |
| `EnvWaterLevelEvent` | `Env_CurrentWaterLevelEvent` | site_id, location_id, event_date, dtw_ft, gwe_ft, status, use_for_model |

### `schema/boring.py` — 7-Table Boring Log Schema

| Class | Table | Key Fields |
|---|---|---|
| `BoringLocation` | `BoringLocations` | boring_id, site_id, location_type, northing, easting, ground_elevation, toc_elevation, status |
| `LithologyInterval` | `LithologyIntervals` | boring_id, top_depth, bottom_depth, uscs, primary_material, color, moisture, odor, staining, pid_ppm |
| `BoringSample` | `BoringSamples` | sample_id, boring_id, sample_type, top_depth, bottom_depth, recovery, blow_counts, lab_submitted, matrix, analytical_group |
| `WellConstruction` | `WellConstruction` | boring_id, component_type, top_depth, bottom_depth, diameter, material, slot_size |
| `GroundwaterObservation` | `GroundwaterObservations` | boring_id, observation_datetime, depth_to_water, observation_type, reference_point |
| `BoringPhoto` | `BoringPhotos` | photo_id, boring_id, sample_id, depth, photo_path, caption, taken_by, datetime |
| `BoringComment` | `BoringComments` | comment_id, boring_id, reviewer, comment_text, severity, assigned_to, status, resolution_note, resolved_date |

### `schema/survey.py` — Survey + Elevation Audit Trail

| Class | Table | Key Fields |
|---|---|---|
| `SurveyPointRaw` | `SurveyPoints_Raw` | point_id, northing, easting, elevation, feature_code, hrms, vrms, fix_type, occupation_time, operator |
| `SurveyPointQA` | `SurveyPoints_QA` | point_id, qa_status, qa_flags (list), approved |
| `LevelLoopRun` | `LevelLoopRuns` | run_id, site_id, survey_date, benchmark_id, known_elevation, misclosure_ft, closure_tolerance_ft, adjusted, operator |
| `LevelLoopObservation` | `LevelLoopObservations` | run_id, setup_id, point_id, backsight, foresight, intermediate_sight, hi, elevation |
| `ElevationHistory` | `ElevationHistory` | location_id, elevation_type, elevation, vertical_datum, survey_date, survey_method, source_run_id, approved_for_use, superseded |

### `schema/drone.py` — Flight Registry + Products

| Class | Table | Key Fields |
|---|---|---|
| `DroneFlight` | `DroneFlights` | flight_id, project_id, site_id, flight_date, pilot, drone_model, sensor, altitude, overlap_forward, overlap_side, gcp_used, checkpoint_count, processing_software, output_crs, vertical_datum, qa_status |
| `DroneControlPoint` | `DroneControlPoints` | point_id, flight_id, northing, easting, elevation, point_type (GCP/CP), residual_h, residual_v |
| `DroneCheckpoint` | `DroneCheckpoints` | checkpoint_id, flight_id, northing, easting, elevation, residual_h, residual_v, within_tolerance |
| `DroneProductRecord` | `DroneProductRegistry` | product_id, flight_id, product_type (orthomosaic/DSM/DEM/point_cloud), path, crs, vertical_datum, resolution_m, qa_status |

### `schema/dashboard.py` — 10 Flat Mart Tables

| Class | Table | Purpose |
|---|---|---|
| `DashSiteStatus` | `Dash_SiteStatus` | Per-site rollup (active events, open QA, report due) |
| `DashEventStatus` | `Dash_EventStatus` | Per-event rollup (sampled %, lab received, figures ready) |
| `DashWellStatus` | `Dash_WellStatus` | Per-well current status (sampled, dry, inaccessible, GWE) |
| `DashCurrentExceedances` | `Dash_CurrentExceedances` | Flat list of current exceedances (analyte, result, screening level, location) |
| `DashGWLevelSummary` | `Dash_GWLevelSummary` | Current GWE per well, delta from prior event |
| `DashAnalyticalSummary` | `Dash_AnalyticalSummary` | Latest detected/exceeded results per analyte per location |
| `DashFieldQA` | `Dash_FieldQA` | Field QA flags (missing samples, photo gaps, access issues) |
| `DashLabQA` | `Dash_LabQA` | Lab QA flags (unmatched samples, RPD failures, missing analytes) |
| `DashOpenIssues` | `Dash_OpenIssues` | All open QA/review issues across field, lab, GIS, model |
| `DashReportReadiness` | `Dash_ReportReadiness` | Go/no-go per category (field, lab, GIS, QA, model, report) |

### `schema/__init__.py` — Re-exports

```python
from .envmon import EnvSample, EnvAnalyticalResult, EnvImportQA, EnvWaterLevelEvent
from .boring import (BoringLocation, LithologyInterval, BoringSample, WellConstruction,
                     GroundwaterObservation, BoringPhoto, BoringComment)
from .survey import SurveyPointRaw, SurveyPointQA, LevelLoopRun, LevelLoopObservation, ElevationHistory
from .drone import DroneFlight, DroneControlPoint, DroneCheckpoint, DroneProductRecord
from .dashboard import (DashSiteStatus, DashEventStatus, DashWellStatus, DashCurrentExceedances,
                        DashGWLevelSummary, DashAnalyticalSummary, DashFieldQA, DashLabQA,
                        DashOpenIssues, DashReportReadiness)
```

---

## Section 3: `npg/` + `numpy_geom.py`

### `npg/` — Absorbed Dan Patterson Source

Files pulled from:
- `https://github.com/Dan-Patterson/numpy_geometry`
- `https://github.com/Dan-Patterson/Tools_for_ArcGIS_Pro`

**Attribution header in every `npg/` file:**
```python
# Absorbed from Dan Patterson / numpy_geometry
# Source: https://github.com/Dan-Patterson/numpy_geometry
# Author: Dan Patterson <dan_patterson@carleton.ca>
# License: Free use (confirmed 2026-06-25)
# Modified in place for AutoGIS. See git log for changes.
```

Files:
- `npg/npg_maths.py` — math utilities including `_trans_rot_2()`
- `npg/npg_geom_ops.py` — geometry ops including `simplify()`, `_ch_simple()`, `_densify_2D()`
- `npg/npg_analysis.py` — spatial analysis including `n_near()`

**In-place modification policy:**
- Fix bugs, fill gaps, add missing docstrings, remove dead code freely
- Do not add arcpy imports
- Track significant changes in commit messages referencing Dan Patterson origin

### `numpy_geom.py` — Public AutoGIS API

Five functions, named for their AutoGIS use case:

```python
def rotate_points(xy: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotate (x,y) array by angle_deg. Used by callout placement."""

def convex_hull(xy: np.ndarray) -> np.ndarray:
    """Convex hull of (x,y) points. Used by callout collision detection."""

def nearest_neighbors(
    xy: np.ndarray, k: int = 1
) -> tuple[np.ndarray, np.ndarray]:
    """K nearest neighbors per point. Returns (indices, distances).
    Used by RPD duplicate location matching."""

def simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker simplification. Used by contour generalization."""

def densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray:
    """Add intermediate vertices. Used by contour smoothing."""
```

**Rules:**
- All inputs and outputs are plain `np.ndarray` — no arcpy objects, no GIS dependencies
- No side effects
- Used directly by `OptimizeCalloutPlacement` (Phase 3), `EvaluateDuplicateRPD` (Phase 2), geostatistical contour tools (Phase 4-5)

---

## Data Flow Summary

```
Tool start
    ↓
run_id = uuid4()
RunHistory.write(RunRecord(status="running", ...))
    ↓
Tool reads/writes schema dataclasses
(e.g. ElevationHistory, BoringSample, DashReportReadiness)
    ↓
arcpy adapter materializes to GDB (adapters layer only)
    ↓
numpy_geom functions called for geometry ops (pure numpy)
    ↓
RunHistory.write(RunRecord(status="success"|"error", ...))
```

---

## Testing Strategy

- `run_history.py` — unit tests with `tmp_path` fixture, no GDB needed
- `schema/` — unit tests: instantiate dataclasses, call `to_row()`, assert field types/names
- `numpy_geom.py` / `npg/` — unit tests with synthetic numpy arrays, no arcpy, no GDB
- All tests run with `python -m pytest -q` (existing test runner, no arcpy needed)

---

## Dependencies Added

None. All three modules depend only on:
- Python stdlib (`dataclasses`, `datetime`, `csv`, `json`, `uuid`, `pathlib`)
- `numpy` (already in the project)

No new packages required.

---

## Files to Create

| File | LOC (est.) | Notes |
|---|---|---|
| `autogis/core/common/run_history.py` | ~120 | RunRecord dataclass + RunHistory class |
| `autogis/core/common/schema/__init__.py` | ~20 | Re-exports only |
| `autogis/core/common/schema/envmon.py` | ~80 | 4 dataclasses |
| `autogis/core/common/schema/boring.py` | ~160 | 7 dataclasses |
| `autogis/core/common/schema/survey.py` | ~120 | 5 dataclasses |
| `autogis/core/common/schema/drone.py` | ~100 | 4 dataclasses |
| `autogis/core/common/schema/dashboard.py` | ~120 | 10 dataclasses |
| `autogis/core/common/numpy_geom.py` | ~60 | 5 wrapper functions |
| `autogis/core/common/npg/__init__.py` | ~5 | |
| `autogis/core/common/npg/npg_maths.py` | ~absorbed | From Dan Patterson |
| `autogis/core/common/npg/npg_geom_ops.py` | ~absorbed | From Dan Patterson |
| `autogis/core/common/npg/npg_analysis.py` | ~absorbed | From Dan Patterson |
| `tests/core/common/test_run_history.py` | ~60 | |
| `tests/core/common/test_schema.py` | ~80 | |
| `tests/core/common/test_numpy_geom.py` | ~60 | |

**Total new code (excluding absorbed npg/):** ~1,000 lines

---

## Implementation Order

1. `schema/` modules — pure dataclasses, no dependencies, fastest to write
2. `run_history.py` — depends only on stdlib
3. `npg/` — pull files, add attribution headers, clean up
4. `numpy_geom.py` — thin wrappers, depends on `npg/`
5. Tests for all four

Each step is independently mergeable.
