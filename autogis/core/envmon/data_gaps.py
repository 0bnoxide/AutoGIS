"""Identify monitoring data gaps vs an expected schedule (Tool 4.10).

Headless, arcpy-free. Compares a schedule (well network + required analytes)
against actual AnalyticalResultRecords for an event window. See ADR-0026.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .gdb_schema import AnalyticalResultRecord
from .canonical_read import canonical_records
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR

_SEV = {
    "MISSING_WELL": SEV_ERROR,
    "MISSED_ANALYTE": SEV_ERROR,
    "UNEXPECTED_WELL": SEV_WARNING,
    "DRY_OR_INACCESSIBLE": SEV_INFO,
}


@dataclass
class DataGapRecord:
    SiteID: str
    LocationID: str
    AnalyteCanonicalName: str
    GapType: str
    Severity: str
    EventLabel: str
    Detail: str


def _in_window(r: AnalyticalResultRecord, event_date: Optional[date],
               window_days: int) -> bool:
    if event_date is None:
        return True
    if r.SampleDate is None:
        return False
    return abs((r.SampleDate - event_date).days) <= window_days


def identify_data_gaps(
    results: List[AnalyticalResultRecord],
    schedule: dict,
    *,
    event_date: Optional[date],
    window_days: int,
    dry_wells: Dict[str, str],
    qa: QACollector,
) -> List[DataGapRecord]:
    """Identify missing wells, missed analytes, dry wells, and unexpected wells.

    Args:
        results: Analytical result records for the site.
        schedule: Dict with keys: site_id, event_label, wells,
                  required_analytes, and optionally well_analytes.
        event_date: Center date for the sampling window; None = use all results.
        window_days: Half-width of the event window in days.
        dry_wells: Mapping of LocationID -> reason for dry/inaccessible wells.
        qa: QA collector to receive gap records.

    Returns:
        List of DataGapRecord, one per gap.
    """
    site_id = schedule.get("site_id", "")
    event_label = schedule.get("event_label", "")
    network = list(schedule.get("wells", []))
    required_analytes = list(schedule.get("required_analytes", []))
    well_analytes_override: dict = schedule.get("well_analytes", {}) or {}

    # 1. Filter results into the event window.
    window_results = [r for r in results if _in_window(r, event_date, window_days)]

    window_results = canonical_records(window_results, qa)

    # 2. Index: LocationID -> set of AnalyteCanonicalName
    loc_analytes: dict[str, set] = defaultdict(set)
    for r in window_results:
        loc_analytes[r.LocationID].add(r.AnalyteCanonicalName)

    network_set = set(network)
    gaps: List[DataGapRecord] = []

    # 3. Check each scheduled well.
    for well in network:
        if well in dry_wells:
            reason = dry_wells[well]
            gaps.append(DataGapRecord(
                SiteID=site_id, LocationID=well, AnalyteCanonicalName="",
                GapType="DRY_OR_INACCESSIBLE", Severity=SEV_INFO,
                EventLabel=event_label,
                Detail=f"Well flagged dry/inaccessible: {reason}"))
            qa.add(SEV_INFO, "dry_or_inaccessible",
                   f"Well {well!r} is dry/inaccessible: {reason}",
                   site_id=site_id, location_id=well)
            continue

        if well not in loc_analytes:
            gaps.append(DataGapRecord(
                SiteID=site_id, LocationID=well, AnalyteCanonicalName="",
                GapType="MISSING_WELL", Severity=SEV_ERROR,
                EventLabel=event_label,
                Detail="No results in event window"))
            qa.add(SEV_ERROR, "missing_well",
                   f"Well {well!r} has no results in event window",
                   site_id=site_id, location_id=well)
            continue

        # Well has results — check per-analyte.
        required = well_analytes_override.get(well, required_analytes)
        present = loc_analytes[well]
        for analyte in required:
            if analyte not in present:
                gaps.append(DataGapRecord(
                    SiteID=site_id, LocationID=well,
                    AnalyteCanonicalName=analyte,
                    GapType="MISSED_ANALYTE", Severity=SEV_ERROR,
                    EventLabel=event_label,
                    Detail=f"Analyte {analyte!r} not found in results for well"))
                qa.add(SEV_ERROR, "missed_analyte",
                       f"Well {well!r}: required analyte {analyte!r} absent",
                       site_id=site_id, location_id=well, analyte_name=analyte)

    # 4. Unexpected wells: results for LocationIDs not in the network.
    unexpected_seen: set = set()
    for loc in loc_analytes:
        if loc not in network_set and loc not in unexpected_seen:
            unexpected_seen.add(loc)
            gaps.append(DataGapRecord(
                SiteID=site_id, LocationID=loc, AnalyteCanonicalName="",
                GapType="UNEXPECTED_WELL", Severity=SEV_WARNING,
                EventLabel=event_label,
                Detail="LocationID not in expected well network"))
            qa.add(SEV_WARNING, "unexpected_well",
                   f"Well {loc!r} has results but is not in the scheduled network",
                   site_id=site_id, location_id=loc)

    # 5. Summary info.
    counts: dict[str, int] = {}
    for g in gaps:
        counts[g.GapType] = counts.get(g.GapType, 0) + 1
    qa.add(SEV_INFO, "data_gaps_complete",
           f"identify_data_gaps: {len(gaps)} gap(s) — " +
           ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
           site_id=site_id)

    return gaps
