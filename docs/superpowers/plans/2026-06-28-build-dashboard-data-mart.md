# BuildDashboardDataMart Implementation Plan

> **Deviation note (2026-07-02):** the shipped `dashboard_data_mart.py` does NOT
> import from `schema/dashboard.py` as this plan specifies below -- it defines
> its own inline row structures instead. `schema/dashboard.py`'s `Dash_*`
> dataclasses were later found to have zero importers anywhere (including this
> tool) and were removed as dead code; see ADR-0014's status update and issue
> #120. This plan is kept as a historical record of original intent, not
> current architecture.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `BuildDashboardDataMart` (roadmap 6.7) — flatten raw analytical, water-level, and QA records into the 10 `Dash_*` dataclasses defined in `autogis/core/common/schema/dashboard.py`, serialize to JSON for headless use, and provide an arcpy GDB write seam for LOCAL production.

**Architecture:**
- New: `autogis/core/envmon/dashboard_data_mart.py` — 10 `flatten_*` functions returning `Dash_*` dataclass instances (arcpy-free, unit-tested), `DashboardMart` container, `write_mart_json()`, and two `# pragma: no cover` GDB seams (`read_source_from_gdb`, `write_mart_to_gdb`).
- Modify: `autogis/adapters/cli.py` — add `build-dashboard-mart` command; headless by default (JSON → JSON), LOCAL with `--gdb` flag.
- New: `tests/envmon/test_dashboard_data_mart.py`

**Tech Stack:** Python stdlib only (dataclasses, json, datetime, collections). No arcpy, no arcgis, no openpyxl in the headless tier.

## Global Constraints

- Branch: `feat/gdb-schema-upgrade` (or any clean feature branch off `main`)
- `flatten_*` functions and `build_mart()` must be importable with neither `arcpy` nor `arcgis` present — the core invariant (ADR-0002).
- `read_source_from_gdb()` and `write_mart_to_gdb()` are `# pragma: no cover`; they call `import arcpy` **inside** the function body (never at module level) following the pattern in `autogis/core/envmon/level_loop.py`.
- `Dash_*` dataclasses are imported from `autogis.core.common.schema.dashboard` — do not redefine them.
- CLI `--gdb` flag calls `_guard("build-dashboard-mart")` before arcpy ops; without `--gdb` the command is fully headless.
- Run tests with `python -m pytest -q`.
- Assumption: `event_id` is the event-date string "YYYY-MM-DD" (no separate event-ID table exists in current schema). Noted inline in module docstring.
- Assumption: GW trend threshold = ±0.5 ft (RISING if delta > +0.5, FALLING if delta < −0.5, STABLE otherwise). Noted inline.
- Assumption: QA category → domain routing uses frozensets grounded in `grep qa.add.*category=` across the codebase (see module constants). Unknown categories fall through to domain `"GENERAL"` in `DashOpenIssues`; nothing is silently dropped.

---

## File Map

| Path | Action | Responsibility |
|------|--------|---------------|
| `autogis/core/envmon/dashboard_data_mart.py` | Create | 10 `flatten_*` functions, `DashboardMart`, `build_mart`, `write_mart_json`, GDB seams |
| `tests/envmon/test_dashboard_data_mart.py` | Create | All unit tests for headless tier |
| `autogis/adapters/cli.py` | Modify | Add `build-dashboard-mart` command |

---

### Task 1: Module scaffold + `flatten_site_status` + `flatten_event_status`

**Files:**
- Create: `autogis/core/envmon/dashboard_data_mart.py`
- Create: `tests/envmon/test_dashboard_data_mart.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_dashboard_data_mart.py`:

```python
"""Tests for BuildDashboardDataMart headless flatten functions.

All tests are arcpy-free — source data is in-memory list[dict].
Field name convention for input dicts: snake_case matching the Dash_* dataclass fields.
"""
from autogis.core.envmon.dashboard_data_mart import (
    flatten_site_status,
    flatten_event_status,
)
from autogis.core.common.schema.dashboard import DashSiteStatus, DashEventStatus

# ---------------------------------------------------------------------------
# Shared test fixtures (reused across all tasks — add to bottom of each task)
# ---------------------------------------------------------------------------

_SAMPLES = [
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-01",
     "matrix": "GW", "sample_id": "S1-001"},
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-02",
     "matrix": "GW", "sample_id": "S1-002"},
    # Prior event — same site, different date
    {"site_id": "SITE1", "event_date": "2025-11-01", "location_id": "MW-01",
     "matrix": "GW", "sample_id": "S1-003"},
]

_QA_RECORDS = [
    {"severity": "ERROR", "category": "orphan_result", "location_id": "MW-01",
     "analyte": "", "description": "no parent sample", "sample_id": "S1-001"},
    {"severity": "WARNING", "category": "field_duplicate_present",
     "location_id": "MW-02", "analyte": "", "description": "dup flagged",
     "sample_id": "S1-002"},
    # INFO rows must NOT appear in QA tables
    {"severity": "INFO", "category": "validation_complete",
     "location_id": "", "analyte": "", "description": "done", "sample_id": ""},
]


# ---------------------------------------------------------------------------
# DashSiteStatus
# ---------------------------------------------------------------------------

def test_flatten_site_status_returns_dataclass():
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS)
    assert isinstance(result, DashSiteStatus)


def test_flatten_site_status_site_id():
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS)
    assert result.site_id == "SITE1"


def test_flatten_site_status_active_events_counts_distinct_dates():
    # Two distinct event_dates across the three sample rows → 2
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS)
    assert result.active_events == 2


def test_flatten_site_status_open_qa_excludes_info():
    # ERROR + WARNING = 2; INFO is excluded
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS)
    assert result.open_qa_issues == 2


def test_flatten_site_status_site_name():
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS,
                                 site_name="Acme Industrial")
    assert result.site_name == "Acme Industrial"


def test_flatten_site_status_last_updated_is_non_empty_string():
    result = flatten_site_status("SITE1", _SAMPLES, _QA_RECORDS)
    assert isinstance(result.last_updated, str) and result.last_updated


def test_flatten_site_status_empty_samples():
    result = flatten_site_status("SITE1", [], _QA_RECORDS)
    assert result.active_events == 0


# ---------------------------------------------------------------------------
# DashEventStatus
# ---------------------------------------------------------------------------

def test_flatten_event_status_returns_dataclass():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert isinstance(result, DashEventStatus)


def test_flatten_event_status_wells_sampled_filters_by_event():
    # Only 2 of the 3 samples belong to "2026-05-01"
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert result.wells_sampled == 2


def test_flatten_event_status_wells_planned_defaults_to_sampled():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert result.wells_planned == result.wells_sampled


def test_flatten_event_status_wells_planned_explicit_override():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES,
                                  ["MW-01", "MW-02", "MW-03"], _QA_RECORDS)
    assert result.wells_planned == 3


def test_flatten_event_status_lab_received_true_when_samples_exist():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert result.lab_received is True


def test_flatten_event_status_lab_received_false_when_no_event_samples():
    result = flatten_event_status("SITE1", "2099-01-01", _SAMPLES, None, _QA_RECORDS)
    assert result.lab_received is False


def test_flatten_event_status_figures_ready_default_false():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert result.figures_ready is False


def test_flatten_event_status_report_ready_default_false():
    result = flatten_event_status("SITE1", "2026-05-01", _SAMPLES, None, _QA_RECORDS)
    assert result.report_ready is False
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'autogis.core.envmon.dashboard_data_mart'`

- [ ] **Step 3: Create `autogis/core/envmon/dashboard_data_mart.py` with scaffold + first two functions**

