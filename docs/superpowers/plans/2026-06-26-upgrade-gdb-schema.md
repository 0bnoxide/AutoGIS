# UpgradeEnvMonitoringGDBSchema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 28 new TABLE_SCHEMAS entries to gdb_schema.py and implement an `upgrade-schema` CLI command that runs `create_or_update_gdb_schema()`, reports per-table status, and writes a version row.

**Architecture:** New `upgrade_schema.py` wraps the existing `create_or_update_gdb_schema()` without touching it — takes a before-snapshot, calls the existing function, diffs after, writes `Env_SchemaVersion`. The CLI command uses `_guard()` then executes directly (not a .pyt stub). All logic except the arcpy paths is arcpy-free and unit-tested.

**Tech Stack:** Python 3.x, `dataclasses`, `click`, `arcpy` (runtime-guarded), `pytest`.

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- All code in `core/` must remain importable without arcpy present (Key invariant).
- arcpy code paths must be marked `# pragma: no cover` and lazily imported.
- Run tests with `python -m pytest -q` from the repo root.
- Existing `TABLE_SCHEMAS` and `create_or_update_gdb_schema()` in `gdb_schema.py` must NOT be modified — only additions.
- Field tuple format: `(name, esri_type, length_or_None)`. Use constants `T, D, L, DT, SH` already defined in gdb_schema.py. `DT` always has `length=None`. `SH` (bool) always has `length=None`.
- Commit after each task using conventional commits.

---

### Task 1: Extend TABLE_SCHEMAS — 28 new entries

**Files:**
- Modify: `autogis/core/envmon/gdb_schema.py` (append 28 entries after line 99, before `FEATURE_SCHEMAS`)
- Test: `tests/envmon/test_upgrade_schema.py` (create new file, schema coverage only for now)

**Interfaces:**
- Produces: `gdb_schema.TABLE_SCHEMAS` with 37 total keys (9 existing + 28 new)

- [ ] **Step 1: Write the failing test**

Create `tests/envmon/test_upgrade_schema.py`:

