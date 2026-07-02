# RefreshMonitoringDashboardData Design

> **Deviation note (2026-07-02):** the shipped `dashboard_refresh.py` does NOT
> reference `schema/dashboard.py` as this spec assumes below. `schema/dashboard.py`'s
> `Dash_*` dataclasses were later found to have zero importers anywhere and were
> removed as dead code; see ADR-0014's status update and issue #120. Kept as a
> historical record of original intent, not current architecture.

**Date:** 2026-06-28
**Status:** Approved
**Tool:** RefreshMonitoringDashboardData (Tool 6.4)
**Priority:** MEDIUM — pushes the data-mart tables into the hosted layers a dashboard reads
**Runtime:** CLI ✓ / AGOL ✓ — `arcgis` (cloud extra), never arcpy

---

## Problem

`BuildDashboardDataMart` (6.7, planned) computes the flattened `Dash_*` tables locally.
A dashboard reads *hosted* feature layers, so those tables have to be pushed to AGOL each
event. Today that's a manual truncate-and-append in the AGOL UI. There is no tool that
refreshes the hosted dashboard layers from the local data mart.

---

## Approach

**Chosen:** A thin uploader over the data mart, on the injected-`gis` / lazy-`arcgis`
contract (same as `publish.py`). Given the local `Dash_*` tables (rows shaped by the
existing `schema/dashboard.py` dataclasses — `DashSiteStatus`, `DashCurrentExceedances`,
`DashGWLevelSummary`, etc.) and a mapping of table → hosted layer item, it truncates and
appends each hosted layer inside a per-table try/QA so one failure doesn't abort the rest.
A `--dry-run` validates row schema against the hosted layer fields without writing.

**Rejected: computing the mart here.** That's `BuildDashboardDataMart` (6.7). This tool
only *publishes* an already-built mart — single responsibility, reuses the mart's QA.

**Rejected: incremental upserts.** Dashboard tables are small and fully rebuilt per event;
truncate-append is simpler and avoids stale rows. (ponytail: upsert only if a table ever
grows past the truncate-append ceiling.)

**Rejected: `GIS()` in core.** Injected only; tests use a fake gis.

---

## Architecture

```
autogis/
  core/common/schema/
    dashboard.py              ← EXISTS (Dash_* dataclasses define the row contract)
  core/agol/
    dashboard_refresh.py      ← NEW (injected gis, lazy arcgis)
  adapters/
    cli.py                    ← add `agol refresh-dashboard` command
tests/
  test_agol_dashboard_refresh.py  ← NEW (fake gis)
```

---

## Public API (`dashboard_refresh.py`)

```python
@dataclass
class RefreshResult:
    tables_refreshed: int
    rows_pushed: dict[str, int]      # table -> row count
    failures: list[str]
    qa: QACollector

def refresh_dashboard_data(
    gis,                             # injected GIS
    mart_tables: dict[str, list[dict]],   # "Dash_SiteStatus" -> rows
    layer_map: dict[str, str],            # table name -> hosted layer item id
    *,
    dry_run: bool = False,
) -> RefreshResult:
    """Truncate+append each hosted dashboard layer from the local data mart."""
```

---

## CLI Command

```
autogis agol refresh-dashboard \
  --profile <agol_profile.yaml> \
  --mart-dir <data_mart/> \
  --layer-map <dash_layers.yaml> \
  [--dry-run] \
  [--report <refresh_qa.md>]
```

---

## Test Strategy

`tests/test_agol_dashboard_refresh.py` — fake injected `gis`:

1. Module imports without `arcgis` installed.
2. Each mapped table truncates then appends; fake gis records the calls in order.
3. `rows_pushed` matches input row counts per table.
4. A table missing from `layer_map` → WARNING, skipped, not a crash.
5. One hosted-layer failure is captured in `failures`; remaining tables still refresh.
6. `dry_run=True` validates row keys against layer fields and writes nothing.