```python
"""dashboard_data_mart.py — flatten Env_* source tables into Dash_* dashboard tables.

All ``flatten_*`` functions are arcpy-free: they accept in-memory ``list[dict]``
and return ``Dash_*`` dataclass instances from ``autogis.core.common.schema.dashboard``.
``build_mart()`` and ``write_mart_json()`` are also headless.

GDB seams (``read_source_from_gdb``, ``write_mart_to_gdb``) are LOCAL — they call
``import arcpy`` inside the function body and are marked ``# pragma: no cover``.

Assumptions (noted here per spec):
  - ``event_id`` is the event-date string "YYYY-MM-DD"; no separate event table exists.
  - GW trend threshold = ±0.5 ft: RISING if Δ > +0.5, FALLING if Δ < −0.5, else STABLE.
  - QA domain routing uses frozensets grounded in grep of qa.add() calls in the codebase.
    Unknown categories fall through to domain "GENERAL" in DashOpenIssues; nothing dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..common.schema.dashboard import (
    DashSiteStatus, DashEventStatus, DashWellStatus,
    DashCurrentExceedances, DashGWLevelSummary, DashAnalyticalSummary,
    DashFieldQA, DashLabQA, DashOpenIssues, DashReportReadiness,
)

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

#: Input-dict severity values that count as "open" QA issues.
_OPEN_SEVERITIES: frozenset[str] = frozenset({"ERROR", "WARNING"})

#: GW water-level delta thresholds for trend classification (feet).
_TREND_RISING_FT: float = 0.5
_TREND_FALLING_FT: float = -0.5

#: QA categories produced by field-collection or location-reconciliation logic.
#: Grounded in grep of qa.add(...category=...) across autogis/core/envmon/.
FIELD_QA_CATEGORIES: frozenset[str] = frozenset({
    "well_not_sampled",             # reconcile_locations
    "field_duplicate_present",      # build_current_event duplicate rules
    "sample_id_not_found",          # build_current_event specific_sample_ids rule
})

#: QA categories produced by lab-result processing or EDD-import logic.
LAB_QA_CATEGORIES: frozenset[str] = frozenset({
    "averaged_parent_duplicate",    # build_current_event
    "average_rule_nondetect_pair",  # build_current_event
    "unit_conversion_failed",       # apply_screening
    "no_results_for_figure",        # build_current_event
    "orphan_result",                # validate_database
    "duplicate_sample_key",         # validate_database
    "import_qa_errors_present",     # evaluate_readiness
    "multiple_results_after_rules", # build_current_event
})

#: GIS/figure categories — routed to "GIS" domain in DashOpenIssues.
GIS_QA_CATEGORIES: frozenset[str] = frozenset({
    "broken_data_source",           # export_figures
    "repath_failed",                # layout_manager
    "defquery_layer_missing",       # layout_manager
    "lyrx_missing",                 # layout_manager
    "lyrx_apply_failed",            # layout_manager
    "boundary_layer_missing",       # layout_manager
    "export_blocked",               # export_figures
    "layout_missing",               # export_figures / layout_manager
    "table_missing",                # validate_database
    "field_missing",                # validate_database
})


def _now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _qa_domain(category: str) -> str:
    """Map a QA category string to a domain label for DashOpenIssues."""
    if category in FIELD_QA_CATEGORIES:
        return "FIELD"
    if category in LAB_QA_CATEGORIES:
        return "LAB"
    if category in GIS_QA_CATEGORIES:
        return "GIS"
    return "GENERAL"


# ---------------------------------------------------------------------------
# DashboardMart container
# ---------------------------------------------------------------------------

@dataclass
class DashboardMart:
    """Holds all 10 Dash_* table outputs from a single build_mart() call."""
    site_status: DashSiteStatus
    event_status: DashEventStatus
    well_statuses: list[DashWellStatus]
    gw_level_summaries: list[DashGWLevelSummary]
    analytical_summaries: list[DashAnalyticalSummary]
    current_exceedances: list[DashCurrentExceedances]
    field_qa: list[DashFieldQA]
    lab_qa: list[DashLabQA]
    open_issues: list[DashOpenIssues]
    report_readiness: DashReportReadiness
    built_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict (date objects converted to ISO strings)."""
        def _default(obj):
            from datetime import date
            if isinstance(obj, date):
                return obj.isoformat()
            raise TypeError(f"Not serialisable: {type(obj)}")

        raw = {
            "site_status": asdict(self.site_status),
            "event_status": asdict(self.event_status),
            "well_statuses": [asdict(r) for r in self.well_statuses],
            "gw_level_summaries": [asdict(r) for r in self.gw_level_summaries],
            "analytical_summaries": [asdict(r) for r in self.analytical_summaries],
            "current_exceedances": [asdict(r) for r in self.current_exceedances],
            "field_qa": [asdict(r) for r in self.field_qa],
            "lab_qa": [asdict(r) for r in self.lab_qa],
            "open_issues": [asdict(r) for r in self.open_issues],
            "report_readiness": asdict(self.report_readiness),
            "built_at": self.built_at,
        }
        # Normalise date objects to strings (asdict preserves Python date objects)
        return json.loads(json.dumps(raw, default=_default))


# ---------------------------------------------------------------------------
# flatten_site_status
# ---------------------------------------------------------------------------

def flatten_site_status(
    site_id: str,
    samples: list[dict],
    qa_records: list[dict],
    site_name: str = "",
    report_due_date: Optional[str] = None,
) -> DashSiteStatus:
    """Aggregate site-level KPIs into DashSiteStatus.

    Args:
        site_id: Site identifier string.
        samples: All sample dicts for this site (any event). Each dict must
            have key ``event_date`` (str "YYYY-MM-DD").
        qa_records: All QA record dicts for this site. Each must have
            ``severity`` (str "ERROR"/"WARNING"/"INFO").
        site_name: Human-readable site label (optional).
        report_due_date: ISO date string "YYYY-MM-DD" or None.

    Returns:
        DashSiteStatus with active_events = distinct event_date count,
        open_qa_issues = count of ERROR + WARNING records.
    """
    active_events = len({s["event_date"] for s in samples if s.get("event_date")})
    open_qa = sum(
        1 for r in qa_records
        if r.get("severity", "").upper() in _OPEN_SEVERITIES
    )
    return DashSiteStatus(
        site_id=site_id,
        site_name=site_name,
        active_events=active_events,
        open_qa_issues=open_qa,
        report_due_date=report_due_date,
        last_updated=_now(),
    )


# ---------------------------------------------------------------------------
# flatten_event_status
# ---------------------------------------------------------------------------

def flatten_event_status(
    site_id: str,
    event_id: str,
    samples: list[dict],
    wells_planned: Optional[list[str]],
    qa_records: list[dict],
    lab_ready: bool = False,
    figures_ready: bool = False,
) -> DashEventStatus:
    """Build DashEventStatus for one site/event.

    Args:
        site_id: Site identifier.
        event_id: Event identifier (event_date string "YYYY-MM-DD").
        samples: All sample dicts for this site (all events). Filtered
            internally to rows where ``event_date == event_id``.
        wells_planned: Explicit list of planned LocationIDs, or None to
            default to the count of sampled locations.
        qa_records: QA records (used for future gate; currently unused here
            but kept for API symmetry with build_mart).
        lab_ready: True if caller confirms lab data received.
        figures_ready: True if figures have been exported.

    Returns:
        DashEventStatus with report_ready=False (set by build_mart after
        flatten_report_readiness is computed).
    """
    event_samples = [s for s in samples if s.get("event_date") == event_id]
    sampled_locs = {s["location_id"] for s in event_samples if s.get("location_id")}
    planned_count = (
        len(wells_planned) if wells_planned is not None else len(sampled_locs)
    )
    lab_received = lab_ready or bool(event_samples)
    return DashEventStatus(
        site_id=site_id,
        event_id=event_id,
        wells_planned=planned_count,
        wells_sampled=len(sampled_locs),
        lab_received=lab_received,
        figures_ready=figures_ready,
        report_ready=False,   # updated by build_mart() after readiness check
        last_updated=_now(),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: all 16 tests PASS.

- [ ] **Step 5: Full suite smoke-check + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart scaffold — flatten_site_status, flatten_event_status + 16 tests"
```

---

### Task 2: `flatten_well_status` + `flatten_gw_level_summary`

**Files:**
- Modify: `autogis/core/envmon/dashboard_data_mart.py` (append two functions)
- Modify: `tests/envmon/test_dashboard_data_mart.py` (append test block)

- [ ] **Step 1: Append the failing tests to `tests/envmon/test_dashboard_data_mart.py`**

