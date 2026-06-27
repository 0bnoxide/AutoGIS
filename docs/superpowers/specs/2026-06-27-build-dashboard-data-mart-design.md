# BuildDashboardDataMart Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** BuildDashboardDataMart (Phase 4.4a / Tool 6.7)
**Priority:** HIGH (prerequisite for AGOL dashboards; existing Dash_* tables have no population path)

---

## Problem

Ten `Dash_*` tables were added to TABLE_SCHEMAS in Phase 1.4 but no tool populates
them. They are designed as pre-flattened dashboard views — one row per site/event/well —
to avoid complex AGOL joins at dashboard render time. Without them, any AGOL dashboard
would have to join 5+ tables client-side, which is slow and brittle.

The graph navigator confirms these source mappings:
- `Dash_SiteStatus` ← `Env_CurrentEventWide` + `Env_ImportQA`
- `Dash_EventStatus` ← `Env_Samples` + `Env_AnalyticalResults`
- `Dash_WellStatus` ← `Env_CurrentWaterLevelEvent`
- `Dash_CurrentExceedances` ← `Env_AnalyticalResults WHERE ExceedsScreeningLevel=1`
- `Dash_GWLevelSummary` ← `Env_WaterLevels` two-event join
- `Dash_AnalyticalSummary` ← `Env_AnalyticalResults`
- `Dash_FieldQA` ← `Env_ImportQA WHERE AnalyteName IS NULL`
- `Dash_LabQA` ← `Env_ImportQA WHERE AnalyteName IS NOT NULL`
- `Dash_OpenIssues` ← `Env_ImportQA` grouped by Category + Severity
- `Dash_ReportReadiness` ← cross-check Env_Samples + Env_AnalyticalResults (same data as `EvaluateReportReadiness` tool)

---

## Approach

**Chosen:** LOCAL tool (arcpy) that reads source tables, transforms rows in pure Python,
then truncates and repopulates each `Dash_*` table. Pure-Python transformation layer is
arcpy-free and testable. One function per Dash_ table; orchestrated by
`build_dashboard_data_mart()`.

**Rejected: arcpy cursors with SQL aggregation.** SQL in arcpy cursors is brittle across
GDB backends. Prefer loading rows into Python dicts, aggregating in Python, then writing.

**Rejected: Materialized views via `arcpy.management.MakeTableView`.** Not persistent
between sessions; doesn't populate the actual tables.

---

## Architecture

```
autogis/
  core/envmon/
    dashboard_data_mart.py   ← NEW
  adapters/
    cli.py                   ← add build-dashboard-data-mart command (LOCAL)
tests/envmon/
  test_dashboard_data_mart.py ← NEW, arcpy-free (transformation functions only)
```

---

## Public API (`dashboard_data_mart.py`)

```python
@dataclass
class MartSummary:
    site_id: str
    event_id: str
    built_at: str
    tables_updated: list[str]
    row_counts: dict[str, int]

# --- Pure Python transformation functions (arcpy-free) ---

def build_dash_site_status(
    wide_rows: list[dict],      # from Env_CurrentEventWide
    qa_errors: list[dict],      # from Env_ImportQA (ERROR severity)
    site_id: str,
    event_id: str,
) -> list[dict]: ...

def build_dash_event_status(
    samples: list[dict],
    results: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]: ...

def build_dash_well_status(
    water_level_events: list[dict],   # from Env_CurrentWaterLevelEvent
    prior_water_level_events: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]: ...

def build_dash_current_exceedances(
    results: list[dict],   # filtered ExceedsScreeningLevel=1
    site_id: str,
    event_id: str,
) -> list[dict]: ...

# ... similar for remaining 6 tables ...

# --- LOCAL orchestrator (arcpy) ---

def build_dashboard_data_mart(   # pragma: no cover
    gdb_path: str,
    site_id: str,
    event_id: str,
    prior_event_id: Optional[str] = None,
) -> MartSummary: ...
```

---

## Transformation Notes

**`build_dash_gw_level_summary`:** Joins current and prior water level events by
`LocationID`. `Delta_ft = current.GWE_ft - prior.GWE_ft`. Trend:
- Delta > 0.1 ft → "Rising"
- Delta < -0.1 ft → "Falling"
- Otherwise → "Stable"

**`build_dash_current_exceedances`:** Filter `results` where `ExceedsScreeningLevel=1`
(already computed at import time by `normalize_*` functions). One row per
result (not aggregated — multiple analytes per location are separate rows).

**`build_dash_open_issues`:** Group `Env_ImportQA` rows by `(Domain, Severity,
Description)`, keeping the most recent `LastUpdated`.

---

## CLI Command

```
autogis envmon build-dashboard-data-mart <gdb> \
    --site H281 --event 2026Q2 \
    [--prior-event 2026Q1] \
    [--report mart_summary.md]
```

---

## Test Strategy

`tests/envmon/test_dashboard_data_mart.py` — all arcpy-free:

1. `build_dash_site_status()` with 3 wide_rows → returns 1 row with `ActiveEvents=3`
2. `build_dash_event_status()` with partial lab results → `LabReceived=False`
3. `build_dash_well_status()` with prior event data → correct `Delta_ft`
4. `build_dash_well_status()` rising delta → `Trend="Rising"`
5. `build_dash_current_exceedances()` filters only `ExceedsScreeningLevel=1` rows
6. `build_dash_field_qa()` filters `AnalyteName IS NULL` records only
7. `build_dash_lab_qa()` filters `AnalyteName IS NOT NULL` records only
8. `MartSummary` JSON-serializable via `dataclasses.asdict()`
