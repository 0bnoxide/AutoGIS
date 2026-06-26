# Common Foundation Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Scaffold `schema/`, `run_history.py`, `npg/`, and `numpy_geom.py` in `autogis/core/common/` — the shared foundation every Phase 1-4 fast-track tool depends on.

**Architecture:** Four independently mergeable tasks in dependency order: schema dataclasses first (no deps), run_history second (stdlib only), npg/ third (absorbed Dan Patterson source), numpy_geom.py fourth (wraps npg/). No arcpy anywhere in this layer.

**Tech Stack:** Python 3.10+, stdlib only (`dataclasses`, `csv`, `json`, `uuid`, `datetime`, `pathlib`), numpy (to be added as dependency).

## Global Constraints

- No `arcpy` or `arcgis` imports anywhere in `autogis/core/common/`
- All tests run with `python -m pytest -q` from project root — no GDB, no ArcGIS Pro
- `from __future__ import annotations` at top of every new module (matches existing codebase style)
- Python 3.10+ minimum (`str | None` union syntax permitted)
- Every dataclass exposes `table_name: ClassVar[str]` and `to_row() -> dict`
- `npg/` files must carry Dan Patterson attribution header (see Task 3)
- numpy must be added to `[dependencies]` in `setup.cfg` before Task 4 tests can run

---

## File Map

**Created:**
- `autogis/core/common/schema/__init__.py`
- `autogis/core/common/schema/envmon.py`
- `autogis/core/common/schema/boring.py`
- `autogis/core/common/schema/survey.py`
- `autogis/core/common/schema/drone.py`
- `autogis/core/common/schema/dashboard.py`
- `autogis/core/common/run_history.py`
- `autogis/core/common/npg/__init__.py`
- `autogis/core/common/npg/npg_maths.py`
- `autogis/core/common/npg/npg_geom_ops.py`
- `autogis/core/common/npg/npg_analysis.py`
- `autogis/core/common/numpy_geom.py`
- `tests/core/__init__.py`
- `tests/core/common/__init__.py`
- `tests/core/common/test_schema.py`
- `tests/core/common/test_run_history.py`
- `tests/core/common/test_numpy_geom.py`

**Modified:**
- `setup.cfg` — add `numpy` to `[project] dependencies`

---

## Task 1: `schema/` Package

**Files:**
- Create: `autogis/core/common/schema/__init__.py`
- Create: `autogis/core/common/schema/envmon.py`
- Create: `autogis/core/common/schema/boring.py`
- Create: `autogis/core/common/schema/survey.py`
- Create: `autogis/core/common/schema/drone.py`
- Create: `autogis/core/common/schema/dashboard.py`
- Create: `tests/core/__init__.py` (empty)
- Create: `tests/core/common/__init__.py` (empty)
- Create: `tests/core/common/test_schema.py`

**Interfaces:**
- Produces: `from autogis.core.common.schema import ElevationHistory, DroneFlight, RunRecord` etc. — consumed by Tasks 2, 4, and all fast-track tools

- [x] **Step 1: Write the failing tests**

```python
# tests/core/common/test_schema.py
from __future__ import annotations
import dataclasses
from datetime import date, datetime

from autogis.core.common.schema import (
    EnvSample, EnvAnalyticalResult, EnvImportQA, EnvWaterLevelEvent,
    BoringLocation, LithologyInterval, BoringSample, WellConstruction,
    GroundwaterObservation, BoringPhoto, BoringComment,
    SurveyPointRaw, SurveyPointQA, LevelLoopRun, LevelLoopObservation,
    ElevationHistory,
    DroneFlight, DroneControlPoint, DroneCheckpoint, DroneProductRecord,
    DashSiteStatus, DashEventStatus, DashWellStatus, DashCurrentExceedances,
    DashGWLevelSummary, DashAnalyticalSummary, DashFieldQA, DashLabQA,
    DashOpenIssues, DashReportReadiness,
)


def test_env_sample_table_name():
    assert EnvSample.table_name == "Env_Samples"


def test_env_sample_to_row_keys():
    s = EnvSample(
        site_id="H281", location_id="MW-1", event_date=date(2026, 6, 1),
        matrix="GW", sample_id="H281-MW1-GW-2026Q2",
    )
    row = s.to_row()
    assert "site_id" in row
    assert "location_id" in row
    assert "event_date" in row
    assert "matrix" in row
    assert "sample_id" in row


def test_env_analytical_result_table_name():
    assert EnvAnalyticalResult.table_name == "Env_AnalyticalResults"


def test_env_import_qa_table_name():
    assert EnvImportQA.table_name == "Env_ImportQA"


def test_env_water_level_event_table_name():
    assert EnvWaterLevelEvent.table_name == "Env_CurrentWaterLevelEvent"


def test_boring_location_table_name():
    assert BoringLocation.table_name == "BoringLocations"


def test_boring_location_to_row_is_dict():
    b = BoringLocation(
        boring_id="B-01", site_id="H281", location_type="boring",
        northing=None, easting=None, ground_elevation=None,
        toc_elevation=None, status="drilled",
    )
    assert isinstance(b.to_row(), dict)


def test_lithology_interval_table_name():
    assert LithologyInterval.table_name == "LithologyIntervals"


def test_boring_sample_table_name():
    assert BoringSample.table_name == "BoringSamples"


def test_well_construction_table_name():
    assert WellConstruction.table_name == "WellConstruction"


def test_groundwater_observation_table_name():
    assert GroundwaterObservation.table_name == "GroundwaterObservations"


def test_boring_photo_table_name():
    assert BoringPhoto.table_name == "BoringPhotos"


def test_boring_comment_table_name():
    assert BoringComment.table_name == "BoringComments"


def test_survey_point_raw_table_name():
    assert SurveyPointRaw.table_name == "SurveyPoints_Raw"


def test_survey_point_qa_table_name():
    assert SurveyPointQA.table_name == "SurveyPoints_QA"


def test_level_loop_run_table_name():
    assert LevelLoopRun.table_name == "LevelLoopRuns"


def test_level_loop_observation_table_name():
    assert LevelLoopObservation.table_name == "LevelLoopObservations"


def test_elevation_history_table_name():
    assert ElevationHistory.table_name == "ElevationHistory"


def test_elevation_history_to_row():
    e = ElevationHistory(
        location_id="MW-1", elevation_type="TOC", elevation=4812.5,
        vertical_datum="NAVD88", survey_date=date(2026, 6, 1),
        survey_method="level_loop", source_run_id="abc123",
        approved_for_use=True, superseded=False,
    )
    row = e.to_row()
    assert row["approved_for_use"] is True
    assert row["superseded"] is False


def test_drone_flight_table_name():
    assert DroneFlight.table_name == "DroneFlights"


def test_drone_control_point_table_name():
    assert DroneControlPoint.table_name == "DroneControlPoints"


def test_drone_checkpoint_table_name():
    assert DroneCheckpoint.table_name == "DroneCheckpoints"


def test_drone_product_record_table_name():
    assert DroneProductRecord.table_name == "DroneProductRegistry"


def test_all_dash_table_names():
    assert DashSiteStatus.table_name == "Dash_SiteStatus"
    assert DashEventStatus.table_name == "Dash_EventStatus"
    assert DashWellStatus.table_name == "Dash_WellStatus"
    assert DashCurrentExceedances.table_name == "Dash_CurrentExceedances"
    assert DashGWLevelSummary.table_name == "Dash_GWLevelSummary"
    assert DashAnalyticalSummary.table_name == "Dash_AnalyticalSummary"
    assert DashFieldQA.table_name == "Dash_FieldQA"
    assert DashLabQA.table_name == "Dash_LabQA"
    assert DashOpenIssues.table_name == "Dash_OpenIssues"
    assert DashReportReadiness.table_name == "Dash_ReportReadiness"


def test_to_row_returns_all_fields():
    """to_row() must include every field — no silent omissions."""
    e = ElevationHistory(
        location_id="MW-1", elevation_type="TOC", elevation=4812.5,
        vertical_datum="NAVD88", survey_date=date(2026, 6, 1),
        survey_method="level_loop", source_run_id="abc123",
        approved_for_use=True, superseded=False,
    )
    expected_keys = {f.name for f in dataclasses.fields(e)}
    assert set(e.to_row().keys()) == expected_keys
```

