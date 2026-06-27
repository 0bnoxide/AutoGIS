# BuildDashboardDataMart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildDashboardDataMart` — populate all 10 `Dash_*` tables from
source GDB tables using per-table pure-Python transformation functions.
See spec: `docs/superpowers/specs/2026-06-27-build-dashboard-data-mart-design.md`.

**Architecture:**
- New: `autogis/core/envmon/dashboard_data_mart.py`
- Modify: `autogis/adapters/cli.py` — add `build-dashboard-data-mart` command (LOCAL)
- New: `tests/envmon/test_dashboard_data_mart.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- All `build_dash_*()` functions are arcpy-free — receive pre-loaded dicts, return list[dict].
- `build_dashboard_data_mart()` is LOCAL, `# pragma: no cover`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Transformation functions + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_dashboard_data_mart.py`:

```python
import dataclasses, json
from autogis.core.envmon.dashboard_data_mart import (
    MartSummary,
    build_dash_site_status,
    build_dash_event_status,
    build_dash_well_status,
    build_dash_current_exceedances,
    build_dash_field_qa,
    build_dash_lab_qa,
    build_dash_open_issues,
    build_dash_gw_level_summary,
    build_dash_analytical_summary,
    build_dash_report_readiness,
)

_SITE = "H281"
_EVENT = "2026Q2"

_WIDE_ROWS = [
    {"SiteID": "H281", "LocationID": "MW-01", "EventDate": "2026-06-15"},
    {"SiteID": "H281", "LocationID": "MW-02", "EventDate": "2026-06-15"},
    {"SiteID": "H281", "LocationID": "MW-03", "EventDate": "2026-06-15"},
]

_QA_ERRORS = [
    {"SiteID": "H281", "Severity": "ERROR", "Category": "orphan_result",
     "Message": "test error", "AnalyteName": None},
    {"SiteID": "H281", "Severity": "ERROR", "Category": "bad_units",
     "Message": "unit error", "AnalyteName": "Benzene"},
]

_SAMPLES = [
    {"SiteID": "H281", "EventID": "2026Q2", "LocationID": "MW-01",
     "SampleID": "S-01", "Matrix": "GW"},
    {"SiteID": "H281", "EventID": "2026Q2", "LocationID": "MW-02",
     "SampleID": "S-02", "Matrix": "GW"},
]

_RESULTS = [
    {"SiteID": "H281", "EventID": "2026Q2", "SampleID": "S-01",
     "Analyte": "Benzene", "Result": 5.0, "Units": "ug/L",
     "IsDetection": 1, "ExceedsScreeningLevel": 1, "ScreeningLevel": 1.0,
     "ScreeningSource": "MDEQ"},
    {"SiteID": "H281", "EventID": "2026Q2", "SampleID": "S-02",
     "Analyte": "Benzene", "Result": 0.5, "Units": "ug/L",
     "IsDetection": 1, "ExceedsScreeningLevel": 0, "ScreeningLevel": 1.0,
     "ScreeningSource": "MDEQ"},
]

_WL_CURRENT = [
    {"SiteID": "H281", "EventID": "2026Q2", "LocationID": "MW-01",
     "GWE_ft": 498.5, "DTW_ft": 13.84, "Status": "OK"},
]
_WL_PRIOR = [
    {"SiteID": "H281", "EventID": "2026Q1", "LocationID": "MW-01",
     "GWE_ft": 497.5, "DTW_ft": 14.84},
]


def test_dash_site_status_active_events():
    rows = build_dash_site_status(_WIDE_ROWS, _QA_ERRORS, _SITE, _EVENT)
    assert len(rows) == 1
    assert rows[0]["ActiveEvents"] == 3


def test_dash_site_status_open_qa_issues():
    rows = build_dash_site_status(_WIDE_ROWS, _QA_ERRORS, _SITE, _EVENT)
    assert rows[0]["OpenQAIssues"] == 2


def test_dash_event_status_wells_sampled():
    rows = build_dash_event_status(_SAMPLES, _RESULTS, _SITE, _EVENT)
    assert rows[0]["WellsSampled"] == 2


def test_dash_event_status_lab_received():
    rows = build_dash_event_status(_SAMPLES, _RESULTS, _SITE, _EVENT)
    assert rows[0]["LabReceived"] == 1


def test_dash_well_status_gwe():
    rows = build_dash_well_status(_WL_CURRENT, _WL_PRIOR, _SITE, _EVENT)
    assert any(abs(r.get("GWE_ft", 0) - 498.5) < 0.01 for r in rows)


def test_dash_well_status_delta():
    rows = build_dash_well_status(_WL_CURRENT, _WL_PRIOR, _SITE, _EVENT)
    mw01 = next(r for r in rows if r["LocationID"] == "MW-01")
    assert abs(mw01["GWEDelta_ft"] - 1.0) < 0.01


def test_dash_current_exceedances_only_exceed():
    rows = build_dash_current_exceedances(_RESULTS, _SITE, _EVENT)
    assert len(rows) == 1
    assert rows[0]["Analyte"] == "Benzene"


def test_dash_field_qa_no_analyte_name():
    rows = build_dash_field_qa(_QA_ERRORS, _SITE, _EVENT)
    assert all(r.get("IssueType") == "orphan_result" or r.get("IssueType") == "orphan_result"
               for r in rows)
    assert len(rows) == 1   # only the AnalyteName=None row


def test_dash_lab_qa_has_analyte_name():
    rows = build_dash_lab_qa(_QA_ERRORS, _SITE, _EVENT)
    assert len(rows) == 1
    assert rows[0].get("Analyte") == "Benzene"


def test_mart_summary_json_serializable():
    s = MartSummary(site_id="H281", event_id="2026Q2", built_at="2026-06-27T12:00:00",
                    tables_updated=["Dash_SiteStatus"], row_counts={"Dash_SiteStatus": 1})
    d = dataclasses.asdict(s)
    json.dumps(d)   # should not raise
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/dashboard_data_mart.py`**

