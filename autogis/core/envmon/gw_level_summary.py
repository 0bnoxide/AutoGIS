"""Groundwater level summary from ElevationHistory.

Post-roadmap extra tool — not a numbered roadmap tool. Roadmap 5.1 is the
unrelated "Analytical Callout Builder" (BuildAnalyticalCallouts,
`envmon build-callouts`) — see issue #458.


Headless precursor to the arcpy contour tool: reads approved elevation
records and produces per-well water-level elevation, depth-to-water (DTW)
from top-of-casing, and trend vs the previous approved survey.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from typing import Dict, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ..common.schema.survey import ElevationHistory

_STABLE_FT = 0.1


@dataclasses.dataclass
class GWLevelRow:
    location_id: str
    survey_date: date
    water_level_elevation: float
    toc_elevation: Optional[float]
    depth_to_water: Optional[float]
    trend: str
    vertical_datum: str


def _trend(curr_elev: float, curr_dtw: Optional[float],
           prev_elev: float, prev_dtw: Optional[float]) -> str:
    # Prefer DTW comparison when both DTWs exist; a falling DTW means the water
    # level rose. is-not-None guards keep a legitimate 0.0 DTW from looking
    # "missing".
    if curr_dtw is not None and prev_dtw is not None:
        delta = curr_dtw - prev_dtw
        if abs(delta) < _STABLE_FT:
            return "STABLE"
        return "RISING" if delta < 0 else "DECLINING"
    # No TOC: compare elevation directly (rising elevation = rising water).
    delta = curr_elev - prev_elev
    if abs(delta) < _STABLE_FT:
        return "STABLE"
    return "RISING" if delta > 0 else "DECLINING"


def build_gw_level_summary(
    elevations: List[ElevationHistory],
    toc_elevations: Dict[str, float],
    *,
    event_date: date,
    qa: QACollector,
) -> List[GWLevelRow]:
    """Compute the per-well groundwater level summary for ``event_date``."""
    active = [e for e in elevations if e.approved_for_use and not e.superseded]

    current: Dict[str, List[ElevationHistory]] = {}
    historical: Dict[str, List[ElevationHistory]] = {}
    for e in active:
        if not str(e.location_id or "").strip():
            qa.add(SEV_WARNING, "blank_location_id",
                   "Elevation record with blank location_id skipped")
            continue
        if e.survey_date == event_date:
            current.setdefault(e.location_id, []).append(e)
        elif e.survey_date < event_date:
            historical.setdefault(e.location_id, []).append(e)

    rows: List[GWLevelRow] = []
    for loc_id, recs in sorted(current.items()):
        if len(recs) > 1:
            # All recs here share survey_date == event_date, so there is no
            # "latest" to pick by date; take the last in input order.
            qa.add(SEV_WARNING, "multiple_approved_elevations",
                   f"{loc_id}: {len(recs)} approved elevations for {event_date}; "
                   f"using the last in input order", location_id=loc_id)
        best = recs[-1]

        toc = toc_elevations.get(loc_id)
        dtw = (toc - best.elevation) if toc is not None else None

        hist = sorted(historical.get(loc_id, []), key=lambda r: r.survey_date)
        if not hist:
            trend = "INSUFFICIENT_DATA"
        else:
            prev = hist[-1]
            prev_dtw = (toc - prev.elevation) if toc is not None else None
            trend = _trend(best.elevation, dtw, prev.elevation, prev_dtw)

        rows.append(GWLevelRow(
            location_id=loc_id,
            survey_date=event_date,
            water_level_elevation=best.elevation,
            toc_elevation=toc,
            depth_to_water=dtw,
            trend=trend,
            vertical_datum=best.vertical_datum,
        ))

    qa.add(SEV_INFO, "gw_level_summary_complete",
           f"build_gw_level_summary: {len(rows)} well(s) summarised for {event_date}")
    return rows