- [x] **Step 2: Create empty `__init__.py` files and run tests to confirm they fail**

```bash
mkdir -p autogis/core/common/schema
mkdir -p tests/core/common
touch autogis/core/common/schema/__init__.py
touch tests/core/__init__.py
touch tests/core/common/__init__.py
```

Run: `python -m pytest tests/core/common/test_schema.py -q`  
Expected: `ImportError` or `ModuleNotFoundError`

- [x] **Step 3: Implement `schema/envmon.py`**

```python
# autogis/core/common/schema/envmon.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class EnvSample:
    table_name: ClassVar[str] = "Env_Samples"
    site_id: str
    location_id: str
    event_date: date
    matrix: str
    sample_id: str
    depth_top_ft: Optional[float] = None
    depth_bot_ft: Optional[float] = None
    sampled_by: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvAnalyticalResult:
    table_name: ClassVar[str] = "Env_AnalyticalResults"
    sample_id: str
    analyte: str
    result: Optional[float]
    units: str
    qualifier: str = ""
    reporting_limit: Optional[float] = None
    method: str = ""
    lab: str = ""
    is_nondetect: bool = False
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvImportQA:
    table_name: ClassVar[str] = "Env_ImportQA"
    run_id: str
    severity: str
    category: str
    message: str
    site_id: str = ""
    location_id: str = ""
    sample_id: str = ""
    source_row: Optional[int] = None
    source_sheet: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class EnvWaterLevelEvent:
    table_name: ClassVar[str] = "Env_CurrentWaterLevelEvent"
    site_id: str
    location_id: str
    event_date: date
    dtw_ft: Optional[float]
    gwe_ft: Optional[float]
    status: str          # "measured" | "dry" | "NM" | "NS" | "inaccessible"
    use_for_model: bool = True
    exclusion_reason: str = ""
    measured_by: str = ""
    import_batch_id: str = ""

    def to_row(self) -> dict:
        return asdict(self)
```

- [x] **Step 4: Implement `schema/boring.py`**

```python
# autogis/core/common/schema/boring.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import ClassVar, Optional


@dataclass
class BoringLocation:
    table_name: ClassVar[str] = "BoringLocations"
    boring_id: str
    site_id: str
    location_type: str   # boring | monitoring_well | piezometer | test_pit | hand_auger
    northing: Optional[float]
    easting: Optional[float]
    ground_elevation: Optional[float]
    toc_elevation: Optional[float]
    status: str          # proposed | drilled | surveyed | logged | reviewed | finalized
    coordinate_system: str = ""
    vertical_datum: str = ""
    drilling_start_date: Optional[date] = None
    drilling_end_date: Optional[date] = None
    driller: str = ""
    logged_by: str = ""
    total_depth_ft: Optional[float] = None
    completion_type: str = ""  # backfilled | monitoring_well | abandoned | piezometer

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class LithologyInterval:
    table_name: ClassVar[str] = "LithologyIntervals"
    boring_id: str
    top_depth: float
    bottom_depth: float
    uscs: str = ""
    primary_material: str = ""
    secondary_material: str = ""
    color: str = ""
    moisture: str = ""
    density_consistency: str = ""
    plasticity: str = ""
    odor: str = ""
    staining: str = ""
    pid_ppm: Optional[float] = None
    description: str = ""
    graphic_pattern: str = ""
    reviewed: bool = False

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringSample:
    table_name: ClassVar[str] = "BoringSamples"
    sample_id: str
    boring_id: str
    sample_type: str     # grab | split_spoon | shelby | rock_core | soil_analytical | duplicate
    top_depth: float
    bottom_depth: float
    recovery: Optional[float] = None
    blow_counts: Optional[str] = None
    lab_submitted: bool = False
    matrix: str = ""
    analytical_group: str = ""
    photo_id: str = ""
    coc_number: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class WellConstruction:
    table_name: ClassVar[str] = "WellConstruction"
    boring_id: str
    component_type: str  # casing | screen | sand_pack | bentonite | grout | cap | surface_seal
    top_depth: float
    bottom_depth: float
    diameter: Optional[float] = None
    material: str = ""
    slot_size: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class GroundwaterObservation:
    table_name: ClassVar[str] = "GroundwaterObservations"
    boring_id: str
    observation_datetime: Optional[datetime]
    depth_to_water: Optional[float]
    observation_type: str = ""  # during_drilling | after_drilling | stabilized | not_encountered
    reference_point: str = ""   # ground_surface | TOC | casing
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringPhoto:
    table_name: ClassVar[str] = "BoringPhotos"
    photo_id: str
    boring_id: str
    sample_id: str = ""
    depth: Optional[float] = None
    photo_path: str = ""
    caption: str = ""
    taken_by: str = ""
    datetime: Optional[datetime] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class BoringComment:
    table_name: ClassVar[str] = "BoringComments"
    comment_id: str
    boring_id: str
    reviewer: str = ""
    comment_text: str = ""
    severity: str = ""           # info | warning | error
    assigned_to: str = ""
    status: str = "open"         # open | resolved | deferred
    resolution_note: str = ""
    resolved_date: Optional[date] = None

    def to_row(self) -> dict:
        return asdict(self)
```