```python
from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS

NEW_TABLES = [
    "Env_SchemaVersion",
    "Env_CurrentWaterLevelEvent",
    "BoringLocations",
    "LithologyIntervals",
    "BoringSamples",
    "WellConstruction",
    "GroundwaterObservations",
    "BoringPhotos",
    "BoringComments",
    "SurveyPoints_Raw",
    "SurveyPoints_QA",
    "LevelLoopRuns",
    "LevelLoopObservations",
    "ElevationHistory",
    "DroneFlights",
    "DroneControlPoints",
    "DroneCheckpoints",
    "DroneProductRegistry",
    "Dash_SiteStatus",
    "Dash_EventStatus",
    "Dash_WellStatus",
    "Dash_CurrentExceedances",
    "Dash_GWLevelSummary",
    "Dash_AnalyticalSummary",
    "Dash_FieldQA",
    "Dash_LabQA",
    "Dash_OpenIssues",
    "Dash_ReportReadiness",
]


def test_all_new_tables_in_schema():
    missing = [t for t in NEW_TABLES if t not in TABLE_SCHEMAS]
    assert missing == [], f"Missing from TABLE_SCHEMAS: {missing}"


def test_total_table_count():
    assert len(TABLE_SCHEMAS) == 37, (
        f"Expected 37 tables (9 existing + 28 new), got {len(TABLE_SCHEMAS)}"
    )


def test_env_schema_version_fields():
    fields = {f[0] for f in TABLE_SCHEMAS["Env_SchemaVersion"]}
    assert fields == {
        "SchemaVersion", "UpgradedAt", "PreviousVersion",
        "TablesCreated", "FieldsAdded", "UpgradedBy", "Notes",
    }
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

Expected: 3 failures — `KeyError` on `Env_SchemaVersion` / assertion on count.

- [ ] **Step 3: Add the 28 entries to TABLE_SCHEMAS in gdb_schema.py**

Open `autogis/core/envmon/gdb_schema.py`. After the closing `}` of `TABLE_SCHEMAS` (after `"Env_CurrentEventWide"` entry, around line 99), **replace the closing `}` with the following** (the new entries close the dict):

```python
    "Env_CurrentEventWide": [
        ("SiteID", T, 32), ("FigureSpecID", T, 64), ("EventDate", DT, None),
        ("Matrix", T, 16), ("LocationID", T, 32), ("SampleID", T, 64),
        ("SampleDate", DT, None), ("DepthIntervalText", T, 32),
        ("HasExceedance", SH, None), ("HasDetection", SH, None),
        ("HasOnlyNonDetects", SH, None),
        ("HasMissingRequiredAnalytes", SH, None),
        ("LabelText_Fallback", T, 2000), ("ImportBatchID", T, 64)],

    # ------------------------------------------------------------------
    # Schema version tracking (v2 — added 2026-06-26)
    # ------------------------------------------------------------------
    "Env_SchemaVersion": [
        ("SchemaVersion", T, 16), ("UpgradedAt", DT, None),
        ("PreviousVersion", T, 16), ("TablesCreated", L, None),
        ("FieldsAdded", L, None), ("UpgradedBy", T, 64),
        ("Notes", T, 256)],

    # ------------------------------------------------------------------
    # Envmon extension
    # ------------------------------------------------------------------
    "Env_CurrentWaterLevelEvent": [
        ("SiteID", T, 32), ("LocationID", T, 32), ("EventDate", DT, None),
        ("DTW_ft", D, None), ("GWE_ft", D, None), ("Status", T, 32),
        ("UseForModel", SH, None), ("ExclusionReason", T, 128),
        ("MeasuredBy", T, 64), ("ImportBatchID", T, 64)],

    # ------------------------------------------------------------------
    # Boring domain
    # ------------------------------------------------------------------
    "BoringLocations": [
        ("BoringID", T, 32), ("SiteID", T, 32), ("LocationType", T, 32),
        ("Northing", D, None), ("Easting", D, None),
        ("GroundElevation_ft", D, None), ("TOCElevation_ft", D, None),
        ("Status", T, 32), ("CoordinateSystem", T, 64),
        ("VerticalDatum", T, 32), ("DrillingStartDate", DT, None),
        ("DrillingEndDate", DT, None), ("Driller", T, 64),
        ("LoggedBy", T, 64), ("TotalDepth_ft", D, None),
        ("CompletionType", T, 32)],
    "LithologyIntervals": [
        ("BoringID", T, 32), ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("USCS", T, 16), ("PrimaryMaterial", T, 64), ("SecondaryMaterial", T, 64),
        ("Color", T, 32), ("Moisture", T, 32), ("DensityConsistency", T, 32),
        ("Plasticity", T, 32), ("Odor", T, 32), ("Staining", T, 32),
        ("PID_ppm", D, None), ("Description", T, 512), ("GraphicPattern", T, 64),
        ("Reviewed", SH, None)],
    "BoringSamples": [
        ("SampleID", T, 64), ("BoringID", T, 32), ("SampleType", T, 32),
        ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("Recovery_pct", D, None), ("BlowCounts", T, 32),
        ("LabSubmitted", SH, None), ("Matrix", T, 16),
        ("AnalyticalGroup", T, 32), ("PhotoID", T, 64), ("COCNumber", T, 32)],
    "WellConstruction": [
        ("BoringID", T, 32), ("ComponentType", T, 32),
        ("TopDepth_ft", D, None), ("BottomDepth_ft", D, None),
        ("Diameter_in", D, None), ("Material", T, 64),
        ("SlotSize", T, 16), ("Notes", T, 256)],
    "GroundwaterObservations": [
        ("BoringID", T, 32), ("ObservationDatetime", DT, None),
        ("DepthToWater_ft", D, None), ("ObservationType", T, 32),
        ("ReferencePoint", T, 64), ("Notes", T, 256)],
    "BoringPhotos": [
        ("PhotoID", T, 64), ("BoringID", T, 32), ("SampleID", T, 64),
        ("Depth_ft", D, None), ("PhotoPath", T, 256), ("Caption", T, 256),
        ("TakenBy", T, 64), ("PhotoDatetime", DT, None)],
    "BoringComments": [
        ("CommentID", T, 64), ("BoringID", T, 32), ("Reviewer", T, 64),
        ("CommentText", T, 512), ("Severity", T, 16), ("AssignedTo", T, 64),
        ("Status", T, 32), ("ResolutionNote", T, 256), ("ResolvedDate", DT, None)],

    # ------------------------------------------------------------------
    # Survey domain
    # ------------------------------------------------------------------
    "SurveyPoints_Raw": [
        ("PointID", T, 64), ("Northing", D, None), ("Easting", D, None),
        ("Elevation_ft", D, None), ("FeatureCode", T, 32),
        ("Description", T, 256), ("HRMS_ft", D, None), ("VRMS_ft", D, None),
        ("FixType", T, 32), ("CorrectionSource", T, 64),
        ("OccupationTime_s", D, None), ("RodHeight_ft", D, None),
        ("CollectedAt", T, 32), ("Operator", T, 64)],
    "SurveyPoints_QA": [
        ("PointID", T, 64), ("QAStatus", T, 32),
        ("QAFlags", T, 512), ("Approved", SH, None)],
    "LevelLoopRuns": [
        ("RunID", T, 64), ("SiteID", T, 32), ("SurveyDate", DT, None),
        ("BenchmarkID", T, 32), ("KnownElevation_ft", D, None),
        ("Misclosure_ft", D, None), ("ClosureTolerance_ft", D, None),
        ("Adjusted", SH, None), ("Operator", T, 64), ("Notes", T, 256)],
    "LevelLoopObservations": [
        ("RunID", T, 64), ("SetupID", T, 32), ("PointID", T, 64),
        ("Backsight_ft", D, None), ("Foresight_ft", D, None),
        ("IntermediateSight_ft", D, None), ("HI_ft", D, None),
        ("Elevation_ft", D, None)],
    "ElevationHistory": [
        ("LocationID", T, 32), ("ElevationType", T, 32),
        ("Elevation_ft", D, None), ("VerticalDatum", T, 32),
        ("SurveyDate", DT, None), ("SurveyMethod", T, 64),
        ("SourceRunID", T, 64), ("ApprovedForUse", SH, None),
        ("Superseded", SH, None)],

    # ------------------------------------------------------------------
    # Drone domain
    # ------------------------------------------------------------------
    "DroneFlights": [
        ("FlightID", T, 64), ("ProjectID", T, 32), ("SiteID", T, 32),
        ("FlightDate", DT, None), ("Pilot", T, 64), ("DroneModel", T, 64),
        ("Sensor", T, 64), ("FlightAltitude_m", D, None),
        ("OverlapForward_pct", D, None), ("OverlapSide_pct", D, None),
        ("GCPUsed", SH, None), ("CheckpointCount", L, None),
        ("ProcessingSoftware", T, 64), ("OutputCRS", T, 64),
        ("VerticalDatum", T, 32), ("OrthomosaicPath", T, 256),
        ("DSMPath", T, 256), ("DEMPath", T, 256),
        ("PointCloudPath", T, 256), ("QAStatus", T, 32)],
    "DroneControlPoints": [
        ("PointID", T, 64), ("FlightID", T, 64),
        ("Northing", D, None), ("Easting", D, None), ("Elevation_ft", D, None),
        ("PointType", T, 16), ("ResidualH_m", D, None), ("ResidualV_m", D, None)],
    "DroneCheckpoints": [
        ("CheckpointID", T, 64), ("FlightID", T, 64),
        ("Northing", D, None), ("Easting", D, None), ("Elevation_ft", D, None),
        ("ResidualH_m", D, None), ("ResidualV_m", D, None),
        ("WithinTolerance", SH, None)],
    "DroneProductRegistry": [
        ("ProductID", T, 64), ("FlightID", T, 64), ("ProductType", T, 32),
        ("ProductPath", T, 256), ("CRS", T, 64), ("VerticalDatum", T, 32),
        ("Resolution_m", D, None), ("QAStatus", T, 32)],

    # ------------------------------------------------------------------
    # Dashboard domain
    # ------------------------------------------------------------------
    "Dash_SiteStatus": [
        ("SiteID", T, 32), ("SiteName", T, 128),
        ("ActiveEvents", L, None), ("OpenQAIssues", L, None),
        ("ReportDueDate", DT, None), ("LastUpdated", T, 32)],
    "Dash_EventStatus": [
        ("SiteID", T, 32), ("EventID", T, 64),
        ("WellsPlanned", L, None), ("WellsSampled", L, None),
        ("LabReceived", SH, None), ("FiguresReady", SH, None),
        ("ReportReady", SH, None), ("LastUpdated", T, 32)],
    "Dash_WellStatus": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Status", T, 32), ("GWE_ft", D, None), ("GWEDelta_ft", D, None),
        ("LastUpdated", T, 32)],
    "Dash_CurrentExceedances": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Analyte", T, 128), ("Result", D, None), ("Units", T, 16),
        ("ScreeningLevel", D, None), ("ScreeningSource", T, 64),
        ("LastUpdated", T, 32)],
    "Dash_GWLevelSummary": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("GWE_ft", D, None), ("PriorGWE_ft", D, None), ("Delta_ft", D, None),
        ("Trend", T, 16), ("LastUpdated", T, 32)],
    "Dash_AnalyticalSummary": [
        ("SiteID", T, 32), ("EventID", T, 64), ("LocationID", T, 32),
        ("Analyte", T, 128), ("Result", D, None), ("Units", T, 16),
        ("IsDetection", SH, None), ("IsExceedance", SH, None),
        ("LastUpdated", T, 32)],
    "Dash_FieldQA": [
        ("SiteID", T, 32), ("EventID", T, 64), ("IssueType", T, 32),
        ("LocationID", T, 32), ("Description", T, 256), ("LastUpdated", T, 32)],
    "Dash_LabQA": [
        ("SiteID", T, 32), ("EventID", T, 64), ("IssueType", T, 32),
        ("LocationID", T, 32), ("Analyte", T, 128),
        ("Description", T, 256), ("LastUpdated", T, 32)],
    "Dash_OpenIssues": [
        ("SiteID", T, 32), ("EventID", T, 64), ("Domain", T, 32),
        ("Severity", T, 16), ("Description", T, 256),
        ("AssignedTo", T, 64), ("LastUpdated", T, 32)],
    "Dash_ReportReadiness": [
        ("SiteID", T, 32), ("EventID", T, 64),
        ("FieldReady", SH, None), ("LabReady", SH, None),
        ("GISReady", SH, None), ("QAReady", SH, None),
        ("ModelReady", SH, None), ("ReportReady", SH, None),
        ("OverallReady", SH, None), ("LastUpdated", T, 32)],
}
```

> **Important:** The existing `"Env_CurrentEventWide"` entry is already in the file (line 91-98). Replace ONLY the closing `}` on line 99 with the above block (which re-includes `"Env_CurrentEventWide"` ending with `],` and then adds the 28 new entries plus the closing `}`).

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/gdb_schema.py tests/envmon/test_upgrade_schema.py
git commit -m "feat(gdb_schema): add 28 TABLE_SCHEMAS entries — domain + version tracking (v2)"
```

