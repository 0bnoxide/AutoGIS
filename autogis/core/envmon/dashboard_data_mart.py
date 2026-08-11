"""dashboard_data_mart.py — Tool 6.7 BuildDashboardDataMart.

Populate the pre-flattened ``Dash_*`` tables (one row per site/event/well) that
back AGOL dashboards, so the dashboard never has to join 5+ tables client-side.

The transformation layer (``build_dash_*`` functions) is pure Python and
arcpy-free — it maps source-table rows (as dicts) to ``Dash_*``-schema rows.
The orchestrator ``build_dashboard_data_mart`` reads/truncates/repopulates the
GDB and imports arcpy lazily (``# pragma: no cover``).

Output dict keys follow the ``Dash_*`` schemas in ``gdb_schema.py``.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..common.logging import get_logger
from ..common.qa import QACollector
from .canonical_read import canonical_result_rows

LOG = get_logger(__name__)

_RISING_THRESHOLD = 0.1   # ft


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class MartSummary:
    site_id: str
    event_id: str
    built_at: str
    tables_updated: List[str] = field(default_factory=list)
    row_counts: Dict[str, int] = field(default_factory=dict)


def export_dashboard_json(
    tables: Dict[str, List[dict]],
    export_dir: str | Path,
) -> List[Path]:
    """Write refresh-dashboard JSON with atomic per-file replacement."""
    output_dir = Path(export_dir)
    payloads = []
    for table in sorted(tables):
        if not table.startswith("Dash_") or not table.isidentifier():
            raise ValueError(f"Invalid dashboard table name: {table!r}")
        target = output_dir / f"{table}.json"
        text = json.dumps(
            tables[table], indent=2, sort_keys=True, ensure_ascii=False,
            allow_nan=False,
        ) + "\n"
        payloads.append((target, text.encode("utf-8")))

    expected_names = {target.name for target, _payload in payloads}
    stale = sorted(
        path.name for path in output_dir.glob("Dash_*.json")
        if path.name not in expected_names
    ) if output_dir.exists() else []
    if stale:
        raise ValueError(
            "Unexpected dashboard JSON file(s) in export directory: "
            + ", ".join(stale))

    output_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for target, payload in payloads:
            tmp = target.with_name(target.name + ".tmp")
            staged.append((tmp, target))
            tmp.write_bytes(payload)
        for tmp, target in staged:
            os.replace(tmp, target)
    except BaseException:
        for tmp, _target in staged:
            tmp.unlink(missing_ok=True)
        raise
    return [target for target, _payload in payloads]


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _event_date_str(v) -> str:
    """Normalize an EventDate (date/datetime/str) to an ISO 'YYYY-MM-DD' string."""
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.strftime("%Y-%m-%d")
    return str(v or "")


def _row_gwe(row: dict):
    """Groundwater elevation off a water-level row, under either table's name.

    ``Env_WaterLevels`` stores ``GroundwaterElevation_ft``;
    ``Env_CurrentWaterLevelEvent`` stores ``GWE_ft`` (#466). ``""`` counts as
    absent, not as a value.
    """
    v = row.get("GroundwaterElevation_ft")
    if v in (None, ""):
        v = row.get("GWE_ft")
    return v


def select_prior_water_levels(
    all_water_levels: List[dict],
    current_water_levels: List[dict],
    prior_event_id: Optional[str] = None,
) -> List[dict]:
    """Pick the *prior* water-level row per LocationID from a multi-event table.

    For each well, return the measurement with the latest ``EventDate`` strictly
    *before* that well's current event date — not whichever row happens to come
    last in cursor order. When ``prior_event_id`` is an explicit ISO date
    (``YYYY-MM-DD``), candidates are restricted to that date instead.

    Pure / arcpy-free so the orchestrator's prior-selection is unit-testable.
    """
    explicit = bool(prior_event_id) and len(str(prior_event_id)) == 10 \
        and str(prior_event_id)[4] == "-"
    current_date = {r.get("LocationID", ""): _event_date_str(r.get("EventDate"))
                    for r in current_water_levels}
    by_loc: Dict[str, dict] = {}
    skipped: Dict[str, str] = {}
    for r in all_water_levels:
        if _num(_row_gwe(r)) is None:
            # A row with no USABLE elevation cannot produce a delta, and taking
            # it as "the prior" hides the last row that could. Reachable since
            # #464 gave Survey123 water levels a real EventDate: those rows
            # carry a DTW but no TOC, so they out-date the workbook row and
            # collapsed every Delta_ft to NULL and every Trend to "Unknown" --
            # the exact symptom #466 fixed, re-entering by a different door.
            # Tested with _num, not `in (None, "")`: "N/A"/"ND"/"   " are
            # present but unusable, and the presence test let them through --
            # and _prior_gwe_by_location already funnels through _num, so the
            # two seams would disagree about what counts as an elevation.
            sk = r.get("LocationID", "")
            ed_sk = _event_date_str(r.get("EventDate"))
            if ed_sk > skipped.get(sk, ""):
                skipped[sk] = ed_sk
            continue
        loc = r.get("LocationID", "")
        ed = _event_date_str(r.get("EventDate"))
        if explicit:
            if ed != str(prior_event_id):
                continue
        else:
            cur = current_date.get(loc)
            if cur is not None and not (ed and ed < cur):
                continue  # keep only measurements strictly before the current one
        prev = by_loc.get(loc)
        if prev is None or ed > _event_date_str(prev.get("EventDate")):
            by_loc[loc] = r
    # The delta can now span a different pair of events than the two most
    # recent, and the Dash_* schema has no prior-date column to show it. Say so
    # rather than letting the span change silently between runs -- same
    # disclosure channel the orchestrator uses for its canonical-read drops.
    for sk, ed_sk in sorted(skipped.items()):
        chosen = by_loc.get(sk)
        if chosen is not None and ed_sk > _event_date_str(
                chosen.get("EventDate")):
            LOG.info("[prior-water-level] %s: skipped a newer %s reading with "
                     "no usable elevation; delta is against %s instead.",
                     sk, ed_sk, _event_date_str(chosen.get("EventDate")))
    return list(by_loc.values())


# ---------------------------------------------------------------------------
# Pure-Python transformation functions (arcpy-free, unit-tested)
# ---------------------------------------------------------------------------
def build_dash_site_status(wide_rows: List[dict], qa_errors: List[dict],
                           site_id: str, event_id: str,
                           site_name: str = "") -> List[dict]:
    """Dash_SiteStatus at site grain; ``event_id`` is intentionally unstamped."""
    _ = event_id  # Dash_SiteStatus has no EventID column.
    return [{
        "SiteID": site_id, "SiteName": site_name,
        "ActiveEvents": len(wide_rows),
        "OpenQAIssues": len(qa_errors),
        "ReportDueDate": None, "LastUpdated": _now(),
    }]


def build_dash_event_status(samples: List[dict], results: List[dict],
                            site_id: str, event_id: str,
                            wells_planned: Optional[int] = None) -> List[dict]:
    """Dash_EventStatus ← Env_Samples + Env_AnalyticalResults (one row).

    LabReceived is True only when every sampled well has at least one result.
    """
    sampled = {s.get("LocationID", "") for s in samples if s.get("LocationID")}
    with_results = {r.get("LocationID", "") for r in results if r.get("LocationID")}
    lab_received = bool(sampled) and sampled.issubset(with_results)
    return [{
        "SiteID": site_id, "EventID": event_id,
        "WellsPlanned": wells_planned if wells_planned is not None else len(sampled),
        "WellsSampled": len(sampled),
        "LabReceived": int(lab_received),
        "FiguresReady": 0, "ReportReady": 0, "LastUpdated": _now(),
    }]


def _prior_gwe_by_location(
    prior_water_level_events: List[dict],
) -> Dict[str, Optional[float]]:
    """Map LocationID -> prior groundwater elevation, accepting either name.

    The two source tables spell the same quantity differently:
    ``Env_WaterLevels`` (where prior rows come from, via
    :func:`select_prior_water_levels`) stores ``GroundwaterElevation_ft``,
    while ``Env_CurrentWaterLevelEvent`` stores ``GWE_ft``. Reading only the
    latter made every prior lookup ``None`` — so ``Delta_ft`` was always NULL
    and ``Trend`` always "Unknown" on the delivered dashboard (#466).
    Resolved here, once, rather than at each consumer.
    """
    return {p.get("LocationID", ""): _num(_row_gwe(p))
            for p in prior_water_level_events}


def build_dash_well_status(water_level_events: List[dict],
                           prior_water_level_events: List[dict],
                           site_id: str, event_id: str) -> List[dict]:
    """Dash_WellStatus ← Env_CurrentWaterLevelEvent (+ prior for delta)."""
    prior = _prior_gwe_by_location(prior_water_level_events)
    out = []
    for e in water_level_events:
        loc = e.get("LocationID", "")
        gwe = _num(e.get("GWE_ft"))
        pgwe = prior.get(loc)
        delta = (gwe - pgwe) if (gwe is not None and pgwe is not None) else None
        out.append({
            "SiteID": site_id, "EventID": event_id, "LocationID": loc,
            "Status": e.get("Status", ""), "GWE_ft": gwe,
            "GWEDelta_ft": delta, "LastUpdated": _now(),
        })
    return out


def _trend(delta: Optional[float]) -> str:
    if delta is None:
        return "Unknown"
    if delta > _RISING_THRESHOLD:
        return "Rising"
    if delta < -_RISING_THRESHOLD:
        return "Falling"
    return "Stable"


def build_dash_gw_level_summary(water_level_events: List[dict],
                                prior_water_level_events: List[dict],
                                site_id: str, event_id: str) -> List[dict]:
    """Dash_GWLevelSummary ← two-event water-level join with trend."""
    prior = _prior_gwe_by_location(prior_water_level_events)
    out = []
    for e in water_level_events:
        loc = e.get("LocationID", "")
        gwe = _num(e.get("GWE_ft"))
        pgwe = prior.get(loc)
        delta = (gwe - pgwe) if (gwe is not None and pgwe is not None) else None
        out.append({
            "SiteID": site_id, "EventID": event_id, "LocationID": loc,
            "GWE_ft": gwe, "PriorGWE_ft": pgwe, "Delta_ft": delta,
            "Trend": _trend(delta), "LastUpdated": _now(),
        })
    return out


def _analyte(r: dict) -> str:
    return r.get("AnalyteName") or r.get("AnalyteCanonicalName") or ""


def build_dash_current_exceedances(results: List[dict], site_id: str,
                                   event_id: str) -> List[dict]:
    """Dash_CurrentExceedances ← Env_AnalyticalResults WHERE ExceedsScreeningLevel=1."""
    out = []
    for r in results:
        if int(r.get("ExceedsScreeningLevel", 0) or 0) != 1:
            continue
        out.append({
            "SiteID": site_id, "EventID": event_id,
            "LocationID": r.get("LocationID", ""), "Analyte": _analyte(r),
            "Result": _num(r.get("ResultNumeric")), "Units": r.get("Units", ""),
            "ScreeningLevel": _num(r.get("ScreeningLevel")),
            "ScreeningSource": r.get("ScreeningLevelSource", ""),
            "LastUpdated": _now(),
        })
    return out


def build_dash_analytical_summary(results: List[dict], site_id: str,
                                  event_id: str) -> List[dict]:
    """Dash_AnalyticalSummary ← Env_AnalyticalResults (one row per result)."""
    out = []
    for r in results:
        out.append({
            "SiteID": site_id, "EventID": event_id,
            "LocationID": r.get("LocationID", ""), "Analyte": _analyte(r),
            "Result": _num(r.get("ResultNumeric")), "Units": r.get("Units", ""),
            "IsDetection": int(r.get("IsDetected", 0) or 0),
            "IsExceedance": int(r.get("ExceedsScreeningLevel", 0) or 0),
            "LastUpdated": _now(),
        })
    return out


def _has_analyte(r: dict) -> bool:
    return bool((r.get("AnalyteName") or "").strip())


def build_dash_field_qa(qa_rows: List[dict], site_id: str,
                        event_id: str) -> List[dict]:
    """Dash_FieldQA ← Env_ImportQA WHERE AnalyteName IS NULL/blank."""
    out = []
    for r in qa_rows:
        if _has_analyte(r):
            continue
        out.append({
            "SiteID": site_id, "EventID": event_id,
            "IssueType": r.get("Category", ""),
            "LocationID": r.get("LocationID", ""),
            "Description": r.get("Message", ""), "LastUpdated": _now(),
        })
    return out


def build_dash_lab_qa(qa_rows: List[dict], site_id: str,
                      event_id: str) -> List[dict]:
    """Dash_LabQA ← Env_ImportQA WHERE AnalyteName IS NOT NULL."""
    out = []
    for r in qa_rows:
        if not _has_analyte(r):
            continue
        out.append({
            "SiteID": site_id, "EventID": event_id,
            "IssueType": r.get("Category", ""),
            "LocationID": r.get("LocationID", ""),
            "Analyte": r.get("AnalyteName", ""),
            "Description": r.get("Message", ""), "LastUpdated": _now(),
        })
    return out


def build_dash_open_issues(qa_rows: List[dict], site_id: str,
                           event_id: str) -> List[dict]:
    """Dash_OpenIssues ← Env_ImportQA grouped by (Domain=Category, Severity,
    Description=Message)."""
    grouped: "OrderedDict[tuple, dict]" = OrderedDict()
    for r in qa_rows:
        key = (r.get("Category", ""), r.get("Severity", ""), r.get("Message", ""))
        if key not in grouped:
            grouped[key] = {
                "SiteID": site_id, "EventID": event_id,
                "Domain": r.get("Category", ""), "Severity": r.get("Severity", ""),
                "Description": r.get("Message", ""),
                "AssignedTo": r.get("AssignedTo", ""), "LastUpdated": _now(),
            }
    return list(grouped.values())


def build_dash_report_readiness(samples: List[dict], results: List[dict],
                                site_id: str, event_id: str) -> List[dict]:
    """Dash_ReportReadiness ← Env_Samples + Env_AnalyticalResults cross-check."""
    sampled = {s.get("LocationID", "") for s in samples if s.get("LocationID")}
    with_results = {r.get("LocationID", "") for r in results if r.get("LocationID")}
    lab_ready = bool(sampled) and sampled.issubset(with_results)
    field_ready = bool(sampled)
    overall = field_ready and lab_ready
    return [{
        "SiteID": site_id, "EventID": event_id,
        "FieldReady": int(field_ready), "LabReady": int(lab_ready),
        "GISReady": 0, "QAReady": 0, "ModelReady": 0,
        "ReportReady": int(overall), "OverallReady": int(overall),
        "LastUpdated": _now(),
    }]


# ---------------------------------------------------------------------------
# LOCAL orchestrator (arcpy, lazy import)
# ---------------------------------------------------------------------------
def build_dashboard_data_mart(  # pragma: no cover - requires arcpy
    gdb_path: str,
    site_id: str,
    event_id: str,
    prior_event_id: Optional[str] = None,
    *,
    export_dir: Optional[str | Path] = None,
) -> MartSummary:
    """Read source tables, repopulate Dash_*, and optionally export their JSON."""
    from ...runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()

    def _read(table: str) -> List[dict]:
        fields = [f.name for f in arcpy.ListFields(f"{gdb_path}/{table}")]
        with arcpy.da.SearchCursor(f"{gdb_path}/{table}", fields) as cur:
            rows = [dict(zip(fields, row)) for row in cur]
        # Scope every source read to this site so a multi-site GDB does not leak
        # another site's data/QA into this site's mart.
        if "SiteID" in fields:
            rows = [r for r in rows if r.get("SiteID") == site_id]
        return rows

    wide = _read("Env_CurrentEventWide")
    qa_rows = _read("Env_ImportQA")
    qa_errors = [r for r in qa_rows if r.get("Severity") in ("ERROR", "CRITICAL")]
    samples = _read("Env_Samples")
    results = _read("Env_AnalyticalResults")
    # Canonical-read policy before the exceedance filter and the analyte-pivoting
    # Dash_* builders (ADR-0075): drop QC rows + resolve fraction pairs so the
    # mart never double-counts. No qa channel in this orchestrator, so surface
    # the drop/resolve messages via the module logger (never write-only).
    _mart_qa = QACollector()
    results = canonical_result_rows(results, _mart_qa)
    for _rec in _mart_qa.records:
        LOG.info("[canonical-read] %s", _rec.message)
    wl = _read("Env_CurrentWaterLevelEvent")
    prior_wl = (select_prior_water_levels(_read("Env_WaterLevels"), wl,
                                          prior_event_id)
                if prior_event_id else [])
    exceedances = [r for r in results
                   if int(r.get("ExceedsScreeningLevel", 0) or 0) == 1]

    builders = {
        "Dash_SiteStatus": build_dash_site_status(wide, qa_errors, site_id, event_id),
        "Dash_EventStatus": build_dash_event_status(samples, results, site_id, event_id),
        "Dash_WellStatus": build_dash_well_status(wl, prior_wl, site_id, event_id),
        "Dash_GWLevelSummary": build_dash_gw_level_summary(wl, prior_wl, site_id, event_id),
        "Dash_CurrentExceedances": build_dash_current_exceedances(exceedances, site_id, event_id),
        "Dash_AnalyticalSummary": build_dash_analytical_summary(results, site_id, event_id),
        "Dash_FieldQA": build_dash_field_qa(qa_rows, site_id, event_id),
        "Dash_LabQA": build_dash_lab_qa(qa_rows, site_id, event_id),
        "Dash_OpenIssues": build_dash_open_issues(qa_rows, site_id, event_id),
        "Dash_ReportReadiness": build_dash_report_readiness(samples, results, site_id, event_id),
    }

    summary = MartSummary(site_id=site_id, event_id=event_id, built_at=_now())
    for table, rows in builders.items():
        target = f"{gdb_path}/{table}"
        arcpy.management.TruncateTable(target)
        if rows:
            cols = list(rows[0].keys())
            with arcpy.da.InsertCursor(target, cols) as ic:
                for row in rows:
                    ic.insertRow([row[c] for c in cols])
        summary.tables_updated.append(table)
        summary.row_counts[table] = len(rows)
        LOG.info("dashboard mart: %s <- %s rows", table, len(rows))
    if export_dir is not None:
        export_dashboard_json(builders, export_dir)
    return summary