- [x] **Step 5: Implement `schema/survey.py`**

```python
# autogis/core/common/schema/survey.py
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import ClassVar, Optional


@dataclass
class SurveyPointRaw:
    table_name: ClassVar[str] = "SurveyPoints_Raw"
    point_id: str
    northing: Optional[float]
    easting: Optional[float]
    elevation: Optional[float]
    feature_code: str = ""
    description: str = ""
    hrms: Optional[float] = None   # horizontal RMS precision (ft or m)
    vrms: Optional[float] = None   # vertical RMS precision
    fix_type: str = ""             # fixed | float | autonomous
    correction_source: str = ""
    occupation_time_s: Optional[float] = None
    rod_height: Optional[float] = None
    collected_at: Optional[str] = None   # ISO datetime string
    operator: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class SurveyPointQA:
    table_name: ClassVar[str] = "SurveyPoints_QA"
    point_id: str
    qa_status: str               # pass | warning | error
    qa_flags: list = field(default_factory=list)  # stored as JSON string in GDB
    approved: bool = False

    def to_row(self) -> dict:
        import json
        d = asdict(self)
        d["qa_flags"] = json.dumps(d["qa_flags"])
        return d


@dataclass
class LevelLoopRun:
    table_name: ClassVar[str] = "LevelLoopRuns"
    run_id: str
    site_id: str
    survey_date: date
    benchmark_id: str
    known_elevation: float
    misclosure_ft: Optional[float] = None
    closure_tolerance_ft: Optional[float] = None
    adjusted: bool = False
    operator: str = ""
    notes: str = ""

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class LevelLoopObservation:
    table_name: ClassVar[str] = "LevelLoopObservations"
    run_id: str
    setup_id: str
    point_id: str
    backsight: Optional[float] = None
    foresight: Optional[float] = None
    intermediate_sight: Optional[float] = None
    hi: Optional[float] = None       # height of instrument
    elevation: Optional[float] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class ElevationHistory:
    table_name: ClassVar[str] = "ElevationHistory"
    location_id: str
    elevation_type: str      # TOC | ground | casing_mark | benchmark
    elevation: float
    vertical_datum: str
    survey_date: date
    survey_method: str       # RTK | level_loop | total_station | assumed
    source_run_id: str
    approved_for_use: bool
    superseded: bool

    def to_row(self) -> dict:
        return asdict(self)
```

- [x] **Step 6: Implement `schema/drone.py`**

```python
# autogis/core/common/schema/drone.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class DroneFlight:
    table_name: ClassVar[str] = "DroneFlights"
    flight_id: str
    project_id: str
    site_id: str
    flight_date: date
    pilot: str = ""
    drone_model: str = ""
    sensor: str = ""
    flight_altitude_m: Optional[float] = None
    overlap_forward_pct: Optional[float] = None
    overlap_side_pct: Optional[float] = None
    gcp_used: bool = False
    checkpoint_count: int = 0
    processing_software: str = ""
    output_crs: str = ""
    vertical_datum: str = ""
    orthomosaic_path: str = ""
    dsm_path: str = ""
    dem_path: str = ""
    point_cloud_path: str = ""
    qa_status: str = "pending"   # pending | pass | fail

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneControlPoint:
    table_name: ClassVar[str] = "DroneControlPoints"
    point_id: str
    flight_id: str
    northing: float
    easting: float
    elevation: float
    point_type: str              # GCP | CP (ground control vs. checkpoint)
    residual_h: Optional[float] = None
    residual_v: Optional[float] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneCheckpoint:
    table_name: ClassVar[str] = "DroneCheckpoints"
    checkpoint_id: str
    flight_id: str
    northing: float
    easting: float
    elevation: float
    residual_h: Optional[float] = None
    residual_v: Optional[float] = None
    within_tolerance: Optional[bool] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DroneProductRecord:
    table_name: ClassVar[str] = "DroneProductRegistry"
    product_id: str
    flight_id: str
    product_type: str    # orthomosaic | DSM | DEM | point_cloud
    path: str
    crs: str = ""
    vertical_datum: str = ""
    resolution_m: Optional[float] = None
    qa_status: str = "pending"   # pending | pass | fail

    def to_row(self) -> dict:
        return asdict(self)
```

- [x] **Step 7: Implement `schema/dashboard.py`**