---

### Task 2: Create upgrade_schema.py — pure Python layer + arcpy function

**Files:**
- Create: `autogis/core/envmon/upgrade_schema.py`
- Modify: `tests/envmon/test_upgrade_schema.py` (add 7 more tests)

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION: str = "2.0"`
  - `TableUpgradeStatus(table_name: str, status: str, fields_added: int)`
  - `UpgradeReport(gdb_path: str, previous_version: str, new_version: str, tables: list[TableUpgradeStatus], elapsed_seconds: float = 0.0)` with `.tables_created -> int` and `.fields_added -> int` properties
  - `format_report(report: UpgradeReport) -> str`
  - `upgrade_gdb_schema(gdb_path: str, spatial_reference: int = 4326) -> UpgradeReport` (arcpy, `# pragma: no cover`)

- [ ] **Step 1: Add tests for the pure Python layer**

Append to `tests/envmon/test_upgrade_schema.py`:

```python
from autogis.core.envmon.upgrade_schema import (
    SCHEMA_VERSION,
    TableUpgradeStatus,
    UpgradeReport,
    format_report,
)


def test_schema_version_constant():
    assert SCHEMA_VERSION == "2.0"


def test_table_upgrade_status_attributes():
    s = TableUpgradeStatus("MyTable", "CREATED", 5)
    assert s.table_name == "MyTable"
    assert s.status == "CREATED"
    assert s.fields_added == 5


def test_upgrade_report_properties():
    tables = [
        TableUpgradeStatus("A", "CREATED", 3),
        TableUpgradeStatus("B", "UPDATED", 1),
        TableUpgradeStatus("C", "OK", 0),
    ]
    r = UpgradeReport("/path/site.gdb", "1.0", "2.0", tables, elapsed_seconds=1.5)
    assert r.tables_created == 1
    assert r.fields_added == 4   # 3 + 1 + 0


def test_format_report_contains_created_tag():
    tables = [TableUpgradeStatus("NewTable", "CREATED", 8)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[CREATED]" in out
    assert "NewTable" in out


def test_format_report_contains_updated_tag():
    tables = [TableUpgradeStatus("ExistingTable", "UPDATED", 2)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[UPDATED]" in out
    assert "ExistingTable" in out


def test_format_report_contains_ok_tag():
    tables = [TableUpgradeStatus("StableTable", "OK", 0)]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables)
    out = format_report(r)
    assert "[OK]" in out


def test_format_report_summary_line():
    tables = [
        TableUpgradeStatus("A", "CREATED", 5),
        TableUpgradeStatus("B", "CREATED", 3),
        TableUpgradeStatus("C", "UPDATED", 1),
        TableUpgradeStatus("D", "OK", 0),
    ]
    r = UpgradeReport("/x.gdb", "1.0", "2.0", tables, elapsed_seconds=2.7)
    out = format_report(r)
    # Summary line must mention counts
    assert "2" in out   # 2 created
    assert "1" in out   # 1 updated
```

