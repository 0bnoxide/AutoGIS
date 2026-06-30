"""Build the per-event groundwater-elevation contour layer (Tool 4.1).

Headless: selects one water-level record per well for a target event,
populates ``EnvWaterLevelEvent``, and flags points that must NOT feed the
potentiometric contour surface (dry/NM/NS, anomalous, explicitly excluded,
perched/separate-zone). Contour generation itself stays in ``gw-contours``
(arcpy); this only prepares + flags the input points.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional, Set

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ..common.schema.envmon import EnvWaterLevelEvent

# Field status codes that make a well unusable for contouring.
_NO_CONTOUR_STATUS = {"DRY", "NM", "NS"}


@dataclass
class GWEventResult:
    records: List[EnvWaterLevelEvent]
    contour_points: int          # use_for_model == True
    excluded: int
    anomalous: int
    qa: QACollector


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def build_gwe_event(
    water_levels: List[dict],
    *,
    event_date: str,
    exclude_locations: Optional[Set[str]] = None,
    perched_locations: Optional[Set[str]] = None,
    anomaly_stdev: float = 3.0,
    qa: Optional[QACollector] = None,
) -> GWEventResult:
    """Build the per-event contour layer with exclusion flags."""
    if qa is None:
        qa = QACollector()
    exclude_locations = {s for s in (exclude_locations or set())}
    perched_locations = {s for s in (perched_locations or set())}
    ev_date = date.fromisoformat(event_date)

    # One record per well (input is expected per-event); warn on duplicates.
    selected: dict = {}
    for wl in water_levels:
        loc = str(wl.get("location_id", "")).strip()
        if not loc:
            qa.add(SEV_WARNING, "blank_location_id",
                   "Water-level row with blank location_id skipped")
            continue
        if loc in selected:
            qa.add(SEV_WARNING, "duplicate_water_level",
                   f"{loc}: multiple water-level rows for {event_date}; "
                   f"using the first", location_id=loc)
            continue
        selected[loc] = wl

    # Anomaly population: wells with a real elevation, OK status, not on an
    # exclusion list. 0.0 is a valid elevation (is-not-None guard).
    pop = []
    for loc, wl in selected.items():
        gwe = _to_float(wl.get("gwe_ft"))
        status = str(wl.get("status", "") or "").strip().upper()
        if (gwe is not None and status not in _NO_CONTOUR_STATUS
                and loc not in exclude_locations
                and loc not in perched_locations):
            pop.append(gwe)
    # Robust (median + MAD) instead of mean/stdev on purpose: a single gross
    # outlier inflates its own mean/stdev and escapes a mean±Nσ test (masking).
    # The modified z-score 0.6745*(x-median)/MAD is the standard robust detector;
    # anomaly_stdev is its threshold (≈ stdev count). MAD==0 (≥half identical)
    # means no meaningful spread -> skip anomaly flagging.
    median = mad = None
    if len(pop) >= 2:
        median = statistics.median(pop)
        mad = statistics.median([abs(x - median) for x in pop])
        if mad == 0:
            mad = None

    records: List[EnvWaterLevelEvent] = []
    anomalous = 0
    for loc, wl in sorted(selected.items()):
        gwe = _to_float(wl.get("gwe_ft"))
        dtw = _to_float(wl.get("dtw_ft"))
        status = str(wl.get("status", "") or "").strip()
        reasons: List[str] = []

        if gwe is None:
            reasons.append("missing_elevation")
        if status.upper() in _NO_CONTOUR_STATUS:
            reasons.append(status)
        if loc in exclude_locations:
            reasons.append("excluded")
        if loc in perched_locations:
            reasons.append("perched/separate-zone")

        is_anom = (
            gwe is not None and median is not None and mad is not None
            and 0.6745 * abs(gwe - median) / mad > anomaly_stdev
            and not reasons  # don't re-flag an already-excluded well
        )
        if is_anom:
            reasons.append("anomalous")
            anomalous += 1
            qa.add(SEV_WARNING, "anomalous_elevation",
                   f"{loc}: gwe {gwe} ft is a robust outlier (> {anomaly_stdev} "
                   f"from event median {median:.2f} ft); excluded from contouring",
                   location_id=loc)

        records.append(EnvWaterLevelEvent(
            site_id=str(wl.get("site_id", "") or ""),
            location_id=loc,
            event_date=ev_date,
            dtw_ft=dtw,
            gwe_ft=gwe,
            status=status,
            use_for_model=not reasons,
            exclusion_reason="; ".join(reasons),
            measured_by=str(wl.get("measured_by", "") or ""),
        ))

    contour_points = sum(1 for r in records if r.use_for_model)
    excluded = len(records) - contour_points
    qa.add(SEV_INFO, "gwe_event_built",
           f"build_gwe_event: {len(records)} wells, {contour_points} contour "
           f"points, {excluded} excluded ({anomalous} anomalous) for {event_date}")

    return GWEventResult(records=records, contour_points=contour_points,
                         excluded=excluded, anomalous=anomalous, qa=qa)


def write_gwe_event(result: GWEventResult, out_path: Path) -> Path:
    """Write the EnvWaterLevelEvent rows (flags as columns) to CSV."""
    from ..common.records_csv import write_records_csv
    return write_records_csv(result.records, Path(out_path),
                             record_class=EnvWaterLevelEvent)