```python
# autogis/core/common/schema/dashboard.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import ClassVar, Optional


@dataclass
class DashSiteStatus:
    table_name: ClassVar[str] = "Dash_SiteStatus"
    site_id: str
    site_name: str = ""
    active_events: int = 0
    open_qa_issues: int = 0
    report_due_date: Optional[date] = None
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashEventStatus:
    table_name: ClassVar[str] = "Dash_EventStatus"
    site_id: str
    event_id: str
    wells_planned: int = 0
    wells_sampled: int = 0
    lab_received: bool = False
    figures_ready: bool = False
    report_ready: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashWellStatus:
    table_name: ClassVar[str] = "Dash_WellStatus"
    site_id: str
    event_id: str
    location_id: str
    status: str = ""         # sampled | dry | inaccessible | not_sampled
    gwe_ft: Optional[float] = None
    gwe_delta_ft: Optional[float] = None
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashCurrentExceedances:
    table_name: ClassVar[str] = "Dash_CurrentExceedances"
    site_id: str
    event_id: str
    location_id: str
    analyte: str
    result: Optional[float] = None
    units: str = ""
    screening_level: Optional[float] = None
    screening_source: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashGWLevelSummary:
    table_name: ClassVar[str] = "Dash_GWLevelSummary"
    site_id: str
    event_id: str
    location_id: str
    gwe_ft: Optional[float] = None
    prior_gwe_ft: Optional[float] = None
    delta_ft: Optional[float] = None
    trend: str = ""   # rising | falling | stable
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashAnalyticalSummary:
    table_name: ClassVar[str] = "Dash_AnalyticalSummary"
    site_id: str
    event_id: str
    location_id: str
    analyte: str
    result: Optional[float] = None
    units: str = ""
    is_detection: bool = False
    is_exceedance: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashFieldQA:
    table_name: ClassVar[str] = "Dash_FieldQA"
    site_id: str
    event_id: str
    issue_type: str = ""   # missing_sample | photo_gap | access_issue
    location_id: str = ""
    description: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashLabQA:
    table_name: ClassVar[str] = "Dash_LabQA"
    site_id: str
    event_id: str
    issue_type: str = ""   # unmatched_sample | rpd_failure | missing_analyte
    location_id: str = ""
    analyte: str = ""
    description: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashOpenIssues:
    table_name: ClassVar[str] = "Dash_OpenIssues"
    site_id: str
    event_id: str
    domain: str = ""       # field | lab | gis | model | report
    severity: str = ""     # info | warning | error
    description: str = ""
    assigned_to: str = ""
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)


@dataclass
class DashReportReadiness:
    table_name: ClassVar[str] = "Dash_ReportReadiness"
    site_id: str
    event_id: str
    field_ready: bool = False
    lab_ready: bool = False
    gis_ready: bool = False
    qa_ready: bool = False
    model_ready: bool = False
    report_ready: bool = False
    overall_ready: bool = False
    last_updated: Optional[str] = None

    def to_row(self) -> dict:
        return asdict(self)
```

- [x] **Step 8: Implement `schema/__init__.py`**

```python
# autogis/core/common/schema/__init__.py
from .envmon import EnvSample, EnvAnalyticalResult, EnvImportQA, EnvWaterLevelEvent
from .boring import (
    BoringLocation, LithologyInterval, BoringSample, WellConstruction,
    GroundwaterObservation, BoringPhoto, BoringComment,
)
from .survey import (
    SurveyPointRaw, SurveyPointQA, LevelLoopRun, LevelLoopObservation,
    ElevationHistory,
)
from .drone import DroneFlight, DroneControlPoint, DroneCheckpoint, DroneProductRecord
from .dashboard import (
    DashSiteStatus, DashEventStatus, DashWellStatus, DashCurrentExceedances,
    DashGWLevelSummary, DashAnalyticalSummary, DashFieldQA, DashLabQA,
    DashOpenIssues, DashReportReadiness,
)

__all__ = [
    "EnvSample", "EnvAnalyticalResult", "EnvImportQA", "EnvWaterLevelEvent",
    "BoringLocation", "LithologyInterval", "BoringSample", "WellConstruction",
    "GroundwaterObservation", "BoringPhoto", "BoringComment",
    "SurveyPointRaw", "SurveyPointQA", "LevelLoopRun", "LevelLoopObservation",
    "ElevationHistory",
    "DroneFlight", "DroneControlPoint", "DroneCheckpoint", "DroneProductRecord",
    "DashSiteStatus", "DashEventStatus", "DashWellStatus", "DashCurrentExceedances",
    "DashGWLevelSummary", "DashAnalyticalSummary", "DashFieldQA", "DashLabQA",
    "DashOpenIssues", "DashReportReadiness",
]
```

- [x] **Step 9: Run tests and confirm they pass**

Run: `python -m pytest tests/core/common/test_schema.py -q`  
Expected: All tests pass, 0 errors

- [x] **Step 10: Commit**

```bash
git add autogis/core/common/schema/ tests/core/ tests/core/common/
git commit -m "feat(schema): add domain-split dataclass schema package (27 tables)"
```

---

## Task 2: `run_history.py`

**Files:**
- Create: `autogis/core/common/run_history.py`
- Create: `tests/core/common/test_run_history.py`

**Interfaces:**
- Consumes: nothing from Task 1 (stdlib only)
- Produces:
  - `RunRecord` dataclass
  - `RunHistory(path: Path)` with `.write(record)`, `.query(...)`, `.latest(...)`
  - `RunHistoryError(Exception)`

- [x] **Step 1: Write the failing tests**

