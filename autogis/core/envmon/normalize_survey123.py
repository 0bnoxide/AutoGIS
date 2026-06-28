"""normalize_survey123.py — map Survey123 JSON/CSV submissions to GDB record dicts.

Arcpy-free. Produces the same typed dicts as normalize_groundwater.py /
normalize_*.py so the existing import_to_gdb write layer can consume them.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING


@dataclass
class Survey123Field:
    well_id_field: str = "WellID"
    sampling_date_field: str = "SamplingDate"
    matrix_field: str = "Matrix"
    sampled_by_field: str = "SampledBy"
    coc_number_field: str = "COCNumber"
    dtw_field: str = "DepthToWater_ft"


def _parse_date(value: str, qa: QACollector, context: str) -> Optional[datetime]:
    value_text = str(value).strip() if value is not None else ""
    if not value_text:
        qa.add(QARecord(SEV_ERROR, "invalid_date",
                        f"{context}: missing date"))
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value_text, fmt)
        except ValueError:
            continue
    qa.add(QARecord(SEV_ERROR, "invalid_date",
                    f"{context}: cannot parse date {value!r}"))
    return None


def normalize_survey123_submission(
    payload: dict,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    fm = field_map or Survey123Field()
    well_id = payload.get(fm.well_id_field)
    if not well_id:
        qa.add(QARecord(SEV_ERROR, "missing_required_field",
                        f"Survey123 submission missing {fm.well_id_field!r}"))
        return [], []

    date_raw = payload.get(fm.sampling_date_field, "")
    dt = _parse_date(date_raw, qa, f"submission/{well_id}")
    matrix = str(payload.get(fm.matrix_field, "GW") or "GW")
    sampled_by = payload.get(fm.sampled_by_field, "")
    coc = payload.get(fm.coc_number_field, "")
    dtw_raw = payload.get(fm.dtw_field)

    water_levels: list[dict] = []
    if dtw_raw is not None:
        try:
            dtw = float(dtw_raw)
            water_levels.append({
                "ImportBatchID": batch_id,
                "SiteID": site_id,
                "LocationID": str(well_id),
                "MeasurementDate": dt,
                "DTW_ft": dtw,
                "GWE_ft": None,  # computed when TOC elevation is available
                "MeasuredBy": sampled_by,
                "MeasurementMethod": "Survey123",
            })
        except (TypeError, ValueError):
            qa.add(QARecord(SEV_WARNING, "invalid_dtw",
                            f"{well_id}: cannot parse DTW value {dtw_raw!r}"))

    sample_id = (
        f"{well_id}-{dt.strftime('%Y%m%d')}-{matrix}" if dt
        else f"{well_id}-NODATE-{uuid.uuid4().hex[:6].upper()}-{matrix}"
    )
    samples: list[dict] = [{
        "ImportBatchID": batch_id,
        "SiteID": site_id,
        "LocationID": str(well_id),
        "SampleID": sample_id,
        "SampleDate": dt,
        "Matrix": matrix,
        "SampledBy": sampled_by,
        "COCNumber": coc,
        "SampleSource": "Survey123",
    }]
    return water_levels, samples


def load_survey123_csv_submissions(
    path: Path,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    all_wl: list[dict] = []
    all_samp: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            step_batch = f"{batch_id}_{i}"
            wl, samp = normalize_survey123_submission(
                dict(row), site_id, step_batch, qa, field_map)
            all_wl.extend(wl)
            all_samp.extend(samp)
    return all_wl, all_samp
