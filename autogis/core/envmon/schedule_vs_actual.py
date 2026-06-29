"""Compare expected monitoring schedule vs actual results (headless).

Schedule format (YAML):
    site_id: H281
    wells:
      - MW-1
      - MW-2
    required_analytes:
      - Benzene
      - Toluene
    well_analytes:       # optional per-well OVERRIDE of required_analytes
      MW-2:               # MW-2 is sampled for exactly these analytes,
        - Arsenic         # NOT required_analytes + these

This matches the per-well override contract used by ``data_gaps.py`` (the same
``well_analytes`` key means the same thing across both tools).

No arcpy dependency.
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


@dataclasses.dataclass
class ScheduleGapRecord:
    SiteID: str
    LocationID: str
    AnalyteName: str
    Status: str          # "MISSING" | "UNEXPECTED" | "SAMPLED"
    Detail: str
    EventDate: Optional[date]


def load_schedule_yaml(path: Path) -> dict:
    """Load schedule dict from a YAML file."""
    import yaml  # PyYAML
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def compare_schedule_vs_actual(
    results: List[AnalyticalResultRecord],
    schedule: dict,
    *,
    event_date: Optional[date] = None,
    window_days: int = 30,
    qa: QACollector,
) -> List[ScheduleGapRecord]:
    """Compare schedule definition against actual results.

    Args:
        results: Parsed AnalyticalResultRecord list (arcpy-free).
        schedule: Dict loaded from schedule YAML.
        event_date: Latest date to consider; inferred from results if None.
        window_days: Include results within this many days before event_date.
        qa: QACollector for status messages.

    Returns:
        List of ScheduleGapRecord with Status in {MISSING, UNEXPECTED, SAMPLED}.
    """
    site_id = schedule.get("site_id", "")
    wells: List[str] = list(schedule.get("wells") or [])
    required: set = set(schedule.get("required_analytes") or [])
    well_analytes: Dict[str, List[str]] = schedule.get("well_analytes") or {}

    # Determine event date from results if not provided
    if event_date is None and results:
        dates = [r.SampleDate for r in results if r.SampleDate]
        event_date = max(dates) if dates else None

    # Filter results to the event window
    filtered = results
    if event_date:
        start = event_date - timedelta(days=window_days)
        filtered = [
            r for r in results
            if r.SampleDate and start <= r.SampleDate <= event_date
        ]

    # Build lookup: location -> set of analyte canonical names sampled
    sampled: Dict[str, set] = defaultdict(set)
    for r in filtered:
        if not r.IsNotAnalyzed:
            sampled[r.LocationID].add(r.AnalyteCanonicalName)

    out_rows: List[ScheduleGapRecord] = []
    well_set = set(wells)

    # Check each scheduled well against its expected analytes. A per-well
    # well_analytes entry OVERRIDES required_analytes for that well (same
    # contract as data_gaps.py), so the key means one thing across tools.
    for well in wells:
        expected = set(well_analytes.get(well, required))
        got = sampled.get(well, set())
        for analyte in sorted(expected):
            if analyte not in got:
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=well, AnalyteName=analyte,
                    Status="MISSING",
                    Detail="Required by schedule but not found in results",
                    EventDate=event_date,
                ))
            else:
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=well, AnalyteName=analyte,
                    Status="SAMPLED", Detail="",
                    EventDate=event_date,
                ))
        # Extra analytes sampled at a scheduled well but not on its schedule.
        for analyte in sorted(got - expected):
            out_rows.append(ScheduleGapRecord(
                SiteID=site_id, LocationID=well, AnalyteName=analyte,
                Status="UNEXPECTED",
                Detail="Analyte not required by schedule for this well",
                EventDate=event_date,
            ))

    # Detect unexpected wells (in results but not in the schedule)
    for loc, analytes in sorted(sampled.items()):
        if loc not in well_set:
            for analyte in sorted(analytes):
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=loc, AnalyteName=analyte,
                    Status="UNEXPECTED",
                    Detail="Location not in schedule wells list",
                    EventDate=event_date,
                ))

    n_missing = sum(1 for r in out_rows if r.Status == "MISSING")
    n_unexpected = sum(1 for r in out_rows if r.Status == "UNEXPECTED")
    n_sampled = sum(1 for r in out_rows if r.Status == "SAMPLED")

    if n_missing:
        qa.add(
            SEV_WARNING, "schedule_gaps_found",
            f"{n_missing} scheduled analyte(s) missing from results",
        )
    qa.add(
        SEV_INFO, "schedule_vs_actual_complete",
        f"compare_schedule_vs_actual: {n_sampled} sampled, "
        f"{n_missing} missing, {n_unexpected} unexpected "
        f"out of {len(out_rows)} total records",
    )
    return out_rows


def write_gap_csv(rows: List[ScheduleGapRecord], output_path: Path) -> None:
    """Write ScheduleGapRecord list to CSV (delegates to the shared writer)."""
    from ..common.records_csv import write_records_csv

    write_records_csv(rows, output_path, record_class=ScheduleGapRecord)
