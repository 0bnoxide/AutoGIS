"""soil_interval_selector.py — display-tier assignment for soil sample intervals.

Assigns each location/analyte/depth interval a display tier used by the
cartography pipeline:

  HOTSPOT  — result detected and exceeds screening level
  DETECT   — result detected, below screening level
  ND       — non-detect: a numeric result flagged non-detect, OR no result and
             no screening context (a true reported non-detect)
  NO_DATA  — no numeric result but a screening level was expected (data gap)

Produces a filtered list of dicts (one per interval) with a ``display_tier``
column added; downstream steps write this to CSV for the figure builder.

Headless: stdlib + csv only, no arcpy, no openpyxl.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO

_ND_QUALIFIERS = frozenset({"ND", "U", "BDL"})


class IntervalTier:
    HOTSPOT = "HOTSPOT"
    DETECT = "DETECT"
    ND = "ND"
    NO_DATA = "NO_DATA"
    ALL = frozenset({HOTSPOT, DETECT, ND, NO_DATA})


@dataclass
class SoilInterval:
    location_id: str
    top_depth_ft: float
    bottom_depth_ft: float
    analyte_name: str
    result_value: Optional[float]
    is_detect: bool
    exceeds_screening: bool
    screening_level: Optional[float]
    units: str


def assign_tier(interval: SoilInterval) -> str:
    """Return the display tier string for a single SoilInterval.

    Priority order:
      1. result_value is None:
         - screening_level present → NO_DATA (a screened analyte with no result)
         - screening_level absent  → ND (a true reported non-detect)
      2. exceeds_screening → HOTSPOT
      3. is_detect (numeric, not flagged) → DETECT
      4. otherwise (numeric but flagged non-detect) → ND

    HOTSPOT trusts the canonical ``ExceedsScreeningLevel`` flag from the source
    CSV (that column is authoritative by design); exceedance is not re-derived
    from result_value vs screening_level here.
    """
    if interval.result_value is None:
        return (IntervalTier.NO_DATA if interval.screening_level is not None
                else IntervalTier.ND)
    if interval.exceeds_screening:
        return IntervalTier.HOTSPOT
    if interval.is_detect:
        return IntervalTier.DETECT
    return IntervalTier.ND


def select_intervals(
    intervals: list,
    *,
    analytes: Optional[list] = None,
    tiers: Optional[list] = None,
    max_depth_ft: Optional[float] = None,
    qa: Optional[QACollector] = None,
) -> list:
    """Filter intervals and assign display tiers.

    Returns a list of dicts — all SoilInterval fields plus ``display_tier``.
    """
    if qa is None:
        qa = QACollector()

    rows = []
    for iv in intervals:
        if analytes and iv.analyte_name not in analytes:
            continue
        if max_depth_ft is not None and iv.top_depth_ft > max_depth_ft:
            continue
        tier = assign_tier(iv)
        if tiers and tier not in tiers:
            continue
        row = asdict(iv)
        row["display_tier"] = tier
        rows.append(row)

    qa.add(QARecord(SEV_INFO, "select_intervals",
                    f"{len(rows)} interval(s) selected; "
                    f"filters — analytes={analytes}, tiers={tiers}, "
                    f"max_depth_ft={max_depth_ft}"))
    return rows


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_bool_flag(value: str) -> bool:
    """Parse common CSV/Excel boolean representations."""
    return value.strip().lower() in {"true", "1", "yes"}


def load_soil_results_csv(path) -> list:
    """Read a soil results CSV and return a list of SoilInterval objects.

    Expected columns: LocationID, TopDepthFt, BottomDepthFt, AnalyteName,
    ResultValue, ResultQualifier, ReportedUnits, ScreeningLevel,
    ExceedsScreeningLevel.
    """
    path = Path(path)
    intervals = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            qualifier = row.get("ResultQualifier", "").strip().upper()
            result_value = _parse_float(row.get("ResultValue", "").strip())
            is_detect = (qualifier not in _ND_QUALIFIERS
                         and result_value is not None)
            intervals.append(SoilInterval(
                location_id=row.get("LocationID", ""),
                top_depth_ft=_parse_float(row.get("TopDepthFt", "")) or 0.0,
                bottom_depth_ft=_parse_float(row.get("BottomDepthFt", "")) or 0.0,
                analyte_name=row.get("AnalyteName", ""),
                result_value=result_value,
                is_detect=is_detect,
                exceeds_screening=_parse_bool_flag(
                    row.get("ExceedsScreeningLevel", "False")),
                screening_level=_parse_float(row.get("ScreeningLevel", "")),
                units=row.get("ReportedUnits", ""),
            ))
    return intervals


def write_intervals_csv(rows: list, out_path: Path) -> None:
    """Write select_intervals output to CSV (empty file if no rows)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