```python
# ── append to test file ──────────────────────────────────────────────────────
from autogis.core.envmon.dashboard_data_mart import (
    flatten_well_status,
    flatten_gw_level_summary,
)
from autogis.core.common.schema.dashboard import DashWellStatus, DashGWLevelSummary

_WATER_LEVELS = [
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-01",
     "gwe_ft": 10.5, "dtw_ft": 5.5, "measurement_status": "OK",
     "use_for_contour": True},
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-02",
     "gwe_ft": 9.0, "dtw_ft": 7.0, "measurement_status": "Dry",
     "use_for_contour": False},
]

_PRIOR_WL = [
    {"site_id": "SITE1", "event_date": "2025-11-01", "location_id": "MW-01",
     "gwe_ft": 9.8, "dtw_ft": 6.2, "measurement_status": "OK",
     "use_for_contour": True},
    {"site_id": "SITE1", "event_date": "2025-11-01", "location_id": "MW-02",
     "gwe_ft": 9.5, "dtw_ft": 6.5, "measurement_status": "OK",
     "use_for_contour": True},
]


# ---------- flatten_well_status ----------

def test_flatten_well_status_returns_list_of_dataclasses():
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    assert all(isinstance(r, DashWellStatus) for r in result)


def test_flatten_well_status_count():
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    assert len(result) == 2


def test_flatten_well_status_gwe_ft():
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert abs(mw01.gwe_ft - 10.5) < 0.001


def test_flatten_well_status_delta_computed():
    # MW-01: current=10.5, prior=9.8 → delta = +0.7
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert abs(mw01.gwe_delta_ft - 0.7) < 0.01


def test_flatten_well_status_no_prior_delta_is_none():
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert mw01.gwe_delta_ft is None


def test_flatten_well_status_status_from_measurement():
    result = flatten_well_status("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw02 = next(r for r in result if r.location_id == "MW-02")
    assert mw02.status == "Dry"


def test_flatten_well_status_filters_to_event():
    # Pass mixed events; only "2026-05-01" rows should appear
    mixed = _WATER_LEVELS + _PRIOR_WL
    result = flatten_well_status("SITE1", "2026-05-01", mixed)
    assert len(result) == 2
    assert all(r.event_id == "2026-05-01" for r in result)


# ---------- flatten_gw_level_summary ----------

def test_flatten_gw_level_summary_returns_list_of_dataclasses():
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    assert all(isinstance(r, DashGWLevelSummary) for r in result)


def test_flatten_gw_level_summary_count():
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    assert len(result) == 2


def test_flatten_gw_level_summary_delta():
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert abs(mw01.delta_ft - 0.7) < 0.01


def test_flatten_gw_level_summary_trend_rising():
    # MW-01 delta = +0.7 > +0.5 → RISING
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert mw01.trend == "RISING"


def test_flatten_gw_level_summary_trend_stable():
    # MW-02: current=9.0, prior=9.5 → delta = -0.5; |-0.5| <= 0.5 → STABLE
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw02 = next(r for r in result if r.location_id == "MW-02")
    assert mw02.trend == "STABLE"


def test_flatten_gw_level_summary_no_prior_trend_empty_delta_none():
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert mw01.trend == ""
    assert mw01.delta_ft is None


def test_flatten_gw_level_summary_prior_gwe_stored():
    result = flatten_gw_level_summary("SITE1", "2026-05-01", _WATER_LEVELS, _PRIOR_WL)
    mw01 = next(r for r in result if r.location_id == "MW-01")
    assert abs(mw01.prior_gwe_ft - 9.8) < 0.001
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: FAIL — `ImportError: cannot import name 'flatten_well_status'`

- [ ] **Step 3: Append two functions to `autogis/core/envmon/dashboard_data_mart.py`**

```python
# ── append to dashboard_data_mart.py ────────────────────────────────────────

def flatten_well_status(
    site_id: str,
    event_id: str,
    water_levels: list[dict],
    prior_water_levels: Optional[list[dict]] = None,
) -> list[DashWellStatus]:
    """One DashWellStatus row per location in the current event.

    Args:
        site_id: Site identifier.
        event_id: Event-date string "YYYY-MM-DD". Records with a different
            ``event_date`` are ignored.
        water_levels: All water-level dicts for this site (any event). Each
            dict must have keys: ``location_id``, ``event_date``, ``gwe_ft``
            (Optional[float]), ``dtw_ft`` (Optional[float]),
            ``measurement_status`` (str).
        prior_water_levels: Water-level dicts for the prior event. Used only
            to compute ``gwe_delta_ft``; if None, delta is None.

    Returns:
        List of DashWellStatus instances, one per location in event_id.
    """
    current = [r for r in water_levels if r.get("event_date") == event_id]
    prior_by_loc: dict[str, Optional[float]] = {}
    if prior_water_levels:
        for r in prior_water_levels:
            loc = r.get("location_id", "")
            if loc:
                prior_by_loc[loc] = r.get("gwe_ft")

    out: list[DashWellStatus] = []
    for r in current:
        loc = r.get("location_id", "")
        gwe = r.get("gwe_ft")
        prior = prior_by_loc.get(loc)
        delta = (gwe - prior) if (gwe is not None and prior is not None) else None
        out.append(DashWellStatus(
            site_id=site_id,
            event_id=event_id,
            location_id=loc,
            status=r.get("measurement_status", ""),
            gwe_ft=gwe,
            gwe_delta_ft=delta,
            last_updated=_now(),
        ))
    return out


def flatten_gw_level_summary(
    site_id: str,
    event_id: str,
    water_levels: list[dict],
    prior_water_levels: Optional[list[dict]] = None,
) -> list[DashGWLevelSummary]:
    """One DashGWLevelSummary row per location — current GWE, prior GWE, delta, trend.

    Trend classification (module constant _TREND_RISING_FT = +0.5 ft,
    _TREND_FALLING_FT = −0.5 ft):
      - delta > +0.5 → "RISING"
      - delta < −0.5 → "FALLING"
      - |delta| ≤ 0.5 → "STABLE"
      - No prior data → trend = ""

    Args:
        site_id: Site identifier.
        event_id: Event-date string "YYYY-MM-DD".
        water_levels: All water-level dicts (any event); filtered by event_date.
        prior_water_levels: Prior-event water-level dicts; if None, delta and
            trend are omitted (None/"").
    """
    current = [r for r in water_levels if r.get("event_date") == event_id]
    prior_by_loc: dict[str, Optional[float]] = {}
    if prior_water_levels:
        for r in prior_water_levels:
            loc = r.get("location_id", "")
            if loc:
                prior_by_loc[loc] = r.get("gwe_ft")

    out: list[DashGWLevelSummary] = []
    for r in current:
        loc = r.get("location_id", "")
        gwe = r.get("gwe_ft")
        prior = prior_by_loc.get(loc)
        delta = (gwe - prior) if (gwe is not None and prior is not None) else None
        if delta is not None:
            if delta > _TREND_RISING_FT:
                trend = "RISING"
            elif delta < _TREND_FALLING_FT:
                trend = "FALLING"
            else:
                trend = "STABLE"
        else:
            trend = ""
        out.append(DashGWLevelSummary(
            site_id=site_id,
            event_id=event_id,
            location_id=loc,
            gwe_ft=gwe,
            prior_gwe_ft=prior,
            delta_ft=delta,
            trend=trend,
            last_updated=_now(),
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: all tests pass (16 from Task 1 + 16 new = 32 total).

- [ ] **Step 5: Full suite smoke-check + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart — flatten_well_status, flatten_gw_level_summary (trend RISING/STABLE/FALLING)"
```

---

### Task 3: `flatten_current_exceedances` + `flatten_analytical_summary`

**Files:**
- Modify: `autogis/core/envmon/dashboard_data_mart.py`
- Modify: `tests/envmon/test_dashboard_data_mart.py`

- [ ] **Step 1: Append the failing tests**

```python
# ── append to test file ──────────────────────────────────────────────────────
from autogis.core.envmon.dashboard_data_mart import (
    flatten_current_exceedances,
    flatten_analytical_summary,
)
from autogis.core.common.schema.dashboard import (
    DashCurrentExceedances, DashAnalyticalSummary,
)

_RESULTS = [
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-01",
     "sample_id": "S1-001", "sample_date": "2026-05-01",
     "analyte": "Benzene", "result": 150.0, "units": "ug/L",
     "is_detection": True, "is_nondetect": False, "is_exceedance": True,
     "screening_level": 5.0, "screening_source": "EPA MCL"},
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-02",
     "sample_id": "S1-002", "sample_date": "2026-05-01",
     "analyte": "Benzene", "result": 1.0, "units": "ug/L",
     "is_detection": True, "is_nondetect": False, "is_exceedance": False,
     "screening_level": 5.0, "screening_source": "EPA MCL"},
    {"site_id": "SITE1", "event_date": "2026-05-01", "location_id": "MW-01",
     "sample_id": "S1-001", "sample_date": "2026-05-01",
     "analyte": "Toluene", "result": 0.5, "units": "ug/L",
     "is_detection": False, "is_nondetect": True, "is_exceedance": False,
     "screening_level": 1000.0, "screening_source": "EPA MCL"},
]


# ---------- flatten_current_exceedances ----------

def test_flatten_current_exceedances_returns_list_of_dataclasses():
    result = flatten_current_exceedances("SITE1", "2026-05-01", _RESULTS)
    assert all(isinstance(r, DashCurrentExceedances) for r in result)


def test_flatten_current_exceedances_only_exceedances():
    result = flatten_current_exceedances("SITE1", "2026-05-01", _RESULTS)
    assert len(result) == 1