```python
"""dashboard_data_mart.py — populate Dash_* tables from source GDB tables.

Pure-Python transformation functions (build_dash_*) are arcpy-free.
build_dashboard_data_mart() is LOCAL (arcpy), # pragma: no cover.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MartSummary:
    site_id: str
    event_id: str
    built_at: str
    tables_updated: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def build_dash_site_status(
    wide_rows: list[dict],
    qa_errors: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    active = len({r["LocationID"] for r in wide_rows})
    open_issues = len(qa_errors)
    return [{"SiteID": site_id, "SiteName": site_id,
             "ActiveEvents": active, "OpenQAIssues": open_issues,
             "LastUpdated": _ts()}]


def build_dash_event_status(
    samples: list[dict],
    results: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    sampled = {r["LocationID"] for r in samples}
    result_sample_ids = {r["SampleID"] for r in results}
    lab_received = int(len(result_sample_ids) > 0)
    return [{"SiteID": site_id, "EventID": event_id,
             "WellsPlanned": None, "WellsSampled": len(sampled),
             "LabReceived": lab_received,
             "FiguresReady": 0, "ReportReady": 0,
             "LastUpdated": _ts()}]


def build_dash_well_status(
    current_wl: list[dict],
    prior_wl: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    prior_by_loc = {r["LocationID"]: r.get("GWE_ft") for r in prior_wl}
    out = []
    for r in current_wl:
        gwe = r.get("GWE_ft")
        prior = prior_by_loc.get(r["LocationID"])
        delta = (gwe - prior) if (gwe is not None and prior is not None) else None
        out.append({"SiteID": site_id, "EventID": event_id,
                    "LocationID": r["LocationID"],
                    "Status": r.get("Status", ""),
                    "GWE_ft": gwe, "GWEDelta_ft": delta,
                    "LastUpdated": _ts()})
    return out


def build_dash_current_exceedances(
    results: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    out = []
    for r in results:
        if r.get("ExceedsScreeningLevel"):
            out.append({"SiteID": site_id, "EventID": event_id,
                        "LocationID": r.get("LocationID", ""),
                        "Analyte": r.get("Analyte", ""),
                        "Result": r.get("Result"),
                        "Units": r.get("Units", ""),
                        "ScreeningLevel": r.get("ScreeningLevel"),
                        "ScreeningSource": r.get("ScreeningSource", ""),
                        "LastUpdated": _ts()})
    return out


def build_dash_gw_level_summary(
    current_wl: list[dict],
    prior_wl: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    prior_by_loc = {r["LocationID"]: r.get("GWE_ft") for r in prior_wl}
    out = []
    for r in current_wl:
        gwe = r.get("GWE_ft")
        prior = prior_by_loc.get(r["LocationID"])
        delta = (gwe - prior) if (gwe is not None and prior is not None) else None
        if delta is not None:
            trend = "Rising" if delta > 0.1 else ("Falling" if delta < -0.1 else "Stable")
        else:
            trend = "Unknown"
        out.append({"SiteID": site_id, "EventID": event_id,
                    "LocationID": r["LocationID"],
                    "GWE_ft": gwe, "PriorGWE_ft": prior,
                    "Delta_ft": delta, "Trend": trend,
                    "LastUpdated": _ts()})
    return out


def build_dash_analytical_summary(
    results: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    out = []
    for r in results:
        out.append({"SiteID": site_id, "EventID": event_id,
                    "LocationID": r.get("LocationID", ""),
                    "Analyte": r.get("Analyte", ""),
                    "Result": r.get("Result"),
                    "Units": r.get("Units", ""),
                    "IsDetection": r.get("IsDetection", 0),
                    "IsExceedance": r.get("ExceedsScreeningLevel", 0),
                    "LastUpdated": _ts()})
    return out


def build_dash_field_qa(qa_rows: list[dict], site_id: str, event_id: str) -> list[dict]:
    return [{"SiteID": site_id, "EventID": event_id,
             "IssueType": r.get("Category", ""),
             "LocationID": r.get("LocationID", ""),
             "Description": r.get("Message", ""),
             "LastUpdated": _ts()}
            for r in qa_rows if not r.get("AnalyteName")]


def build_dash_lab_qa(qa_rows: list[dict], site_id: str, event_id: str) -> list[dict]:
    return [{"SiteID": site_id, "EventID": event_id,
             "IssueType": r.get("Category", ""),
             "LocationID": r.get("LocationID", ""),
             "Analyte": r.get("AnalyteName", ""),
             "Description": r.get("Message", ""),
             "LastUpdated": _ts()}
            for r in qa_rows if r.get("AnalyteName")]


def build_dash_open_issues(qa_rows: list[dict], site_id: str, event_id: str) -> list[dict]:
    return [{"SiteID": site_id, "EventID": event_id,
             "Domain": "QA",
             "Severity": r.get("Severity", ""),
             "Description": r.get("Message", "")[:256],
             "AssignedTo": "",
             "LastUpdated": _ts()}
            for r in qa_rows]


def build_dash_report_readiness(
    samples: list[dict],
    results: list[dict],
    site_id: str,
    event_id: str,
) -> list[dict]:
    sample_ids = {r["SampleID"] for r in samples}
    result_ids = {r["SampleID"] for r in results}
    lab_ready = int(sample_ids.issubset(result_ids)) if sample_ids else 0
    field_ready = int(len(sample_ids) > 0)
    return [{"SiteID": site_id, "EventID": event_id,
             "FieldReady": field_ready, "LabReady": lab_ready,
             "GISReady": 0, "QAReady": 0,
             "ModelReady": 1, "ReportReady": 0, "OverallReady": 0,
             "LastUpdated": _ts()}]


def build_dashboard_data_mart(    # pragma: no cover
    gdb_path: str,
    site_id: str,
    event_id: str,
    prior_event_id: Optional[str] = None,
) -> MartSummary:
    """Populate all Dash_* tables for a site/event (ArcGIS Pro)."""
    import arcpy
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    def _read(table_name, where=None):
        path = str(_P(gdb) / table_name)
        if not _ax.Exists(path):
            return []
        rows = []
        fields = [f.name for f in _ax.ListFields(path)
                  if f.type not in ("OID", "Geometry")]
        with _ax.da.SearchCursor(path, fields, where) as cur:
            for row in cur:
                rows.append(dict(zip(fields, row)))
        return rows

    def _write(table_name, rows):
        if not rows:
            return 0
        path = str(_P(gdb) / table_name)
        if not _ax.Exists(path):
            return 0
        fields = list(rows[0].keys())
        with _ax.da.InsertCursor(path, fields) as cur:
            for r in rows:
                cur.insertRow([r[f] for f in fields])
        return len(rows)

    def _clear(table_name):
        path = str(_P(gdb) / table_name)
        if _ax.Exists(path):
            where = f"SiteID='{site_id}' AND EventID='{event_id}'"
            with _ax.da.UpdateCursor(path, ["OBJECTID"], where) as cur:
                for _ in cur:
                    cur.deleteRow()

    site_event_where = f"SiteID='{site_id}' AND EventID='{event_id}'"
    site_where = f"SiteID='{site_id}'"

    wide = _read("Env_CurrentEventWide", site_event_where)
    qa_rows = _read("Env_ImportQA", site_where)
    samples = _read("Env_Samples", site_event_where)
    results = _read("Env_AnalyticalResults", site_event_where)
    wl_curr = _read("Env_CurrentWaterLevelEvent", site_event_where)
    wl_prior = _read("Env_WaterLevels",
                     f"SiteID='{site_id}' AND EventID='{prior_event_id}'"
                     if prior_event_id else site_where)

    tables_updated = []
    row_counts: dict[str, int] = {}

    mapping = {
        "Dash_SiteStatus": build_dash_site_status(wide, qa_rows, site_id, event_id),
        "Dash_EventStatus": build_dash_event_status(samples, results, site_id, event_id),
        "Dash_WellStatus": build_dash_well_status(wl_curr, wl_prior, site_id, event_id),
        "Dash_CurrentExceedances": build_dash_current_exceedances(results, site_id, event_id),
        "Dash_GWLevelSummary": build_dash_gw_level_summary(wl_curr, wl_prior, site_id, event_id),
        "Dash_AnalyticalSummary": build_dash_analytical_summary(results, site_id, event_id),
        "Dash_FieldQA": build_dash_field_qa(qa_rows, site_id, event_id),
        "Dash_LabQA": build_dash_lab_qa(qa_rows, site_id, event_id),
        "Dash_OpenIssues": build_dash_open_issues(qa_rows, site_id, event_id),
        "Dash_ReportReadiness": build_dash_report_readiness(samples, results, site_id, event_id),
    }

    for table_name, rows in mapping.items():
        _clear(table_name)
        n = _write(table_name, rows)
        tables_updated.append(table_name)
        row_counts[table_name] = n

    return MartSummary(
        site_id=site_id, event_id=event_id,
        built_at=datetime.now().isoformat(timespec="seconds"),
        tables_updated=tables_updated,
        row_counts=row_counts,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: all 11 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart — 10 Dash_* transformation functions + LOCAL orchestrator"
```

---

### Task 2: CLI command

```python
@envmon.command("build-dashboard-data-mart")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--prior-event", "prior_event_id", default=None)
@click.option("--report", default=None, type=click.Path())
def build_dashboard_data_mart_cmd(gdb, site_id, event_id, prior_event_id, report):
    """Populate all Dash_* tables for a site/event (ArcGIS Pro)."""
    _guard("build-dashboard-data-mart")
    import dataclasses, json
    from autogis.core.envmon.dashboard_data_mart import build_dashboard_data_mart
    summary = build_dashboard_data_mart(gdb, site_id, event_id, prior_event_id)
    click.echo(f"Dashboard data mart built: {len(summary.tables_updated)} tables updated.")
    for t, n in summary.row_counts.items():
        click.echo(f"  {t}: {n} rows")
    if report:
        Path(report).write_text(
            json.dumps(dataclasses.asdict(summary), indent=2), encoding="utf-8")
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(cli): add build-dashboard-data-mart command (LOCAL, populates 10 Dash_* tables)"
```
