"""max_result_dataset.py — cross-event max-detected aggregation."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.config import ND_QUALIFIERS
from ..common.qa import QACollector, QARecord, SEV_INFO


@dataclass
class MaxResultRecord:
    location_id: str
    analyte_name: str
    max_result_value: Optional[float]
    max_result_qualifier: str
    reported_units: str
    max_sample_date: str
    max_sample_id: str
    detection_count: int
    total_sample_count: int
    screening_level: Optional[float]
    exceedance_ratio: Optional[float]
    has_exceedance: bool
    first_detection_date: str
    last_detection_date: str


def _parse_num(v: str) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_max_result_dataset(
    result_rows: list,
    *,
    screening_levels: Optional[dict] = None,
    analytes: Optional[list] = None,
    wells: Optional[list] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_nd: bool = False,
    nd_qualifiers: frozenset = ND_QUALIFIERS,
    qa: Optional[QACollector] = None,
) -> list:
    if qa is None:
        qa = QACollector()
    sl = screening_levels or {}

    # Filters
    rows = result_rows
    if analytes:
        rows = [r for r in rows if r.get("AnalyteName") in analytes]
    if wells:
        rows = [r for r in rows if r.get("LocationID") in wells]
    if date_from:
        rows = [r for r in rows if r.get("SampleDate", "") >= date_from]
    if date_to:
        rows = [r for r in rows if r.get("SampleDate", "") <= date_to]

    # Group
    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r.get("LocationID", ""), r.get("AnalyteName", ""))
        groups.setdefault(key, []).append(r)

    records = []
    for (loc, analyte), grp in groups.items():
        total = len(grp)
        detected = [r for r in grp
                    if r.get("ResultQualifier", "").upper().strip() not in nd_qualifiers
                    and _parse_num(r.get("ResultValue", "")) is not None]

        if not detected and not include_nd:
            continue

        detection_dates = sorted(r.get("SampleDate", "") for r in detected)
        first_det = detection_dates[0] if detection_dates else ""
        last_det  = detection_dates[-1] if detection_dates else ""

        if detected:
            best = max(detected, key=lambda r: _parse_num(r.get("ResultValue", "")) or 0)
            val = _parse_num(best.get("ResultValue", ""))
            qual = best.get("ResultQualifier", "")
            date = best.get("SampleDate", "")
            sid  = best.get("SampleID", "")
        else:
            best = max(grp, key=lambda r: r.get("SampleDate", ""))
            val = None
            qual = best.get("ResultQualifier", "ND")
            date = best.get("SampleDate", "")
            sid  = best.get("SampleID", "")

        screening = sl.get(analyte)
        ratio = (val / screening) if (val is not None and screening) else None
        has_exceedance = ratio is not None and ratio >= 1.0

        records.append(MaxResultRecord(
            location_id=loc, analyte_name=analyte,
            max_result_value=val, max_result_qualifier=qual,
            reported_units=best.get("ReportedUnits", ""),
            max_sample_date=date, max_sample_id=sid,
            detection_count=len(detected), total_sample_count=total,
            screening_level=screening,
            exceedance_ratio=round(ratio, 4) if ratio is not None else None,
            has_exceedance=has_exceedance,
            first_detection_date=first_det, last_detection_date=last_det,
        ))

    qa.add(QARecord(SEV_INFO, "max_result_built",
                    f"{len(records)} location-analyte max records built"))
    return records


def write_max_result_csv(records: list, path: Path) -> None:
    import dataclasses
    if not records:
        Path(path).write_text("")
        return
    fields = [f.name for f in dataclasses.fields(records[0])]
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(dataclasses.asdict(r))