def test_flatten_current_exceedances_location_and_analyte():
    result = flatten_current_exceedances("SITE1", "2026-05-01", _RESULTS)
    row = result[0]
    assert row.location_id == "MW-01"
    assert row.analyte == "Benzene"


def test_flatten_current_exceedances_result_value():
    result = flatten_current_exceedances("SITE1", "2026-05-01", _RESULTS)
    assert abs(result[0].result - 150.0) < 0.01


def test_flatten_current_exceedances_screening_source():
    result = flatten_current_exceedances("SITE1", "2026-05-01", _RESULTS)
    assert result[0].screening_source == "EPA MCL"


def test_flatten_current_exceedances_empty_when_none_exceed():
    no_exc = [dict(r, is_exceedance=False) for r in _RESULTS]
    result = flatten_current_exceedances("SITE1", "2026-05-01", no_exc)
    assert result == []


# ---------- flatten_analytical_summary ----------

def test_flatten_analytical_summary_returns_list_of_dataclasses():
    result = flatten_analytical_summary("SITE1", "2026-05-01", _RESULTS)
    assert all(isinstance(r, DashAnalyticalSummary) for r in result)


def test_flatten_analytical_summary_one_row_per_location_analyte():
    # MW-01/Benzene, MW-01/Toluene, MW-02/Benzene → 3 rows
    result = flatten_analytical_summary("SITE1", "2026-05-01", _RESULTS)
    assert len(result) == 3


def test_flatten_analytical_summary_exceedance_flag():
    result = flatten_analytical_summary("SITE1", "2026-05-01", _RESULTS)
    mw01_benz = next(
        r for r in result if r.location_id == "MW-01" and r.analyte == "Benzene"
    )
    assert mw01_benz.is_exceedance is True
    assert mw01_benz.is_detection is True


def test_flatten_analytical_summary_nondetect_flags():
    result = flatten_analytical_summary("SITE1", "2026-05-01", _RESULTS)
    mw01_tol = next(
        r for r in result if r.location_id == "MW-01" and r.analyte == "Toluene"
    )
    assert mw01_tol.is_detection is False
    assert mw01_tol.is_exceedance is False


def test_flatten_analytical_summary_no_exceedance_below_sl():
    result = flatten_analytical_summary("SITE1", "2026-05-01", _RESULTS)
    mw02_benz = next(
        r for r in result if r.location_id == "MW-02" and r.analyte == "Benzene"
    )
    assert mw02_benz.is_exceedance is False
    assert mw02_benz.is_detection is True
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py::test_flatten_current_exceedances_only_exceedances -v
```

Expected: FAIL — `ImportError: cannot import name 'flatten_current_exceedances'`

- [ ] **Step 3: Append two functions to `autogis/core/envmon/dashboard_data_mart.py`**

```python
# ── append to dashboard_data_mart.py ────────────────────────────────────────

def flatten_current_exceedances(
    site_id: str,
    event_id: str,
    results: list[dict],
) -> list[DashCurrentExceedances]:
    """One DashCurrentExceedances row per result where ``is_exceedance`` is truthy.

    Args:
        site_id: Site identifier.
        event_id: Event identifier (used to populate dataclass field only;
            caller is expected to pass event-filtered results).
        results: Analytical result dicts. Each must have keys:
            ``location_id``, ``analyte``, ``result`` (Optional[float]),
            ``units``, ``is_exceedance`` (bool/int), ``screening_level``
            (Optional[float]), ``screening_source`` (str).
    """
    out: list[DashCurrentExceedances] = []
    for r in results:
        if r.get("is_exceedance"):
            out.append(DashCurrentExceedances(
                site_id=site_id,
                event_id=event_id,
                location_id=r.get("location_id", ""),
                analyte=r.get("analyte", ""),
                result=r.get("result"),
                units=r.get("units", ""),
                screening_level=r.get("screening_level"),
                screening_source=r.get("screening_source", ""),
                last_updated=_now(),
            ))
    return out


