"""build_exceedance_event.py — Tool 4.4 BuildAnalyticalExceedanceEvent.

Select samples per an exceedance-aware rule and enrich each result with an
exceedance ratio (result / screening level), an exceedance tier label, and
detection/exceedance flags. Produces one record per (location, analyte) pair.

Headless: stdlib + optional yaml load, no arcpy. Input rows are raw
``csv.DictReader`` dicts (LocationID, AnalyteName, ResultValue,
ResultQualifier, ReportedUnits, SampleDate, SampleID) — matching the sibling
headless tools on this branch.
"""
from __future__ import annotations

import csv
import dataclasses
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..common.config import ND_QUALIFIERS
from .report_input import normalize_report_rows, validate_iso_date
from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

# Lower-bound-inclusive tiers: lo <= ratio < hi. Exceedance starts at ratio 1.0,
# consistent with has_exceedance (ratio >= 1.0).
_TIERS: Tuple[Tuple[float, Optional[float], str], ...] = (
    (0.0, 1.0, "below"),
    (1.0, 2.0, "1x-2x"),
    (2.0, 5.0, "2x-5x"),
    (5.0, 10.0, "5x-10x"),
    (10.0, None, ">10x"),
)

SUPPORTED_RULES = (
    "max_exceedance_per_location", "latest_per_location",
    "specific_event_date", "date_range_latest",
)


@dataclass
class ExceedanceEventRecord:
    location_id: str
    sample_id: str
    sample_date: str
    analyte_name: str
    result_value: Optional[float]
    result_qualifier: str
    reported_units: str
    screening_level: Optional[float]
    screening_level_name: str
    exceedance_ratio: Optional[float]
    exceedance_tier: str
    has_exceedance: bool
    has_detection: bool
    selection_reason: str


def _parse_num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_nondetect(row: dict) -> bool:
    qual = str(row.get("ResultQualifier", "")).upper().strip()
    if qual in ND_QUALIFIERS:
        return True
    return _parse_num(row.get("ResultValue", "")) is None


def classify_exceedance_tier(ratio: Optional[float]) -> str:
    """Map a numeric exceedance ratio to a tier label ('below' if None)."""
    if ratio is None:
        return "below"
    for lo, hi, label in _TIERS:
        if ratio >= lo and (hi is None or ratio < hi):
            return label
    return "below"


def _ratio(row: dict, sl: Optional[float]) -> Optional[float]:
    if sl in (None, 0) or _is_nondetect(row):
        return None
    val = _parse_num(row.get("ResultValue", ""))
    return (val / sl) if val is not None else None


def build_exceedance_event(
    result_rows: List[dict],
    screening_levels: Dict[str, float],
    *,
    rule: str = "max_exceedance_per_location",
    event_date: Optional[str] = None,
    date_range: Optional[Tuple[str, str]] = None,
    screening_level_name: str = "",
    qa: Optional[QACollector] = None,
) -> List[ExceedanceEventRecord]:
    """Select samples by ``rule`` and enrich with ratio/tier. One record per
    (location, analyte)."""
    qa = qa or QACollector()
    sl = screening_levels or {}
    if rule not in SUPPORTED_RULES:
        raise ValueError(f"Unsupported rule {rule!r}; "
                         f"expected one of {SUPPORTED_RULES}")

    rows = normalize_report_rows(result_rows, qa)
    if rule == "specific_event_date":
        if not event_date:
            raise ValueError("specific_event_date requires event_date")
        validate_iso_date(event_date, "event_date")
        rows = [r for r in rows if r.get("SampleDate", "") == event_date]
    elif rule == "date_range_latest":
        if not date_range:
            raise ValueError("date_range_latest requires date_range")
        lo, hi = date_range
        validate_iso_date(lo, "date_range[0]")
        validate_iso_date(hi, "date_range[1]")
        rows = [r for r in rows if lo <= r.get("SampleDate", "") <= hi]

    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for r in rows:
        groups[(r.get("LocationID", ""), r.get("AnalyteName", ""))].append(r)

    records: List[ExceedanceEventRecord] = []
    for (loc, analyte), grp in groups.items():
        screening = sl.get(analyte)
        if analyte and screening is None:
            qa.add(QARecord(
                severity=SEV_WARNING, category="no_screening_level",
                message=f"No screening level for analyte {analyte!r}; "
                        f"ratio/tier left blank.",
                location_id=loc, analyte_name=analyte,
                recommended_action="Add the analyte to the screening-levels YAML."))

        if rule == "max_exceedance_per_location":
            chosen = max(grp, key=lambda r: (_ratio(r, screening) or -1.0,
                                             r.get("SampleDate", "")))
            reason = "max exceedance ratio per location"
        else:  # latest_per_location / specific_event_date / date_range_latest
            chosen = max(grp, key=lambda r: r.get("SampleDate", ""))
            reason = {"latest_per_location": "latest sample per location",
                      "specific_event_date": f"event date {event_date}",
                      "date_range_latest": "latest within date range"}[rule]

        ratio = _ratio(chosen, screening)
        val = _parse_num(chosen.get("ResultValue", ""))
        detected = not _is_nondetect(chosen)
        records.append(ExceedanceEventRecord(
            location_id=loc, sample_id=chosen.get("SampleID", ""),
            sample_date=chosen.get("SampleDate", ""), analyte_name=analyte,
            result_value=val if detected else None,
            result_qualifier=chosen.get("ResultQualifier", ""),
            reported_units=chosen.get("ReportedUnits", ""),
            screening_level=screening, screening_level_name=screening_level_name,
            exceedance_ratio=round(ratio, 4) if ratio is not None else None,
            exceedance_tier=classify_exceedance_tier(ratio),
            has_exceedance=ratio is not None and ratio >= 1.0,
            has_detection=detected, selection_reason=reason,
        ))

    records.sort(key=lambda r: (r.location_id, r.analyte_name))
    qa.add(QARecord(SEV_INFO, "exceedance_event_built",
                    f"{len(records)} location-analyte records built "
                    f"(rule={rule})."))
    return records


def load_screening_levels_yaml(path: Path) -> Dict[str, float]:
    """Load a {AnalyteName: screening_value} mapping from YAML."""
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): float(v) for k, v in data.items() if v is not None}


def write_exceedance_event_csv(
    records: List[ExceedanceEventRecord], path: Path
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f.name for f in dataclasses.fields(ExceedanceEventRecord)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