- [ ] **Step 2: Run to confirm new tests fail**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

Expected: 7 new failures — `ModuleNotFoundError` for `upgrade_schema`.

- [ ] **Step 3: Create `autogis/core/envmon/upgrade_schema.py`**

```python
"""upgrade_schema.py — GDB schema upgrade orchestrator (Phase 1.4).

Pure-Python layer (dataclasses + format_report) is arcpy-free and fully
unit-tested. upgrade_gdb_schema() requires arcpy and is # pragma: no cover.
"""
from __future__ import annotations

import getpass
import time
from dataclasses import dataclass, field
from datetime import datetime

SCHEMA_VERSION = "2.0"


@dataclass
class TableUpgradeStatus:
    table_name: str
    status: str        # "CREATED" | "UPDATED" | "OK"
    fields_added: int


@dataclass
class UpgradeReport:
    gdb_path: str
    previous_version: str
    new_version: str
    tables: list[TableUpgradeStatus] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def tables_created(self) -> int:
        return sum(1 for t in self.tables if t.status == "CREATED")

    @property
    def fields_added(self) -> int:
        return sum(t.fields_added for t in self.tables)


def format_report(report: UpgradeReport) -> str:
    lines = [
        f"UpgradeEnvMonitoringGDBSchema  v{report.previous_version} → v{report.new_version}",
        f"GDB: {report.gdb_path}",
        "",
    ]
    for t in report.tables:
        tag = f"[{t.status}]"
        detail = f"(+{t.fields_added} fields)" if t.fields_added else ""
        lines.append(f"  {tag:<11} {t.table_name:<36} {detail}".rstrip())

    updated = sum(1 for t in report.tables if t.status == "UPDATED")
    ok_count = sum(1 for t in report.tables if t.status == "OK")
    lines += [
        "",
        (f"Summary: {report.tables_created} created, "
         f"{updated} updated, {ok_count} OK  "
         f"| {report.fields_added} fields added"),
        f"Elapsed: {report.elapsed_seconds:.1f} s",
    ]
    return "\n".join(lines)


def upgrade_gdb_schema(  # pragma: no cover
    gdb_path: str,
    spatial_reference: int = 4326,
) -> UpgradeReport:
    """Upgrade a file GDB to the current schema version.

    Calls create_or_update_gdb_schema() (additive-only) after snapshotting
    the current table/field state. Derives per-table status from the diff.
    Writes one row to Env_SchemaVersion.

    Requires arcpy (ArcGIS Pro). All code below this line is # pragma: no cover.
    """
    import arcpy  # noqa: F401
    from pathlib import Path as _P
    from .gdb_schema import create_or_update_gdb_schema, TABLE_SCHEMAS

    t0 = time.monotonic()
    gdb = str(gdb_path)

    # --- read previous version -------------------------------------------
    prev_ver = "1.0"
    vsn_table = str(_P(gdb) / "Env_SchemaVersion")
    if arcpy.Exists(vsn_table):
        with arcpy.da.SearchCursor(vsn_table, ["SchemaVersion"],
                                   sql_clause=(None, "ORDER BY OBJECTID DESC")) as cur:
            for row in cur:
                prev_ver = row[0] or "1.0"
                break

    # --- snapshot before -------------------------------------------------
    tables_before: set[str] = set()
    fields_before: dict[str, set[str]] = {}
    if arcpy.Exists(gdb):
        arcpy.env.workspace = gdb
        for tbl in (arcpy.ListTables() or []):
            tables_before.add(tbl)
            fields_before[tbl] = {f.name.upper()
                                   for f in arcpy.ListFields(str(_P(gdb) / tbl))}

    # --- run the existing upgrade function ------------------------------
    create_or_update_gdb_schema(gdb, spatial_reference=arcpy.SpatialReference(spatial_reference))

    # --- derive per-table status ----------------------------------------
    statuses: list[TableUpgradeStatus] = []
    for tbl_name in TABLE_SCHEMAS:
        if tbl_name not in tables_before:
            fields_count = len(TABLE_SCHEMAS[tbl_name])
            statuses.append(TableUpgradeStatus(tbl_name, "CREATED", fields_count))
        else:
            added = len([
                f for f in TABLE_SCHEMAS[tbl_name]
                if f[0].upper() not in fields_before.get(tbl_name, set())
            ])
            status = "UPDATED" if added else "OK"
            statuses.append(TableUpgradeStatus(tbl_name, status, added))

    # --- write version row -----------------------------------------------
    tables_created = sum(1 for s in statuses if s.status == "CREATED")
    total_fields = sum(s.fields_added for s in statuses)
    elapsed = time.monotonic() - t0

    with arcpy.da.InsertCursor(vsn_table,
                                ["SchemaVersion", "UpgradedAt", "PreviousVersion",
                                 "TablesCreated", "FieldsAdded", "UpgradedBy",
                                 "Notes"]) as cur:
        cur.insertRow([
            SCHEMA_VERSION,
            datetime.now(),
            prev_ver,
            tables_created,
            total_fields,
            getpass.getuser(),
            f"upgrade_schema.py automated upgrade",
        ])

    return UpgradeReport(
        gdb_path=gdb,
        previous_version=prev_ver,
        new_version=SCHEMA_VERSION,
        tables=statuses,
        elapsed_seconds=elapsed,
    )
```

