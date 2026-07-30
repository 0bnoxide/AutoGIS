"""normalize_survey123.py — map Survey123 JSON/CSV submissions to GDB record dicts.

Arcpy-free. Produces the same typed dicts as normalize_groundwater.py /
normalize_*.py so the existing import_to_gdb write layer can consume them.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING
from .sample_id import build_sample_id, strip_qc

#: The qa_flags choice (ADR-0021) that marks a submission as a field
#: duplicate. Survey123 exports select_multiple answers space-delimited;
#: some feature-service exports comma-delimit instead.
FIELD_DUP_CODES = {
    "field_dup": "FD",  # forms generated before the A/B fix
    "field_dup_a": "FD-A",
    "field_dup_b": "FD-B",
}


@dataclass
class Survey123Field:
    well_id_field: str = "WellID"
    sampling_date_field: str = "SamplingDate"
    matrix_field: str = "Matrix"
    sampled_by_field: str = "SampledBy"
    coc_number_field: str = "COCNumber"
    dtw_field: str = "DepthToWater_ft"
    qa_flags_field: str = "QAFlags"


def _qa_flags(payload: dict, fm: "Survey123Field") -> set:
    """The ticked qa_flags choices, lowercased.

    Survey123 renders a select_multiple as one space-delimited string; some
    feature-service exports comma-delimit, and a JSON payload may carry a real
    list. str() on a list yields "['a', 'b']", whose split matches nothing —
    which would silently normalize a field duplicate as its own primary.
    An absent field means "nothing ticked", so submissions from forms built
    before the -FD calculate normalize exactly as before.
    """
    raw = payload.get(fm.qa_flags_field, "") or ""
    if isinstance(raw, (list, tuple, set)):
        raw = " ".join(str(v) for v in raw)
    return {f for f in re.split(r"[,\s]+", str(raw).lower()) if f}


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

    dup_flags = _qa_flags(payload, fm) & FIELD_DUP_CODES.keys()
    if len(dup_flags) > 1:
        qa.add(QARecord(
            SEV_ERROR, "ambiguous_field_duplicate_code",
            f"{well_id}: choose exactly one field duplicate code (A or B)."))
        return water_levels, []
    qc = FIELD_DUP_CODES[next(iter(dup_flags))] if dup_flags else None
    is_dup = qc is not None
    sample_id = build_sample_id(well_id, dt, matrix, qc=qc)
    # Env_Samples has carried IsDuplicate/DuplicateType/ParentSampleID since
    # the EDD importer; evaluate_duplicate_rpd pairs on IsDuplicate == 0 / 1,
    # so leaving them NULL makes a record neither a parent nor a duplicate and
    # silently skips RPD QA. Both sides must be populated, not just the -FD.
    samples: list[dict] = [{
        "ImportBatchID": batch_id,
        "SiteID": site_id,
        "LocationID": str(well_id),
        "SampleID": sample_id,
        "ParentSampleID": strip_qc(sample_id) if is_dup else "",
        "SampleDate": dt,
        "Matrix": matrix,
        "SampledBy": sampled_by,
        "COCNumber": coc,
        "IsDuplicate": int(is_dup),
        "DuplicateType": "FIELD_DUP" if is_dup else "",
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