def flatten_analytical_summary(
    site_id: str,
    event_id: str,
    results: list[dict],
) -> list[DashAnalyticalSummary]:
    """One DashAnalyticalSummary row per unique (location_id, analyte) pair.

    When the same (location_id, analyte) key appears more than once (e.g.
    duplicate samples not yet resolved), the last-seen row wins.

    Args:
        site_id: Site identifier.
        event_id: Event identifier.
        results: Analytical result dicts. Each must have keys:
            ``location_id``, ``analyte``, ``result`` (Optional[float]),
            ``units``, ``is_detection`` (bool/int), ``is_exceedance``
            (bool/int).
    """
    by_key: dict[tuple[str, str], dict] = {}
    for r in results:
        key = (r.get("location_id", ""), r.get("analyte", ""))
        by_key[key] = r

    out: list[DashAnalyticalSummary] = []
    for (loc_id, analyte), r in sorted(by_key.items()):
        out.append(DashAnalyticalSummary(
            site_id=site_id,
            event_id=event_id,
            location_id=loc_id,
            analyte=analyte,
            result=r.get("result"),
            units=r.get("units", ""),
            is_detection=bool(r.get("is_detection")),
            is_exceedance=bool(r.get("is_exceedance")),
            last_updated=_now(),
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: 32 + 11 new = 43 tests PASS.

- [ ] **Step 5: Full suite smoke-check + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart — flatten_current_exceedances, flatten_analytical_summary"
```

---

### Task 4: `flatten_field_qa` + `flatten_lab_qa` + `flatten_open_issues`

**Files:**
- Modify: `autogis/core/envmon/dashboard_data_mart.py`
- Modify: `tests/envmon/test_dashboard_data_mart.py`

- [ ] **Step 1: Append the failing tests**

```python
# ── append to test file ──────────────────────────────────────────────────────
from autogis.core.envmon.dashboard_data_mart import (
    flatten_field_qa,
    flatten_lab_qa,
    flatten_open_issues,
)
from autogis.core.common.schema.dashboard import DashFieldQA, DashLabQA, DashOpenIssues

# _QA_RECORDS is already defined at top of file; a richer fixture used here:
_QA_MIXED = [
    # FIELD domain
    {"severity": "WARNING", "category": "field_duplicate_present",
     "location_id": "MW-02", "analyte": "", "description": "Field dup",
     "sample_id": "S1-002"},
    # LAB domain
    {"severity": "ERROR", "category": "orphan_result",
     "location_id": "MW-01", "analyte": "Benzene",
     "description": "No parent sample", "sample_id": "S1-001"},
    # GIS domain
    {"severity": "ERROR", "category": "table_missing",
     "location_id": "", "analyte": "", "description": "Schema table absent",
     "sample_id": ""},
    # INFO — must be excluded from all three tables
    {"severity": "INFO", "category": "validation_complete",
     "location_id": "", "analyte": "", "description": "Done", "sample_id": ""},
]


# ---------- flatten_field_qa ----------

def test_flatten_field_qa_returns_list_of_dataclasses():
    result = flatten_field_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert all(isinstance(r, DashFieldQA) for r in result)


def test_flatten_field_qa_only_field_categories():
    result = flatten_field_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert len(result) == 1
    assert result[0].issue_type == "field_duplicate_present"


def test_flatten_field_qa_excludes_info():
    result = flatten_field_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert not any(r.issue_type == "validation_complete" for r in result)


def test_flatten_field_qa_location_populated():
    result = flatten_field_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert result[0].location_id == "MW-02"


# ---------- flatten_lab_qa ----------

def test_flatten_lab_qa_returns_list_of_dataclasses():
    result = flatten_lab_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert all(isinstance(r, DashLabQA) for r in result)


def test_flatten_lab_qa_only_lab_categories():
    result = flatten_lab_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert len(result) == 1
    assert result[0].issue_type == "orphan_result"


def test_flatten_lab_qa_analyte_populated():
    result = flatten_lab_qa("SITE1", "2026-05-01", _QA_MIXED)
    assert result[0].analyte == "Benzene"


# ---------- flatten_open_issues ----------

def test_flatten_open_issues_returns_list_of_dataclasses():
    result = flatten_open_issues("SITE1", "2026-05-01", _QA_MIXED)
    assert all(isinstance(r, DashOpenIssues) for r in result)


def test_flatten_open_issues_all_non_info():
    # 3 non-INFO records (1 WARNING + 2 ERROR)
    result = flatten_open_issues("SITE1", "2026-05-01", _QA_MIXED)
    assert len(result) == 3


def test_flatten_open_issues_excludes_info():
    result = flatten_open_issues("SITE1", "2026-05-01", _QA_MIXED)
    assert not any(r.description == "Done" for r in result)


def test_flatten_open_issues_domain_routing():
    result = flatten_open_issues("SITE1", "2026-05-01", _QA_MIXED)
    domains = {r.domain for r in result}
    assert "FIELD" in domains
    assert "LAB" in domains
    assert "GIS" in domains


def test_flatten_open_issues_severity_preserved():
    result = flatten_open_issues("SITE1", "2026-05-01", _QA_MIXED)
    severities = {r.severity for r in result}
    assert "ERROR" in severities
    assert "WARNING" in severities


def test_flatten_open_issues_unknown_category_goes_to_general():
    unknown = [{"severity": "WARNING", "category": "totally_unknown_category",
                "location_id": "", "analyte": "", "description": "?",
                "sample_id": ""}]
    result = flatten_open_issues("SITE1", "2026-05-01", unknown)
    assert result[0].domain == "GENERAL"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py::test_flatten_field_qa_only_field_categories -v
```

Expected: FAIL — `ImportError: cannot import name 'flatten_field_qa'`

- [ ] **Step 3: Append three functions to `autogis/core/envmon/dashboard_data_mart.py`**

```python
# ── append to dashboard_data_mart.py ────────────────────────────────────────

def flatten_field_qa(
    site_id: str,
    event_id: str,
    qa_records: list[dict],
) -> list[DashFieldQA]:
    """One DashFieldQA row per QA record whose category is in FIELD_QA_CATEGORIES.

    INFO-severity records are always excluded. Only ERROR and WARNING are
    surfaced (per _OPEN_SEVERITIES constant).

    Args:
        site_id: Site identifier.
        event_id: Event identifier.
        qa_records: QA record dicts. Each must have keys: ``severity``,
            ``category``, ``location_id``, ``description``.
    """
    out: list[DashFieldQA] = []
    for r in qa_records:
        if r.get("severity", "").upper() not in _OPEN_SEVERITIES:
            continue
        if r.get("category", "") not in FIELD_QA_CATEGORIES:
            continue
        out.append(DashFieldQA(
            site_id=site_id,
            event_id=event_id,
            issue_type=r.get("category", ""),
            location_id=r.get("location_id", ""),
            description=r.get("description", ""),
            last_updated=_now(),
        ))
    return out


def flatten_lab_qa(
    site_id: str,
    event_id: str,
    qa_records: list[dict],
) -> list[DashLabQA]:
    """One DashLabQA row per QA record whose category is in LAB_QA_CATEGORIES.

    INFO-severity records are excluded. Analyte name is populated from
    the ``analyte`` key on the QA record (may be empty string).

    Args:
        site_id: Site identifier.
        event_id: Event identifier.
        qa_records: QA record dicts with keys: ``severity``, ``category``,
            ``location_id``, ``analyte``, ``description``.
    """
    out: list[DashLabQA] = []
    for r in qa_records:
        if r.get("severity", "").upper() not in _OPEN_SEVERITIES:
            continue
        if r.get("category", "") not in LAB_QA_CATEGORIES:
            continue
        out.append(DashLabQA(
            site_id=site_id,
            event_id=event_id,
            issue_type=r.get("category", ""),
            location_id=r.get("location_id", ""),
            analyte=r.get("analyte", ""),
            description=r.get("description", ""),
            last_updated=_now(),
        ))
    return out


def flatten_open_issues(
    site_id: str,
    event_id: str,
    qa_records: list[dict],
) -> list[DashOpenIssues]:
    """One DashOpenIssues row per non-INFO QA record (all domains).

    DashOpenIssues is a superset of field + lab + GIS issues. The ``domain``
    field is populated via ``_qa_domain()`` so the dashboard can filter.
    Unknown categories receive domain "GENERAL" — nothing is silently dropped.

    Args:
        site_id: Site identifier.
        event_id: Event identifier.
        qa_records: QA record dicts with keys: ``severity``, ``category``,
            ``description``.
    """
    out: list[DashOpenIssues] = []
    for r in qa_records:
        sev = r.get("severity", "").upper()
        if sev not in _OPEN_SEVERITIES:
            continue
        out.append(DashOpenIssues(
            site_id=site_id,
            event_id=event_id,
            domain=_qa_domain(r.get("category", "")),
            severity=sev,
            description=r.get("description", "")[:256],
            assigned_to="",
            last_updated=_now(),
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: 43 + 14 new = 57 tests PASS.

- [ ] **Step 5: Full suite smoke-check + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart — flatten_field_qa, flatten_lab_qa, flatten_open_issues (domain routing)"
```

---

### Task 5: `flatten_report_readiness` + `build_mart()` + `write_mart_json()` + GDB seams

**Files:**
- Modify: `autogis/core/envmon/dashboard_data_mart.py`
- Modify: `tests/envmon/test_dashboard_data_mart.py`

- [ ] **Step 1: Append the failing tests**

```python
# ── append to test file ──────────────────────────────────────────────────────
import json as _json
from autogis.core.envmon.dashboard_data_mart import (
    flatten_report_readiness,
    build_mart,
    write_mart_json,
    DashboardMart,
)
from autogis.core.common.schema.dashboard import DashReportReadiness


# ---------- flatten_report_readiness ----------

def test_flatten_report_readiness_returns_dataclass():
    result = flatten_report_readiness("SITE1", "2026-05-01", _QA_RECORDS)
    assert isinstance(result, DashReportReadiness)


def test_flatten_report_readiness_qa_ready_when_no_errors():
    no_errors = [r for r in _QA_RECORDS if r["severity"] != "ERROR"]
    result = flatten_report_readiness("SITE1", "2026-05-01", no_errors)
    assert result.qa_ready is True


def test_flatten_report_readiness_qa_not_ready_with_errors():
    result = flatten_report_readiness("SITE1", "2026-05-01", _QA_RECORDS)
    assert result.qa_ready is False


def test_flatten_report_readiness_overall_true_when_all_gates_met():
    no_errors = [r for r in _QA_RECORDS if r["severity"] == "INFO"]
    result = flatten_report_readiness(
        "SITE1", "2026-05-01", no_errors,
        field_ready=True, lab_ready=True, gis_ready=True,
    )
    assert result.overall_ready is True
    assert result.report_ready is True


def test_flatten_report_readiness_false_if_one_gate_missing():
    no_errors = [r for r in _QA_RECORDS if r["severity"] == "INFO"]
    result = flatten_report_readiness(
        "SITE1", "2026-05-01", no_errors,
        field_ready=True, lab_ready=False, gis_ready=True,  # lab_ready=False
    )
    assert result.overall_ready is False


def test_flatten_report_readiness_false_if_qa_errors():
    result = flatten_report_readiness(
        "SITE1", "2026-05-01", _QA_RECORDS,
        field_ready=True, lab_ready=True, gis_ready=True,
    )
    # QA has an ERROR → qa_ready=False → overall_ready=False
    assert result.overall_ready is False


# ---------- build_mart ----------

def test_build_mart_returns_dashboard_mart():
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS, prior_water_levels=_PRIOR_WL,
        qa_records=_QA_RECORDS,
    )
    assert isinstance(mart, DashboardMart)


def test_build_mart_exceedances_populated():
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    assert len(mart.current_exceedances) == 1


def test_build_mart_event_status_report_ready_reflects_readiness():
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS, qa_records=[],
        field_ready=True, lab_ready=True, gis_ready=True,
    )
    assert mart.event_status.report_ready is True
    assert mart.report_readiness.overall_ready is True


def test_build_mart_event_status_report_not_ready_when_errors():
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS, qa_records=_QA_RECORDS,
        field_ready=True, lab_ready=True, gis_ready=True,
    )
    # QA has ERROR → report_ready=False
    assert mart.event_status.report_ready is False


def test_build_mart_built_at_is_string():
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    assert isinstance(mart.built_at, str) and mart.built_at


# ---------- write_mart_json ----------

def test_write_mart_json_creates_10_files(tmp_path):
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    written = write_mart_json(mart, tmp_path)
    assert len(written) == 10
    for path in written.values():
        assert path.exists()


def test_write_mart_json_filenames_match_table_names(tmp_path):
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    written = write_mart_json(mart, tmp_path)
    names = {p.name for p in written.values()}
    assert "Dash_SiteStatus.json" in names
    assert "Dash_AnalyticalSummary.json" in names
    assert "Dash_ReportReadiness.json" in names


def test_write_mart_json_files_are_valid_json_lists(tmp_path):
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    written = write_mart_json(mart, tmp_path)
    for path in written.values():
        data = _json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)