```python
# tests/core/common/test_run_history.py
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from autogis.core.common.run_history import RunHistory, RunRecord, RunHistoryError


def _record(**overrides) -> RunRecord:
    defaults = dict(
        run_id=str(uuid.uuid4()),
        tool_name="TestTool",
        site_id="H281",
        event_id="2026-Q2",
        started_at=datetime(2026, 6, 25, 9, 0, 0),
        finished_at=datetime(2026, 6, 25, 9, 0, 5),
        status="success",
        inputs={"workbook": "test.xlsx"},
        outputs={"rows": 42},
        qa_count_error=0,
        qa_count_warning=1,
        qa_count_info=3,
        message="Imported 42 rows, 1 warning.",
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


def test_write_creates_file(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record())
    assert (tmp_path / "run_history.csv").exists()


def test_write_then_query_all(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(site_id="H281"))
    h.write(_record(site_id="ZT42"))
    results = h.query()
    assert len(results) == 2


def test_query_filter_by_site(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(site_id="H281"))
    h.write(_record(site_id="ZT42"))
    results = h.query(site_id="H281")
    assert len(results) == 1
    assert results[0].site_id == "H281"


def test_query_filter_by_tool(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(tool_name="ImportLabEDD"))
    h.write(_record(tool_name="ValidateRTKSurvey"))
    results = h.query(tool_name="ImportLabEDD")
    assert len(results) == 1
    assert results[0].tool_name == "ImportLabEDD"


def test_query_filter_by_status(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(status="success"))
    h.write(_record(status="error"))
    results = h.query(status="error")
    assert len(results) == 1
    assert results[0].status == "error"


def test_query_filter_by_since(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    old = datetime(2026, 1, 1, 0, 0, 0)
    new = datetime(2026, 6, 1, 0, 0, 0)
    h.write(_record(finished_at=old))
    h.write(_record(finished_at=new))
    results = h.query(since=datetime(2026, 3, 1))
    assert len(results) == 1
    assert results[0].finished_at == new


def test_latest_returns_most_recent(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(tool_name="ImportLabEDD", site_id="H281",
                    finished_at=datetime(2026, 6, 1)))
    h.write(_record(tool_name="ImportLabEDD", site_id="H281",
                    finished_at=datetime(2026, 6, 25)))
    rec = h.latest("ImportLabEDD", "H281")
    assert rec is not None
    assert rec.finished_at == datetime(2026, 6, 25)


def test_latest_returns_none_when_no_match(tmp_path):
    h = RunHistory(tmp_path / "run_history.csv")
    assert h.latest("NoSuchTool", "H281") is None


def test_write_is_best_effort_on_readonly_dir(tmp_path):
    """write() must not raise even if disk write fails."""
    h = RunHistory(Path("/nonexistent/path/run_history.csv"))
    h.write(_record())   # must not raise


def test_inputs_outputs_roundtrip(tmp_path):
    """inputs/outputs dicts must survive write→query roundtrip."""
    inputs = {"workbook": "data.xlsx", "site_id": "H281"}
    outputs = {"rows_imported": 99, "qa_path": "/tmp/qa.csv"}
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(inputs=inputs, outputs=outputs))
    rec = h.query()[0]
    assert rec.inputs == inputs
    assert rec.outputs == outputs


def test_event_id_none_roundtrip(tmp_path):
    """event_id=None must survive write→query roundtrip."""
    h = RunHistory(tmp_path / "run_history.csv")
    h.write(_record(event_id=None))
    rec = h.query()[0]
    assert rec.event_id is None


def test_corrupt_file_raises_run_history_error(tmp_path):
    p = tmp_path / "run_history.csv"
    p.write_text("not,a,valid,csv,file\n{{{broken", encoding="utf-8")
    h = RunHistory(p)
    with pytest.raises(RunHistoryError):
        h.query()
```

- [x] **Step 2: Run tests to confirm they fail**

Run: `python -m pytest tests/core/common/test_run_history.py -q`  
Expected: `ImportError: cannot import name 'RunHistory'`

- [x] **Step 3: Implement `run_history.py`**

```python
# autogis/core/common/run_history.py
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%S"
_NONE_SENTINEL = "__None__"


class RunHistoryError(Exception):
    pass


@dataclass
class RunRecord:
    run_id: str
    tool_name: str
    site_id: str
    event_id: Optional[str]
    started_at: datetime
    finished_at: datetime
    status: str          # "success" | "warning" | "error" | "cancelled"
    inputs: dict
    outputs: dict
    qa_count_error: int
    qa_count_warning: int
    qa_count_info: int
    message: str


_FIELDS = [
    "run_id", "tool_name", "site_id", "event_id",
    "started_at", "finished_at", "status",
    "inputs", "outputs",
    "qa_count_error", "qa_count_warning", "qa_count_info",
    "message",
]


def _encode(record: RunRecord) -> dict:
    return {
        "run_id": record.run_id,
        "tool_name": record.tool_name,
        "site_id": record.site_id,
        "event_id": _NONE_SENTINEL if record.event_id is None else record.event_id,
        "started_at": record.started_at.strftime(_DATETIME_FMT),
        "finished_at": record.finished_at.strftime(_DATETIME_FMT),
        "status": record.status,
        "inputs": json.dumps(record.inputs),
        "outputs": json.dumps(record.outputs),
        "qa_count_error": record.qa_count_error,
        "qa_count_warning": record.qa_count_warning,
        "qa_count_info": record.qa_count_info,
        "message": record.message,
    }


def _decode(row: dict) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        tool_name=row["tool_name"],
        site_id=row["site_id"],
        event_id=None if row["event_id"] == _NONE_SENTINEL else row["event_id"],
        started_at=datetime.strptime(row["started_at"], _DATETIME_FMT),
        finished_at=datetime.strptime(row["finished_at"], _DATETIME_FMT),
        status=row["status"],
        inputs=json.loads(row["inputs"]),
        outputs=json.loads(row["outputs"]),
        qa_count_error=int(row["qa_count_error"]),
        qa_count_warning=int(row["qa_count_warning"]),
        qa_count_info=int(row["qa_count_info"]),
        message=row["message"],
    )


class RunHistory:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def write(self, record: RunRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            exists = self._path.exists()
            with self._path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_FIELDS)
                if not exists:
                    writer.writeheader()
                writer.writerow(_encode(record))
        except Exception as exc:
            log.warning("RunHistory.write failed (best-effort): %s", exc)

    def _load(self) -> list[RunRecord]:
        if not self._path.exists():
            return []
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                return [_decode(row) for row in csv.DictReader(fh)]
        except Exception as exc:
            raise RunHistoryError(f"Cannot read run history at {self._path}: {exc}") from exc

    def query(
        self,
        site_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        since: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> list[RunRecord]:
        records = self._load()
        if site_id is not None:
            records = [r for r in records if r.site_id == site_id]
        if tool_name is not None:
            records = [r for r in records if r.tool_name == tool_name]
        if since is not None:
            records = [r for r in records if r.finished_at >= since]
        if status is not None:
            records = [r for r in records if r.status == status]
        return records

    def latest(self, tool_name: str, site_id: str) -> Optional[RunRecord]:
        matches = self.query(tool_name=tool_name, site_id=site_id)
        if not matches:
            return None
        return max(matches, key=lambda r: r.finished_at)
```