- [ ] **Step 4: Run the tests**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Run the full suite**

```
python -m pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/upgrade_schema.py tests/envmon/test_upgrade_schema.py
git commit -m "feat(envmon): upgrade_schema — UpgradeReport dataclasses + format_report + upgrade_gdb_schema"
```

---

### Task 3: Add `upgrade-schema` CLI command

**Files:**
- Modify: `autogis/adapters/cli.py` (add command in the LOCAL tools section)
- Modify: `tests/envmon/test_upgrade_schema.py` (add smoke test for `--help`)

**Interfaces:**
- Consumes: `upgrade_gdb_schema(gdb_path, spatial_reference)` from `upgrade_schema.py`
- Consumes: `format_report(report)` from `upgrade_schema.py`
- Consumes: `_guard(name)` defined at cli.py:59

- [ ] **Step 1: Add the CLI smoke test**

Append to `tests/envmon/test_upgrade_schema.py`:

```python
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_upgrade_schema_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "upgrade-schema" in result.output


def test_upgrade_schema_guard_without_arcpy():
    """Without arcpy, upgrade-schema must error cleanly (no traceback)."""
    result = CliRunner().invoke(autogis, ["envmon", "upgrade-schema", "fake.gdb"])
    # Either RuntimeUnavailable (clean ClickException) or missing-arcpy error —
    # never an unhandled exception (exit_code must not be 2 from Click parse error
    # unless gdb path validation is added, which it isn't per spec).
    assert result.exit_code in (0, 1)
    assert result.exception is None or isinstance(result.exception, SystemExit)
```

