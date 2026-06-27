# UpgradeEnvMonitoringGDBSchema Design

**Date:** 2026-06-26  
**Status:** Approved  
**Tool:** UpgradeEnvMonitoringGDBSchema (Phase 1.4)  
**ADR:** 0018-upgrade-gdb-schema-tool.md  
**Priority:** HIGH (Phase 1 blocker — 27 domain tables missing from GDB)

---

## Problem

`gdb_schema.py::TABLE_SCHEMAS` contains 9 tables covering the core envmon import
pipeline. The Phase 1 scaffold added a 27-table `schema/` dataclass package spanning
boring, survey, drone, and dashboard domains. None of those 27 tables exist in the GDB.
Without them, any tool that tries to write boring logs, survey points, drone products,
or dashboard summaries will fail on first run.

There is also no version tracking: when a site GDB was last upgraded, which version of
the schema it reflects, or how many tables/fields were created — all of that is
invisible. The existing `create_or_update_gdb_schema()` is additive-only and correct
but returns no upgrade report and has no version concept.

---

## Approach

New `upgrade_schema.py` wraps the existing `create_or_update_gdb_schema()` without
modifying it. It adds:

1. **28 new entries in `TABLE_SCHEMAS`** — the 27 domain tables from `schema/` plus
   `Env_SchemaVersion` for version tracking.
2. **Pre-scan + post-call diffing** — snapshot tables/fields before calling the
   existing function, compare after; derive `[CREATED]` / `[UPDATED]` / `[OK]` status
   per table without a second arcpy scan.
3. **`UpgradeReport` dataclass** — pure Python, arcpy-free, captures full upgrade
   metrics and per-table status.
4. **CLI command `upgrade-schema`** — real Click command on the `envmon` group, guarded
   with `_guard()` then executes directly (not via .pyt stub).

---

## Architecture

```
autogis/
  core/envmon/
    gdb_schema.py          ← add 28 TABLE_SCHEMAS entries (Env_SchemaVersion + 27 domain)
    upgrade_schema.py      ← NEW: UpgradeReport, upgrade_gdb_schema(), format_report()
  adapters/
    cli.py                 ← add `upgrade-schema` command
tests/envmon/
  test_upgrade_schema.py   ← arcpy-free: dataclasses + format_report()
```

---

## New TABLE_SCHEMAS Entries

### Env_SchemaVersion (version tracking)
| Field | Type | Length |
|---|---|---|
| SchemaVersion | TEXT | 16 |
| UpgradedAt | DATE | — |
| PreviousVersion | TEXT | 16 |
| TablesCreated | LONG | — |
| FieldsAdded | LONG | — |
| UpgradedBy | TEXT | 64 |
| Notes | TEXT | 256 |

### Domain tables (one per `schema/` dataclass, PascalCase field names, mapped types)

**boring domain (7 tables):** BoringLocations, LithologyIntervals, BoringSamples,
WellConstruction, GroundwaterObservations, BoringPhotos, BoringComments

**survey domain (5 tables):** SurveyPoints_Raw, SurveyPoints_QA, LevelLoopRuns,
LevelLoopObservations, ElevationHistory

**drone domain (4 tables):** DroneFlights, DroneControlPoints, DroneCheckpoints,
DroneProductRegistry

**dashboard domain (10 tables):** Dash_SiteStatus, Dash_EventStatus, Dash_WellStatus,
Dash_CurrentExceedances, Dash_GWLevelSummary, Dash_AnalyticalSummary, Dash_FieldQA,
Dash_LabQA, Dash_OpenIssues, Dash_ReportReadiness

**envmon extension (1 table):** Env_CurrentWaterLevelEvent

Field mapping rules:
- `snake_case` attr → `PascalCase` GDB field
- `str` → `TEXT` (length from semantic context: IDs=32, names=64-128, paths=256)
- `float/Optional[float]` → `DOUBLE`
- `int/bool` → `SHORT` (booleans stored as 0/1)
- `date/datetime/Optional[date]` → `DATE` (length=None)
- `list` → `TEXT 512` (JSON string, e.g. `qa_flags`)

---

## Data Flow

```
upgrade-schema <gdb> [--spatial-reference WKID]
      │
      ▼
_guard("upgrade-schema")          ← ensures arcpy present
      │
      ▼
upgrade_gdb_schema(gdb, sr)       ← upgrade_schema.py
      │
      ├─ snapshot: tables_before = arcpy.ListTables(gdb)
      │             fields_before = {t: {f.name} for t in tables_before}
      │
      ├─ create_or_update_gdb_schema(gdb, sr)   ← existing, unmodified
      │
      ├─ tables_after = arcpy.ListTables(gdb)
      │   derive status per table:
      │     new table   → CREATED
      │     existing, more fields → UPDATED
      │     unchanged   → OK
      │
      └─ write Env_SchemaVersion row
             └─ TablesCreated, FieldsAdded from diff
      │
      ▼
UpgradeReport(gdb_path, previous_version, new_version="2.0", tables=[...])
      │
      ▼
format_report(report) → str      ← printed to stdout by CLI
```

---

## `upgrade_schema.py` Public API

```python
SCHEMA_VERSION = "2.0"

@dataclass
class TableUpgradeStatus:
    table_name: str
    status: str        # "CREATED" | "UPDATED" | "OK"
    fields_added: int

@dataclass
class UpgradeReport:
    gdb_path: str
    previous_version: str   # "" if no version table existed
    new_version: str
    tables: list[TableUpgradeStatus]
    elapsed_seconds: float = 0.0

    @property
    def tables_created(self) -> int: ...
    @property
    def fields_added(self) -> int: ...

def upgrade_gdb_schema(
    gdb_path: str,
    spatial_reference: int = 4326
) -> UpgradeReport:  # pragma: no cover — requires arcpy
    ...

def format_report(report: UpgradeReport) -> str:
    ...   # table-by-table [CREATED]/[UPDATED]/[OK], summary line
```

---

## CLI Command

```python
@envmon.command("upgrade-schema")
@click.argument("gdb")
@click.option("--spatial-reference", type=int, default=4326,
              help="WKID for spatial reference (default: 4326 = GCS WGS 1984)")
def upgrade_schema_cmd(gdb, spatial_reference):
    """Upgrade an envmon file GDB to the current schema version."""
    _guard("upgrade-schema")
    from ..core.envmon.upgrade_schema import upgrade_gdb_schema, format_report
    report = upgrade_gdb_schema(gdb, spatial_reference)
    click.echo(format_report(report))
```

---

## Version Bump Logic

- v1 = the original 9 TABLE_SCHEMAS tables (no version table present)
- v2 = v1 + 28 new entries (27 domain + Env_SchemaVersion)
- `previous_version` = read from `Env_SchemaVersion` if it exists, else `"1.0"`
- After upgrade, insert one row into `Env_SchemaVersion` with the counts

---

## Test Strategy

`tests/envmon/test_upgrade_schema.py` — all arcpy-free:

1. `TableUpgradeStatus` dataclass construction and attribute access
2. `UpgradeReport` property calculations (`tables_created`, `fields_added`)
3. `format_report()` output format — contains `[CREATED]`, `[UPDATED]`, `[OK]` strings
4. `format_report()` summary line contains correct counts
5. `format_report()` with zero changes (all-OK report)
6. `format_report()` with mixed statuses
7. `SCHEMA_VERSION` constant equals `"2.0"`

All arcpy code paths marked `# pragma: no cover`.