- [x] **Step 4: Run tests and confirm they pass**

Run: `python -m pytest tests/core/common/test_run_history.py -q`  
Expected: All tests pass

- [x] **Step 5: Commit**

```bash
git add autogis/core/common/run_history.py tests/core/common/test_run_history.py
git commit -m "feat(run_history): RunRecord + RunHistory CSV append/query (Phase 1 blocker)"
```

---

## Task 3: `npg/` — Absorb Dan Patterson Source

**Files:**
- Create: `autogis/core/common/npg/__init__.py`
- Create: `autogis/core/common/npg/npg_maths.py`
- Create: `autogis/core/common/npg/npg_geom_ops.py`
- Create: `autogis/core/common/npg/npg_analysis.py`
- Modify: `setup.cfg` — add numpy dependency

**Interfaces:**
- Produces: `npg.npg_maths`, `npg.npg_geom_ops`, `npg.npg_analysis` — imported by Task 4

- [x] **Step 1: Add numpy to `setup.cfg`**

Open `setup.cfg`. Change:
```toml
dependencies = ["PyYAML", "click", "openpyxl"]
```
to:
```toml
dependencies = ["PyYAML", "click", "openpyxl", "numpy>=1.24"]
```

- [x] **Step 2: Install numpy**

```bash
pip install numpy>=1.24
```

Verify: `python -c "import numpy; print(numpy.__version__)"` — should print a version number.

- [x] **Step 3: Clone Dan Patterson's repos and identify source files**

```bash
git clone https://github.com/Dan-Patterson/numpy_geometry.git /tmp/numpy_geometry
git clone https://github.com/Dan-Patterson/Tools_for_ArcGIS_Pro.git /tmp/Tools_for_ArcGIS_Pro
```

Locate these files:
- `/tmp/numpy_geometry/arcpro_npg/npg/npg_maths.py` (contains `_trans_rot_2`)
- `/tmp/numpy_geometry/arcpro_npg/npg/npg_geom_ops.py` (contains `simplify`, `_ch_simple`, `_densify_2D`)
- `/tmp/numpy_geometry/arcpro_npg/npg/npg_analysis.py` (contains `n_near`)

Note: Dan's directory layout varies by commit — adapt path if needed. Run `find /tmp/numpy_geometry -name "npg_maths.py"` to locate.

- [x] **Step 4: Create `npg/` directory and copy files**

```bash
mkdir -p autogis/core/common/npg
cp /tmp/numpy_geometry/arcpro_npg/npg/npg_maths.py autogis/core/common/npg/
cp /tmp/numpy_geometry/arcpro_npg/npg/npg_geom_ops.py autogis/core/common/npg/
cp /tmp/numpy_geometry/arcpro_npg/npg/npg_analysis.py autogis/core/common/npg/
```

- [x] **Step 5: Create `npg/__init__.py`**

```python
# autogis/core/common/npg/__init__.py
# Dan Patterson numpy geometry utilities — absorbed and modified in place.
# See individual module files for attribution and modification notes.
```

- [x] **Step 6: Add attribution header to each npg/ file**

Prepend to the top of each of the three files (before existing content):

```python
# Absorbed from Dan Patterson / numpy_geometry
# Source: https://github.com/Dan-Patterson/numpy_geometry
# Author: Dan Patterson <dan_patterson@carleton.ca>
# License: Free use (confirmed 2026-06-25)
# Modified in place for AutoGIS. See git log for changes.
#
```

- [x] **Step 7: Remove arcpy imports from all three files**

Search each file for `import arcpy` or `from arcpy` lines and remove them. Also remove any function calls or lines that use `arcpy.*` — these are the output/IO wrappers, not the numpy computation cores.

For each file run:
```bash
grep -n "arcpy" autogis/core/common/npg/npg_maths.py
grep -n "arcpy" autogis/core/common/npg/npg_geom_ops.py
grep -n "arcpy" autogis/core/common/npg/npg_analysis.py
```

Remove or comment out each hit. If a function body is entirely arcpy-dependent (e.g., returns `arcpy.Polygon`), comment out the whole function body and add: `# EXCLUDED: requires arcpy — use numpy_geom wrapper instead`

- [x] **Step 8: Verify the five key functions are importable**

```bash
python -c "
from autogis.core.common.npg import npg_maths, npg_geom_ops, npg_analysis
print('_trans_rot_2:', hasattr(npg_maths, '_trans_rot_2'))
print('_ch_simple:', hasattr(npg_geom_ops, '_ch_simple'))
print('simplify:', hasattr(npg_geom_ops, 'simplify'))
print('_densify_2D:', hasattr(npg_geom_ops, '_densify_2D'))
print('n_near:', hasattr(npg_analysis, 'n_near'))
"
```

Expected output:
```
_trans_rot_2: True
_ch_simple: True
simplify: True
_densify_2D: True
n_near: True
```

If any function is missing or incomplete in Dan's source (he notes functionality varies by how bored he was), implement it directly in the npg/ file — see the fallback implementations in Task 4 Step 3 for reference.

- [x] **Step 9: Commit**

```bash
git add autogis/core/common/npg/ setup.cfg
git commit -m "feat(npg): absorb Dan Patterson numpy_geometry — attribution, arcpy stripped"
```

---

## Task 4: `numpy_geom.py` — Public AutoGIS API

**Files:**
- Create: `autogis/core/common/numpy_geom.py`
- Create: `tests/core/common/test_numpy_geom.py`

**Interfaces:**
- Consumes: `autogis.core.common.npg.npg_maths._trans_rot_2`, `npg_geom_ops._ch_simple`, `npg_geom_ops.simplify`, `npg_geom_ops._densify_2D`, `npg_analysis.n_near`
- Produces:
  - `rotate_points(xy: np.ndarray, angle_deg: float) -> np.ndarray`
  - `convex_hull(xy: np.ndarray) -> np.ndarray`
  - `nearest_neighbors(xy: np.ndarray, k: int = 1) -> tuple[np.ndarray, np.ndarray]`
  - `simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray`
  - `densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray`