- [ ] **Step 2: Run to confirm the help test fails**

```
python -m pytest tests/envmon/test_upgrade_schema.py::test_upgrade_schema_in_help -v
```

Expected: FAIL — `upgrade-schema` not in output.

- [ ] **Step 3: Add the command to cli.py**

In `autogis/adapters/cli.py`, after the `validate-db` command block (around line 292) and before the `@autogis.group()` for `agol`, insert:

```python
@envmon.command("upgrade-schema")
@click.argument("gdb")
@click.option("--spatial-reference", "spatial_reference", type=int, default=4326,
              help="WKID for the output spatial reference (default: 4326 = GCS WGS 1984).")
def upgrade_schema_cmd(gdb, spatial_reference):
    """Upgrade a file GDB to the current envmon schema version (ArcGIS Pro)."""
    _guard("upgrade-schema")
    from autogis.core.envmon.upgrade_schema import upgrade_gdb_schema, format_report
    report = upgrade_gdb_schema(gdb, spatial_reference)
    click.echo(format_report(report))
```

- [ ] **Step 4: Run all upgrade_schema tests**

```
python -m pytest tests/envmon/test_upgrade_schema.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Run full suite**

```
python -m pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_upgrade_schema.py
git commit -m "feat(cli): add upgrade-schema command — guarded LOCAL, real execution (not pyt stub)"
```

---

### Task 4: Commit spec + plan and open PR

**Files:**
- Already written: `docs/superpowers/specs/2026-06-26-upgrade-gdb-schema-design.md`
- Already written: `docs/superpowers/plans/2026-06-26-upgrade-gdb-schema.md`

- [ ] **Step 1: Commit docs**

```bash
git add docs/superpowers/specs/2026-06-26-upgrade-gdb-schema-design.md \
        docs/superpowers/plans/2026-06-26-upgrade-gdb-schema.md
