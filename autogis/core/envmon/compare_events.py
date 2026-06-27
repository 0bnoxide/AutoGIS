"""Compare current vs previous monitoring event per location/analyte (Tool 4.7).

Headless, arcpy-free. Keys series on (LocationID, AnalyteCanonicalName); adds
Matrix to the key only for locations that appear under more than one matrix.
See ADR-0026 for locked design decisions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


@dataclass
class ComparisonRecord:
    SiteID: str
    LocationID: str
    Matrix: str
    AnalyteCanonicalName: str
    CurrentEventDate: Optional[date]
    PreviousEventDate: Optional[date]
    CurrentResultRaw: str
    PreviousResultRaw: str
    CurrentResultNumeric: Optional[float]
    PreviousResultNumeric: Optional[float]
    Delta: Optional[float]
    PercentChange: Optional[float]
    TrendClass: str
    CurrentExceedance: str
    PreviousExceedance: str


def _detected(r: AnalyticalResultRecord) -> bool:
    return r.IsDetected == 1 and r.ResultNumeric is not None


def _exc(v) -> str:
    return {1: "Y", 0: "N"}.get(v, "")


def _classify(cur_det: bool, prev_det: bool,
               pct: Optional[float], stable_threshold: float) -> str:
    if cur_det and prev_det:
        if pct is None:
            return "INDETERMINATE"
        if abs(pct) <= stable_threshold:
            return "STABLE"
        return "INCREASED" if pct > 0 else "DECREASED"
    if cur_det and not prev_det:
        return "NEW_DETECTION"
    if not cur_det and prev_det:
        return "NO_LONGER_DETECTED"
    if not cur_det and not prev_det:
        return "NONDETECT_BOTH"
    return "INDETERMINATE"


def compare_events(
    results: List[AnalyticalResultRecord],
    qa: QACollector,
    *,
    current_event_date: Optional[date] = None,
    stable_threshold: float = 10.0,
) -> List[ComparisonRecord]:
    """Compare current vs previous monitoring event records.

    Returns one ComparisonRecord per (LocationID[, Matrix], AnalyteCanonicalName)
    series. See ADR-0026 for locked design decisions.
    """
    # 1. Detect mixed-matrix locations — locations that appear under >1 matrix.
    loc_matrices: dict[str, set] = defaultdict(set)
    for r in results:
        loc_matrices[r.LocationID].add(r.Matrix)
    mixed_locs = {loc for loc, mats in loc_matrices.items() if len(mats) > 1}
    for loc in sorted(mixed_locs):
        qa.add(SEV_WARNING, "mixed_matrix",
               f"LocationID {loc!r} appears under multiple matrices "
               f"{sorted(loc_matrices[loc])} — Matrix added to series key",
               location_id=loc)

    # 2. Group results by series key.
    #    For mixed-matrix locations: key = (LocationID, AnalyteCanonicalName, Matrix)
    #    For normal locations: key = (LocationID, AnalyteCanonicalName, "")
    groups: dict[tuple, list[AnalyticalResultRecord]] = defaultdict(list)
    for r in results:
        matrix_key = r.Matrix if r.LocationID in mixed_locs else ""
        key = (r.LocationID, r.AnalyteCanonicalName, matrix_key)
        groups[key].append(r)

    output: List[ComparisonRecord] = []

    for (loc_id, analyte, matrix_key), recs in groups.items():
        # Determine the effective matrix for this series.
        effective_matrix = matrix_key if matrix_key else (recs[0].Matrix if recs else "")

        # 3. Per series: pick current and previous records by SampleDate.
        dates = sorted({r.SampleDate for r in recs if r.SampleDate is not None})

        if current_event_date is not None:
            if current_event_date not in dates:
                qa.add(SEV_INFO, "no_current_record",
                       f"No record for {loc_id!r}/{analyte!r} on "
                       f"current_event_date={current_event_date}; series skipped",
                       location_id=loc_id, analyte_name=analyte)
                continue
            cur_date = current_event_date
            prev_dates = [d for d in dates if d < cur_date]
            prev_date = prev_dates[-1] if prev_dates else None
        else:
            if not dates:
                continue
            cur_date = dates[-1]
            prev_dates = dates[:-1]
            prev_date = prev_dates[-1] if prev_dates else None

        cur_recs = [r for r in recs if r.SampleDate == cur_date]
        prev_recs = [r for r in recs if r.SampleDate == prev_date] if prev_date else []

        # Use the first record per date (one result per loc/analyte/date expected).
        cur = cur_recs[0] if cur_recs else None
        prev = prev_recs[0] if prev_recs else None

        if cur is None:
            continue

        cur_det = _detected(cur)
        prev_det = _detected(prev) if prev else False

        # 4. Compute Delta / PercentChange.
        delta: Optional[float] = None
        pct: Optional[float] = None
        if cur_det and prev_det:
            delta = cur.ResultNumeric - prev.ResultNumeric  # type: ignore[operator]
            if prev.ResultNumeric == 0:  # type: ignore[union-attr]
                qa.add(SEV_WARNING, "percent_change_zero_base",
                       f"Previous value is 0 for {loc_id!r}/{analyte!r}; "
                       f"PercentChange set to None",
                       location_id=loc_id, analyte_name=analyte)
            else:
                pct = delta / prev.ResultNumeric * 100.0  # type: ignore[operator]

        trend = _classify(cur_det, prev_det, pct, stable_threshold)

        output.append(ComparisonRecord(
            SiteID=cur.SiteID,
            LocationID=loc_id,
            Matrix=effective_matrix,
            AnalyteCanonicalName=analyte,
            CurrentEventDate=cur_date,
            PreviousEventDate=prev_date,
            CurrentResultRaw=cur.ResultRawText or "",
            PreviousResultRaw=(prev.ResultRawText or "") if prev else "",
            CurrentResultNumeric=cur.ResultNumeric,
            PreviousResultNumeric=prev.ResultNumeric if prev else None,
            Delta=delta,
            PercentChange=pct,
            TrendClass=trend,
            CurrentExceedance=_exc(cur.ExceedsScreeningLevel),
            PreviousExceedance=_exc(prev.ExceedsScreeningLevel) if prev else "",
        ))

    qa.add(SEV_INFO, "compare_complete",
           f"compare_events: {len(output)} comparison record(s) produced")
    return output