- [x] **Step 1: Write the failing tests**

```python
# tests/core/common/test_numpy_geom.py
from __future__ import annotations
import numpy as np
import pytest
from autogis.core.common.numpy_geom import (
    rotate_points, convex_hull, nearest_neighbors,
    simplify_polyline, densify_polyline,
)


def test_rotate_points_90_degrees():
    """Rotating (1,0) by 90° should give (0,1)."""
    xy = np.array([[1.0, 0.0]])
    result = rotate_points(xy, 90.0)
    assert result.shape == (1, 2)
    assert abs(result[0, 0]) < 1e-10   # x → ~0
    assert abs(result[0, 1] - 1.0) < 1e-10   # y → ~1


def test_rotate_points_0_degrees_unchanged():
    xy = np.array([[3.0, 4.0], [1.0, 2.0]])
    result = rotate_points(xy, 0.0)
    np.testing.assert_allclose(result, xy, atol=1e-10)


def test_rotate_points_360_degrees_unchanged():
    xy = np.array([[3.0, 4.0]])
    result = rotate_points(xy, 360.0)
    np.testing.assert_allclose(result, xy, atol=1e-10)


def test_convex_hull_returns_array():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                   [0.0, 1.0], [0.5, 0.5]])  # 5 pts, one interior
    hull = convex_hull(xy)
    assert isinstance(hull, np.ndarray)
    assert hull.shape[1] == 2


def test_convex_hull_interior_point_excluded():
    """The interior point (0.5, 0.5) must not appear in the hull."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                   [0.0, 1.0], [0.5, 0.5]])
    hull = convex_hull(xy)
    # hull should have 4 vertices (the square corners), not 5
    assert len(hull) <= 4


def test_nearest_neighbors_returns_indices_and_distances():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=1)
    assert idx.shape == (3, 1)
    assert dists.shape == (3, 1)


def test_nearest_neighbors_correct_match():
    """Point 0 (0,0) is closest to Point 1 (1,0), not Point 2 (10,0)."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=1)
    assert idx[0, 0] == 1   # point 0's nearest is point 1
    assert abs(dists[0, 0] - 1.0) < 1e-10


def test_nearest_neighbors_k2():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [10.0, 0.0]])
    idx, dists = nearest_neighbors(xy, k=2)
    assert idx.shape == (4, 2)


def test_simplify_polyline_reduces_vertices():
    """A straight line with midpoints should simplify to just endpoints."""
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0],
                   [3.0, 0.0], [4.0, 0.0]])  # all collinear
    result = simplify_polyline(xy, tolerance=0.01)
    assert len(result) <= 2   # just the two endpoints needed


def test_simplify_polyline_preserves_endpoints():
    xy = np.array([[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]])
    result = simplify_polyline(xy, tolerance=0.01)
    np.testing.assert_allclose(result[0], xy[0])
    np.testing.assert_allclose(result[-1], xy[-1])


def test_simplify_polyline_zero_tolerance_keeps_all():
    xy = np.array([[0.0, 0.0], [1.0, 0.5], [2.0, 0.0]])
    result = simplify_polyline(xy, tolerance=0.0)
    assert len(result) == len(xy)


def test_densify_polyline_increases_vertices():
    xy = np.array([[0.0, 0.0], [2.0, 0.0]])  # one segment
    result = densify_polyline(xy, factor=2)
    assert len(result) > len(xy)


def test_densify_polyline_preserves_endpoints():
    xy = np.array([[0.0, 0.0], [4.0, 0.0]])
    result = densify_polyline(xy, factor=4)
    np.testing.assert_allclose(result[0], xy[0])
    np.testing.assert_allclose(result[-1], xy[-1])


def test_densify_polyline_midpoint_correct():
    """Densify [[0,0],[2,0]] by factor 2 should include [1,0]."""
    xy = np.array([[0.0, 0.0], [2.0, 0.0]])
    result = densify_polyline(xy, factor=2)
    midpoints = result[1:-1]
    assert any(abs(p[0] - 1.0) < 1e-10 and abs(p[1]) < 1e-10
               for p in midpoints)
```

- [x] **Step 2: Run tests to confirm they fail**

Run: `python -m pytest tests/core/common/test_numpy_geom.py -q`  
Expected: `ImportError: cannot import name 'rotate_points'`

- [x] **Step 3: Implement `numpy_geom.py`**

Try importing from `npg/` first; fall back to inline pure-numpy implementations for anything missing or incomplete.