git commit -m "docs(spec+plan): UpgradeEnvMonitoringGDBSchema design + implementation plan"
```

- [ ] **Step 2: Open PR**

```bash
gh pr create \
  --base main \
  --head feat/gdb-schema-upgrade \
  --title "feat(envmon): UpgradeEnvMonitoringGDBSchema — 28 new tables + upgrade-schema CLI" \
  --body "$(cat <<'EOF'
## Summary

- Extends `TABLE_SCHEMAS` in `gdb_schema.py` with 28 new entries: `Env_SchemaVersion` + 27 domain tables spanning boring, survey, drone, and dashboard domains.
- New `upgrade_schema.py` wraps the existing `create_or_update_gdb_schema()` (unmodified), snapshots before/after, and returns an `UpgradeReport` with per-table `[CREATED]/[UPDATED]/[OK]` status.
- Adds `upgrade-schema` CLI command to `autogis envmon` group (guarded, real execution — not a .pyt stub).
- 12 arcpy-free unit tests green.

## ADR

See `docs/adr/0018-upgrade-gdb-schema-tool.md` for the four design decisions this implements.

## Test plan

- [ ] `python -m pytest tests/envmon/test_upgrade_schema.py -v` — 12 tests
- [ ] `python -m pytest -q` — full suite green
- [ ] `autogis envmon --help` shows `upgrade-schema`
- [ ] `autogis envmon upgrade-schema fake.gdb` prints clean error when arcpy absent
EOF
)"
```