def test_write_mart_json_creates_out_dir(tmp_path):
    mart = build_mart(
        site_id="SITE1", event_id="2026-05-01",
        samples=_SAMPLES, results=_RESULTS,
        water_levels=_WATER_LEVELS,
    )
    nested = tmp_path / "does" / "not" / "exist"
    write_mart_json(mart, nested)
    assert nested.is_dir()
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py::test_build_mart_returns_dashboard_mart -v
```

Expected: FAIL — `ImportError: cannot import name 'flatten_report_readiness'`

- [ ] **Step 3: Append the remaining functions to `autogis/core/envmon/dashboard_data_mart.py`**

```python
# ── append to dashboard_data_mart.py ────────────────────────────────────────

def flatten_report_readiness(
    site_id: str,
    event_id: str,
    qa_records: list[dict],
    field_ready: bool = False,
    lab_ready: bool = False,
    gis_ready: bool = False,
    model_ready: bool = False,
) -> DashReportReadiness:
    """Compute DashReportReadiness from gate booleans + QA error scan.

    ``qa_ready`` is True when no QA record has severity "ERROR".
    ``overall_ready`` and ``report_ready`` are True iff all gates pass:
    field_ready AND lab_ready AND gis_ready AND qa_ready.
    (model_ready is recorded but does not block overall_ready.)

    Args:
        site_id: Site identifier.
        event_id: Event identifier.
        qa_records: QA record dicts. ERROR severity → qa_ready = False.
        field_ready: True if field data collection is complete.
        lab_ready: True if lab results are received.
        gis_ready: True if GIS/figure outputs are ready.
        model_ready: True if model outputs are ready (not blocking).
    """
    qa_ready = not any(
        r.get("severity", "").upper() == "ERROR" for r in qa_records
    )
    report_ready = field_ready and lab_ready and gis_ready and qa_ready
    return DashReportReadiness(
        site_id=site_id,
        event_id=event_id,
        field_ready=field_ready,
        lab_ready=lab_ready,
        gis_ready=gis_ready,
        qa_ready=qa_ready,
        model_ready=model_ready,
        report_ready=report_ready,
        overall_ready=report_ready,
        last_updated=_now(),
    )


def build_mart(
    site_id: str,
    event_id: str,
    samples: list[dict],
    results: list[dict],
    water_levels: list[dict],
    prior_water_levels: Optional[list[dict]] = None,
    qa_records: Optional[list[dict]] = None,
    site_name: str = "",
    report_due_date: Optional[str] = None,
    wells_planned: Optional[list[str]] = None,
    field_ready: bool = False,
    lab_ready: bool = False,
    gis_ready: bool = False,
    model_ready: bool = False,
) -> DashboardMart:
    """Assemble a DashboardMart from in-memory source lists.

    All arguments are plain Python (no arcpy). This is the headless core.
    ``build_dashboard_data_mart()`` wraps this with GDB I/O.

    Args:
        site_id: Site identifier.
        event_id: Event-date string "YYYY-MM-DD".
        samples: Sample dicts (all events for this site are accepted;
            functions filter internally by event_date == event_id).
        results: Analytical result dicts for this event.
        water_levels: Water-level dicts (all events); filtered internally.
        prior_water_levels: Water-level dicts for the prior event (for delta).
        qa_records: QA record dicts (all events); not filtered by event here.
        site_name: Human-readable site label.
        report_due_date: ISO date string or None.
        wells_planned: Explicit planned LocationID list; if None, defaults to
            sampled well count.
        field_ready / lab_ready / gis_ready / model_ready: Readiness gate
            booleans passed through to flatten_report_readiness.

    Returns:
        DashboardMart with all 10 Dash_* fields populated.
    """
    qa = qa_records or []
    pw = prior_water_levels or []

    readiness = flatten_report_readiness(
        site_id, event_id, qa,
        field_ready=field_ready, lab_ready=lab_ready,
        gis_ready=gis_ready, model_ready=model_ready,
    )
    event_status = flatten_event_status(
        site_id, event_id, samples, wells_planned, qa,
        lab_ready=lab_ready, figures_ready=False,
    )
    # Reflect computed report_ready into event_status
    event_status.report_ready = readiness.report_ready

    return DashboardMart(
        site_status=flatten_site_status(
            site_id, samples, qa, site_name, report_due_date
        ),
        event_status=event_status,
        well_statuses=flatten_well_status(site_id, event_id, water_levels, pw),
        gw_level_summaries=flatten_gw_level_summary(
            site_id, event_id, water_levels, pw
        ),
        analytical_summaries=flatten_analytical_summary(site_id, event_id, results),
        current_exceedances=flatten_current_exceedances(site_id, event_id, results),
        field_qa=flatten_field_qa(site_id, event_id, qa),
        lab_qa=flatten_lab_qa(site_id, event_id, qa),
        open_issues=flatten_open_issues(site_id, event_id, qa),
        report_readiness=readiness,
        built_at=_now(),
    )


def write_mart_json(mart: DashboardMart, out_dir: Path) -> dict[str, Path]:
    """Write one JSON file per Dash_* table into out_dir.

    Returns:
        Dict mapping table_name → Path for each file written.
        Example: {"Dash_SiteStatus": Path(".../Dash_SiteStatus.json"), ...}
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    d = mart.to_dict()
    table_map: dict[str, list] = {
        "Dash_SiteStatus":         [d["site_status"]],
        "Dash_EventStatus":        [d["event_status"]],
        "Dash_WellStatus":         d["well_statuses"],
        "Dash_GWLevelSummary":     d["gw_level_summaries"],
        "Dash_AnalyticalSummary":  d["analytical_summaries"],
        "Dash_CurrentExceedances": d["current_exceedances"],
        "Dash_FieldQA":            d["field_qa"],
        "Dash_LabQA":              d["lab_qa"],
        "Dash_OpenIssues":         d["open_issues"],
        "Dash_ReportReadiness":    [d["report_readiness"]],
    }
    written: dict[str, Path] = {}
    for table_name, rows in table_map.items():
        p = out_dir / f"{table_name}.json"
        p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        written[table_name] = p
    return written


# ---------------------------------------------------------------------------
# GDB seams — LOCAL only (ArcGIS Pro); # pragma: no cover
# ---------------------------------------------------------------------------

def read_source_from_gdb(  # pragma: no cover
    gdb: Path,
    site_id: str,
    event_id: str,
    prior_event_id: Optional[str] = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Read Env_* source tables from GDB for one site/event.

    Returns:
        (samples, results, water_levels, prior_water_levels, qa_records)
        Each element is a list[dict] with snake_case keys matching the
        flatten_* function input contracts.
    Requires arcpy (ArcGIS Pro LOCAL runtime).
    """
    import arcpy
    from pathlib import Path as _P

    gdb_str = str(gdb)

    def _read(table: str, where: str) -> list[dict]:
        path = str(_P(gdb_str) / table)
        if not arcpy.Exists(path):
            return []
        fields = [f.name for f in arcpy.ListFields(path)
                  if f.type not in ("OID", "Geometry")]
        rows = []
        with arcpy.da.SearchCursor(path, fields, where_clause=where) as cur:
            for row in cur:
                rows.append(dict(zip(fields, row)))
        return rows

    site_event_where = f"SiteID = '{site_id}' AND EventDate = '{event_id}'"
    site_where = f"SiteID = '{site_id}'"
    prior_where = (
        f"SiteID = '{site_id}' AND EventDate = '{prior_event_id}'"
        if prior_event_id else site_where
    )

    raw_samples = _read("Env_Samples", site_event_where)
    raw_results = _read("Env_AnalyticalResults", site_event_where)
    raw_wl = _read("Env_WaterLevels", site_event_where)
    raw_prior_wl = _read("Env_WaterLevels", prior_where) if prior_event_id else []
    raw_qa = _read("Env_ImportQA", site_where)

    # Translate GDB field names → flatten_* input contract (snake_case).
    def _xform_sample(r: dict) -> dict:
        return {
            "site_id": r.get("SiteID", ""),
            "event_date": str(r.get("SampleDate") or r.get("EventDate") or "")[:10],
            "location_id": r.get("LocationID", ""),
            "matrix": r.get("Matrix", ""),
            "sample_id": r.get("SampleID", ""),
        }

    def _xform_result(r: dict) -> dict:
        return {
            "site_id": r.get("SiteID", ""),
            "event_date": str(r.get("SampleDate") or "")[:10],
            "location_id": r.get("LocationID", ""),
            "sample_id": r.get("SampleID", ""),
            "sample_date": str(r.get("SampleDate") or "")[:10],
            "analyte": r.get("AnalyteCanonicalName", "") or r.get("AnalyteName", ""),
            "result": r.get("ResultNumeric"),
            "units": r.get("Units", ""),
            "is_detection": bool(r.get("IsDetected")),
            "is_nondetect": bool(r.get("IsNonDetect")),
            "is_exceedance": bool(r.get("ExceedsScreeningLevel")),
            "screening_level": r.get("ScreeningLevel"),
            "screening_source": r.get("ScreeningLevelSource", ""),
        }

    def _xform_wl(r: dict) -> dict:
        return {
            "site_id": r.get("SiteID", ""),
            "event_date": str(r.get("EventDate") or "")[:10],
            "location_id": r.get("LocationID", ""),
            "gwe_ft": r.get("GroundwaterElevation_ft"),
            "dtw_ft": r.get("DepthToWater_ft"),
            "measurement_status": r.get("MeasurementStatus", ""),
            "use_for_contour": bool(r.get("UseForContour")),
        }

    def _xform_qa(r: dict) -> dict:
        return {
            "severity": r.get("Severity", ""),
            "category": r.get("Category", ""),
            "location_id": r.get("LocationID", ""),
            "analyte": r.get("AnalyteName", ""),
            "description": r.get("Message", ""),
            "sample_id": r.get("SampleID", ""),
        }

    return (
        [_xform_sample(r) for r in raw_samples],
        [_xform_result(r) for r in raw_results],
        [_xform_wl(r) for r in raw_wl],
        [_xform_wl(r) for r in raw_prior_wl],
        [_xform_qa(r) for r in raw_qa],
    )