```python
# autogis/core/common/numpy_geom.py
"""AutoGIS public API over Dan Patterson's numpy geometry utilities (npg/).

All functions accept and return plain numpy arrays. No arcpy, no GIS objects,
no side effects. Safe to import without an ArcGIS Pro license.

Attribution: Dan Patterson <dan_patterson@carleton.ca>
Source: https://github.com/Dan-Patterson/numpy_geometry
License: Free use (confirmed 2026-06-25)
"""
from __future__ import annotations
import numpy as np


# ---------------------------------------------------------------------------
# rotate_points
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_maths import _trans_rot_2 as _rot

    def rotate_points(xy: np.ndarray, angle_deg: float) -> np.ndarray:
        """Rotate (x,y) points by angle_deg. Used by callout placement."""
        return _rot(xy, angle_deg)

except (ImportError, AttributeError):
    def rotate_points(xy: np.ndarray, angle_deg: float) -> np.ndarray:
        """Rotate (x,y) points by angle_deg (pure numpy fallback)."""
        theta = np.radians(angle_deg)
        c, s = np.cos(theta), np.sin(theta)
        R = np.array([[c, -s], [s, c]])
        return (R @ xy.T).T


# ---------------------------------------------------------------------------
# convex_hull
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import _ch_simple as _ch

    def convex_hull(xy: np.ndarray) -> np.ndarray:
        """Convex hull vertices of (x,y) points. Used by callout collision."""
        return _ch(xy)

except (ImportError, AttributeError):
    def convex_hull(xy: np.ndarray) -> np.ndarray:
        """Convex hull via gift wrapping (pure numpy fallback)."""
        pts = xy.tolist()
        n = len(pts)
        if n < 3:
            return xy
        # Find leftmost point
        start = min(range(n), key=lambda i: (pts[i][0], pts[i][1]))
        hull = []
        current = start
        while True:
            hull.append(current)
            next_pt = (current + 1) % n
            for i in range(n):
                ax, ay = pts[next_pt][0] - pts[current][0], pts[next_pt][1] - pts[current][1]
                bx, by = pts[i][0] - pts[current][0], pts[i][1] - pts[current][1]
                cross = ax * by - ay * bx
                if cross > 0:
                    next_pt = i
            current = next_pt
            if current == start:
                break
        return np.array([pts[i] for i in hull])


# ---------------------------------------------------------------------------
# nearest_neighbors
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_analysis import n_near as _nn

    def nearest_neighbors(
        xy: np.ndarray, k: int = 1
    ) -> tuple[np.ndarray, np.ndarray]:
        """K nearest neighbors per point. Returns (indices, distances).
        Used by RPD duplicate location matching."""
        return _nn(xy, k, ordered=True)

except (ImportError, AttributeError):
    def nearest_neighbors(
        xy: np.ndarray, k: int = 1
    ) -> tuple[np.ndarray, np.ndarray]:
        """K nearest neighbors per point (pure numpy fallback)."""
        diff = xy[:, np.newaxis, :] - xy[np.newaxis, :, :]
        dist = np.sqrt((diff ** 2).sum(axis=-1))
        np.fill_diagonal(dist, np.inf)
        idx = np.argsort(dist, axis=1)[:, :k]
        dists = np.take_along_axis(dist, idx, axis=1)
        return idx, dists


# ---------------------------------------------------------------------------
# simplify_polyline
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import simplify as _simplify

    def simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray:
        """Douglas-Peucker simplification. Used by contour generalization."""
        return _simplify(xy, tolerance)

except (ImportError, AttributeError):
    def _dp_reduce(xy: np.ndarray, tol: float) -> list[int]:
        """Douglas-Peucker: return indices of points to keep."""
        if len(xy) <= 2:
            return list(range(len(xy)))
        start, end = xy[0], xy[-1]
        seg = end - start
        seg_len = np.linalg.norm(seg)
        if seg_len == 0:
            dists = np.linalg.norm(xy - start, axis=1)
        else:
            t = np.dot(xy - start, seg) / (seg_len ** 2)
            proj = start + np.outer(t, seg)
            dists = np.linalg.norm(xy - proj, axis=1)
        i_max = int(np.argmax(dists))
        if dists[i_max] <= tol:
            return [0, len(xy) - 1]
        left = _dp_reduce(xy[:i_max + 1], tol)
        right = _dp_reduce(xy[i_max:], tol)
        return left[:-1] + [i + i_max for i in right]

    def simplify_polyline(xy: np.ndarray, tolerance: float) -> np.ndarray:
        """Douglas-Peucker simplification (pure numpy fallback)."""
        if tolerance == 0.0 or len(xy) <= 2:
            return xy
        keep = _dp_reduce(xy, tolerance)
        return xy[keep]


# ---------------------------------------------------------------------------
# densify_polyline
# ---------------------------------------------------------------------------
try:
    from autogis.core.common.npg.npg_geom_ops import _densify_2D as _densify

    def densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray:
        """Add intermediate vertices. Used by contour smoothing."""
        return _densify(xy, factor)

except (ImportError, AttributeError):
    def densify_polyline(xy: np.ndarray, factor: int) -> np.ndarray:
        """Linear interpolation densification (pure numpy fallback)."""
        if factor <= 1 or len(xy) < 2:
            return xy
        parts = []
        for i in range(len(xy) - 1):
            t = np.linspace(0, 1, factor + 1, endpoint=False)
            seg = xy[i] + np.outer(t, xy[i + 1] - xy[i])
            parts.append(seg)
        parts.append(xy[-1:])
        return np.concatenate(parts, axis=0)
```

- [x] **Step 4: Run tests and confirm they pass**

Run: `python -m pytest tests/core/common/test_numpy_geom.py -q`  
Expected: All tests pass.

If `n_near` from Dan Patterson returns a different shape than `(n, k)` indices + `(n, k)` distances, adjust the wrapper's return statement to match. The tests define the contract — the wrapper must satisfy them regardless of what `npg/` returns internally.

- [x] **Step 5: Run full test suite to confirm no regressions**

Run: `python -m pytest -q`  
Expected: All existing tests still pass (151 tests + new tests)

- [x] **Step 6: Commit**

```bash
git add autogis/core/common/numpy_geom.py tests/core/common/test_numpy_geom.py
git commit -m "feat(numpy_geom): public API over npg/ — rotate, hull, nn, simplify, densify"
```

---

## Self-Review

**Spec coverage:**
- ✅ `run_history.py` — RunRecord + RunHistory with write/query/latest
- ✅ `schema/` — all 27 tables across 5 domain modules + `__init__.py` re-exports
- ✅ `npg/` — absorption steps, attribution, arcpy removal, function verification
- ✅ `numpy_geom.py` — 5 public functions with try/except fallbacks
- ✅ `setup.cfg` numpy dependency addition
- ✅ Tests: `test_schema.py`, `test_run_history.py`, `test_numpy_geom.py`
- ✅ No arcpy in any new file
- ✅ All tests runnable with `python -m pytest -q`

**Placeholder scan:** No TBD/TODO. All code blocks are complete implementations.

**Type consistency:**
- `nearest_neighbors` → `tuple[np.ndarray, np.ndarray]` — matches test destructuring `idx, dists = nearest_neighbors(...)`
- `SurveyPointQA.qa_flags` stored as JSON string in `to_row()` — noted inline
- `ElevationHistory.approved_for_use` / `superseded` are `bool` — consistent in test assertions
- `RunRecord.event_id: Optional[str]` — `None` sentinel roundtrip tested explicitly