def write_mart_to_gdb(mart: DashboardMart, gdb: Path) -> None:  # pragma: no cover
    """Truncate-and-reload all 10 Dash_* GDB tables from a DashboardMart.

    Delete-then-insert strategy: removes existing rows for the mart's
    site_id/event_id before inserting new ones. Site-level table
    (Dash_SiteStatus) is keyed on site_id only.

    Requires arcpy (ArcGIS Pro LOCAL runtime).
    """
    import arcpy
    from pathlib import Path as _P

    gdb_str = str(gdb)
    site_id = mart.site_status.site_id
    event_id = mart.event_status.event_id
    d = mart.to_dict()

    def _clear(table: str, where: str) -> None:
        path = str(_P(gdb_str) / table)
        if arcpy.Exists(path):
            with arcpy.da.UpdateCursor(path, ["OID@"],
                                        where_clause=where) as cur:
                for _ in cur:
                    cur.deleteRow()

    def _insert(table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        path = str(_P(gdb_str) / table)
        if not arcpy.Exists(path):
            return 0
        fields = list(rows[0].keys())
        with arcpy.da.InsertCursor(path, fields) as cur:
            for row in rows:
                cur.insertRow([row[f] for f in fields])
        return len(rows)

    site_ev_where = f"site_id = '{site_id}' AND event_id = '{event_id}'"
    site_where = f"site_id = '{site_id}'"

    _clear("Dash_SiteStatus", site_where)
    _insert("Dash_SiteStatus", [d["site_status"]])

    for table, rows in [
        ("Dash_EventStatus",        [d["event_status"]]),
        ("Dash_WellStatus",         d["well_statuses"]),
        ("Dash_GWLevelSummary",     d["gw_level_summaries"]),
        ("Dash_AnalyticalSummary",  d["analytical_summaries"]),
        ("Dash_CurrentExceedances", d["current_exceedances"]),
        ("Dash_FieldQA",            d["field_qa"]),
        ("Dash_LabQA",              d["lab_qa"]),
        ("Dash_OpenIssues",         d["open_issues"]),
        ("Dash_ReportReadiness",    [d["report_readiness"]]),
    ]:
        _clear(table, site_ev_where)
        _insert(table, rows)


def build_dashboard_data_mart(  # pragma: no cover
    gdb: Path,
    site_id: str,
    event_id: str,
    prior_event_id: Optional[str] = None,
    site_name: str = "",
    wells_planned: Optional[list[str]] = None,
    field_ready: bool = False,
    lab_ready: bool = False,
    gis_ready: bool = False,
    model_ready: bool = False,
) -> DashboardMart:
    """Read Env_* source data from GDB, build mart, write Dash_* tables back.

    Full LOCAL orchestrator (arcpy required). For headless use, call
    ``build_mart()`` directly and ``write_mart_json()`` for output.

    Args:
        gdb: Path to the file geodatabase.
        site_id: Site identifier.
        event_id: Event-date string "YYYY-MM-DD".
        prior_event_id: Prior event date for GW delta/trend; None to skip.
        site_name / wells_planned / field_ready / lab_ready / gis_ready /
        model_ready: Passed through to build_mart().

    Returns:
        Populated DashboardMart (also written back to GDB Dash_* tables).
    """
    samples, results, wl, prior_wl, qa = read_source_from_gdb(
        gdb, site_id, event_id, prior_event_id
    )
    mart = build_mart(
        site_id=site_id, event_id=event_id,
        samples=samples, results=results,
        water_levels=wl, prior_water_levels=prior_wl,
        qa_records=qa, site_name=site_name,
        wells_planned=wells_planned,
        field_ready=field_ready, lab_ready=lab_ready,
        gis_ready=gis_ready, model_ready=model_ready,
    )
    write_mart_to_gdb(mart, gdb)
    return mart
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: 57 + 18 new = 75 tests PASS.

- [ ] **Step 5: Full suite smoke-check + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/dashboard_data_mart.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(envmon): dashboard_data_mart — build_mart, write_mart_json, GDB read/write seams (# pragma: no cover)"
```

---

### Task 6: CLI command `build-dashboard-mart`

**Files:**
- Modify: `autogis/adapters/cli.py` (append command after existing envmon commands)
- Modify: `tests/envmon/test_dashboard_data_mart.py` (append CLI tests)

- [ ] **Step 1: Append CLI tests**

```python
# ── append to test file ──────────────────────────────────────────────────────
import json as _json
from pathlib import Path as _Path
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_build_dashboard_mart_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-dashboard-mart" in result.output


def test_build_dashboard_mart_cmd_headless(tmp_path):
    samples_f = tmp_path / "samples.json"
    samples_f.write_text(_json.dumps(_SAMPLES), encoding="utf-8")
    results_f = tmp_path / "results.json"
    results_f.write_text(_json.dumps(_RESULTS), encoding="utf-8")
    wl_f = tmp_path / "wl.json"
    wl_f.write_text(_json.dumps(_WATER_LEVELS), encoding="utf-8")
    out_dir = tmp_path / "mart"

    result = CliRunner().invoke(autogis, [
        "envmon", "build-dashboard-mart",
        "--site", "SITE1",
        "--event", "2026-05-01",
        "--samples", str(samples_f),
        "--results", str(results_f),
        "--water-levels", str(wl_f),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output
    assert (out_dir / "Dash_SiteStatus.json").exists()
    assert (out_dir / "Dash_AnalyticalSummary.json").exists()
    assert (out_dir / "Dash_ReportReadiness.json").exists()


def test_build_dashboard_mart_cmd_with_prior_wl(tmp_path):
    samples_f = tmp_path / "samples.json"
    samples_f.write_text(_json.dumps(_SAMPLES), encoding="utf-8")
    results_f = tmp_path / "results.json"
    results_f.write_text(_json.dumps(_RESULTS), encoding="utf-8")
    wl_f = tmp_path / "wl.json"
    wl_f.write_text(_json.dumps(_WATER_LEVELS), encoding="utf-8")
    prior_f = tmp_path / "prior_wl.json"
    prior_f.write_text(_json.dumps(_PRIOR_WL), encoding="utf-8")
    out_dir = tmp_path / "mart"

    result = CliRunner().invoke(autogis, [
        "envmon", "build-dashboard-mart",
        "--site", "SITE1",
        "--event", "2026-05-01",
        "--samples", str(samples_f),
        "--results", str(results_f),
        "--water-levels", str(wl_f),
        "--prior-water-levels", str(prior_f),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output
    gw_data = _json.loads((out_dir / "Dash_GWLevelSummary.json").read_text())
    # With prior data, MW-01 delta should be present and non-null
    mw01 = next(r for r in gw_data if r["location_id"] == "MW-01")
    assert mw01["delta_ft"] is not None


def test_build_dashboard_mart_cmd_summary_in_stdout(tmp_path):
    samples_f = tmp_path / "samples.json"
    samples_f.write_text(_json.dumps(_SAMPLES), encoding="utf-8")
    results_f = tmp_path / "results.json"
    results_f.write_text(_json.dumps(_RESULTS), encoding="utf-8")
    wl_f = tmp_path / "wl.json"
    wl_f.write_text(_json.dumps(_WATER_LEVELS), encoding="utf-8")
    out_dir = tmp_path / "mart"

    result = CliRunner().invoke(autogis, [
        "envmon", "build-dashboard-mart",
        "--site", "SITE1", "--event", "2026-05-01",
        "--samples", str(samples_f), "--results", str(results_f),
        "--water-levels", str(wl_f), "--out-dir", str(out_dir),
    ])
    assert "analytical" in result.output.lower() or "mart" in result.output.lower()
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py::test_build_dashboard_mart_in_envmon_help -v
```

Expected: FAIL — `AssertionError: 'build-dashboard-mart' not in output`

- [ ] **Step 3: Append command to `autogis/adapters/cli.py`**

After the last `@envmon.command(...)` definition (before any module-level imports at the bottom), add:

```python
@envmon.command("build-dashboard-mart")
@click.option("--site", "site_id", required=True,
              help="Site ID.")
@click.option("--event", "event_id", required=True,
              help="Event ID (event date string, e.g. '2026-05-01').")
@click.option("--samples", "samples_path", required=True,
              type=click.Path(exists=True),
              help="JSON file: list of sample dicts (snake_case keys).")
@click.option("--results", "results_path", required=True,
              type=click.Path(exists=True),
              help="JSON file: list of analytical result dicts.")
@click.option("--water-levels", "wl_path", required=True,
              type=click.Path(exists=True),
              help="JSON file: list of water-level dicts for this event.")
@click.option("--prior-water-levels", "prior_wl_path", default=None,
              type=click.Path(exists=True),
              help="JSON file: water-level dicts for prior event (delta/trend).")
@click.option("--qa", "qa_path", default=None,
              type=click.Path(exists=True),
              help="JSON file: list of QA record dicts.")
@click.option("--out-dir", "out_dir", required=True,
              type=click.Path(),
              help="Output directory for Dash_*.json files.")
@click.option("--site-name", "site_name", default="",
              help="Human-readable site label.")
@click.option("--field-ready/--no-field-ready", default=False,
              help="Field data collection complete.")
@click.option("--lab-ready/--no-lab-ready", default=False,
              help="Lab results received.")
@click.option("--gis-ready/--no-gis-ready", default=False,
              help="GIS / figure outputs ready.")
@click.option("--gdb", "gdb_path", default=None,
              type=click.Path(),
              help="Write Dash_* tables back to this GDB (requires ArcGIS Pro).")
def build_dashboard_mart_cmd(
    site_id, event_id, samples_path, results_path, wl_path, prior_wl_path,
    qa_path, out_dir, site_name, field_ready, lab_ready, gis_ready, gdb_path,
):
    """Build flattened dashboard data mart (Dash_* tables) — fully headless.

    Reads source data from JSON files, runs the 10 flatten transforms, and
    writes one Dash_*.json per table to --out-dir.  Use --gdb to also write
    results back into an ArcGIS Pro geodatabase (requires LOCAL runtime).
    """
    import json as _json
    from autogis.core.envmon.dashboard_data_mart import (
        build_mart, write_mart_json,
    )

    samples = _json.loads(Path(samples_path).read_text(encoding="utf-8"))
    results = _json.loads(Path(results_path).read_text(encoding="utf-8"))
    wl = _json.loads(Path(wl_path).read_text(encoding="utf-8"))
    prior_wl = (
        _json.loads(Path(prior_wl_path).read_text(encoding="utf-8"))
        if prior_wl_path else None
    )
    qa = (
        _json.loads(Path(qa_path).read_text(encoding="utf-8"))
        if qa_path else None
    )

    mart = build_mart(
        site_id=site_id,
        event_id=event_id,
        samples=samples,
        results=results,
        water_levels=wl,
        prior_water_levels=prior_wl,
        qa_records=qa,
        site_name=site_name,
        field_ready=field_ready,
        lab_ready=lab_ready,
        gis_ready=gis_ready,
    )

    written = write_mart_json(mart, Path(out_dir))
    click.echo(
        f"Dashboard mart built: {len(mart.analytical_summaries)} analytical summaries, "
        f"{len(mart.current_exceedances)} exceedances, "
        f"{len(mart.well_statuses)} wells → {out_dir}"
    )
    click.echo(f"  Tables written: {', '.join(written)}")

    if gdb_path:
        _guard("build-dashboard-mart")
        from autogis.core.envmon.dashboard_data_mart import write_mart_to_gdb
        write_mart_to_gdb(mart, Path(gdb_path))
        click.echo(f"  Dash_* tables written to GDB: {gdb_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_dashboard_data_mart.py -v
```

Expected: 75 + 4 new = 79 tests PASS.

- [ ] **Step 5: Full suite + commit**

```bash
python -m pytest -q
git add autogis/adapters/cli.py tests/envmon/test_dashboard_data_mart.py
git commit -m "feat(cli): add build-dashboard-mart command (headless JSON + optional LOCAL GDB write)"
```

---

## Self-Review

### Spec coverage check

| Requirement | Task covering it |
|---|---|
| Flatten raw analytical/water-level tables into Dash_* | Tasks 2–4 |
| All 10 Dash_* dataclasses populated | Task 5 (`build_mart`) |
| Headless (no arcpy/arcgis in core) | All tasks — invariant held |
| TDD (tests first) | Every task: Step 1 → Step 2 → Step 3 |
| GDB write seam for production | Task 5 (`write_mart_to_gdb`, `# pragma: no cover`) |
| CLI surface | Task 6 |
| Headless CLI mode (JSON in/JSON out) | Task 6 (default, no `--gdb`) |
| Optional LOCAL GDB write from CLI | Task 6 (`--gdb` flag + `_guard`) |
| Scope boundary: data mart build only; publishing is 6.8 | Not-done: no arcgis / AGOL publish code anywhere |

### Placeholder scan

No TBD, TODO, "fill in later", or "similar to Task N" patterns present. Every step contains runnable code.

### Type consistency check

- `flatten_site_status` → `DashSiteStatus` ✓ (imported from schema.dashboard)
- `flatten_event_status` → `DashEventStatus` ✓ (event_status.report_ready mutated by build_mart)
- `flatten_well_status` → `list[DashWellStatus]` ✓
- `flatten_gw_level_summary` → `list[DashGWLevelSummary]` ✓
- `flatten_current_exceedances` → `list[DashCurrentExceedances]` ✓
- `flatten_analytical_summary` → `list[DashAnalyticalSummary]` ✓
- `flatten_field_qa` → `list[DashFieldQA]` ✓
- `flatten_lab_qa` → `list[DashLabQA]` ✓
- `flatten_open_issues` → `list[DashOpenIssues]` ✓
- `flatten_report_readiness` → `DashReportReadiness` ✓
- `build_mart` → `DashboardMart` ✓ (contains all 10 above)
- `write_mart_json(mart, out_dir)` returns `dict[str, Path]` ✓ (used in CLI tests)
- `_QA_MIXED` fixture used in Task 4 — `field_duplicate_present` is in `FIELD_QA_CATEGORIES` ✓, `orphan_result` in `LAB_QA_CATEGORIES` ✓, `table_missing` in `GIS_QA_CATEGORIES` ✓
- `_RESULTS`, `_WATER_LEVELS`, `_PRIOR_WL` defined in Task 3 / Task 2 respectively — referenced in Task 5 and Task 6 tests, which append to the same file. The fixtures remain in scope. ✓

### Risks

1. **GDB field name mismatch** — `read_source_from_gdb` translates GDB field names (PascalCase) to snake_case. If the actual schema uses different names (e.g., `EventDate` vs `SampleDate`), the transform will silently produce empty strings. Mitigation: verify against `autogis/core/envmon/gdb_schema.py` `TABLE_SCHEMAS` before first LOCAL run; add a schema-check assertion or log.

2. **`event_id` = event_date assumption** — the Dash_* tables store `event_id` as a free string. If the project later introduces a separate event table, `event_id` values will diverge. Noted in module docstring; low risk for current sprint.

3. **QA category frozensets are additive stubs** — new `qa.add(...category=...)` calls added in future modules will initially fall through to domain `"GENERAL"`. This is correct behaviour (nothing dropped), but `DashFieldQA` / `DashLabQA` will miss new categories until the frozensets are updated. Pattern: update `FIELD_QA_CATEGORIES` / `LAB_QA_CATEGORIES` when a new QA module is added.

4. **`write_mart_to_gdb` field name alignment** — the `to_dict()` output uses snake_case keys; the GDB Dash_* tables use those same names if created by `upgrade_schema`. If the GDB was created with PascalCase field names, `InsertCursor` will fail silently or raise. Mitigation: run `upgrade-schema` before first LOCAL use to ensure Dash_* tables are present with the expected field names.
