"""Reconcile field sample records against lab results (Tool 7.3).

Headless, arcpy-free. Flags samples missing from lab, lab results missing
from field records, date mismatches, matrix mismatches, and duplicate IDs.
Distinct from reconcile-survey123-lab (Tool 2.6), which is Survey123-specific.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclass
class FieldSampleRecord:
    sample_id: str
    location_id: str
    collection_date: str
    matrix: str
    analyte_group: str = ""
    notes: str = ""


@dataclass
class LabResultRecord:
    sample_id: str
    location_id: str
    analysis_date: str
    analyte_name: str
    matrix: str = ""
    result_value: str = ""
    result_units: str = ""


@dataclass
class ReconciliationFlag:
    SampleID: str
    LocationID: str
    FlagType: str
    Severity: str
    Detail: str


_FLAG_SEVERITY = {
    "LAB_MISSING_FROM_FIELD": SEV_ERROR,
    "FIELD_MISSING_FROM_LAB": SEV_ERROR,
    "DATE_MISMATCH": SEV_WARNING,
    "MATRIX_MISMATCH": SEV_WARNING,
    "LOCATION_MISMATCH": SEV_ERROR,
    "DUPLICATE_FIELD_SAMPLE": SEV_WARNING,
    "DUPLICATE_LAB_RESULT": SEV_WARNING,
}


def read_field_samples_csv(path: Path) -> List[FieldSampleRecord]:
    """Read field samples CSV. Required: sample_id, location_id, collection_date."""
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    required = {"sample_id", "location_id", "collection_date"}
    if rows:
        missing = required - rows[0].keys()
        if missing:
            raise ValueError(f"Field samples CSV missing columns: {missing}")
    return [FieldSampleRecord(
        sample_id=r["sample_id"].strip(),
        location_id=r["location_id"].strip(),
        collection_date=r["collection_date"].strip(),
        matrix=r.get("matrix", "").strip(),
        analyte_group=r.get("analyte_group", "").strip(),
        notes=r.get("notes", "").strip(),
    ) for r in rows if r.get("sample_id", "").strip()]


def read_lab_results_csv(path: Path) -> List[LabResultRecord]:
    """Read lab results CSV. Required: sample_id, location_id, analysis_date, analyte_name."""
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    required = {"sample_id", "location_id", "analysis_date", "analyte_name"}
    if rows:
        missing = required - rows[0].keys()
        if missing:
            raise ValueError(f"Lab results CSV missing columns: {missing}")
    return [LabResultRecord(
        sample_id=r["sample_id"].strip(),
        location_id=r["location_id"].strip(),
        analysis_date=r["analysis_date"].strip(),
        analyte_name=r["analyte_name"].strip(),
        matrix=r.get("matrix", "").strip(),
        result_value=r.get("result_value", "").strip(),
        result_units=r.get("result_units", "").strip(),
    ) for r in rows if r.get("sample_id", "").strip()]


def _date_from_str(s: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def reconcile_field_and_lab(
    field_samples: List[FieldSampleRecord],
    lab_results: List[LabResultRecord],
    *,
    date_tolerance_days: int = 1,
    qa: Optional[QACollector] = None,
) -> List[ReconciliationFlag]:
    """Compare field records to lab results and emit flags.

    Args:
        field_samples: From read_field_samples_csv.
        lab_results: From read_lab_results_csv.
        date_tolerance_days: Max date delta before DATE_MISMATCH flag.
        qa: QA collector (created if not supplied).

    Returns:
        List of ReconciliationFlag.
    """
    if qa is None:
        qa = QACollector()

    flags: List[ReconciliationFlag] = []

    # Index field samples by sample_id.
    field_by_id: dict[str, list[FieldSampleRecord]] = {}
    for fs in field_samples:
        field_by_id.setdefault(fs.sample_id, []).append(fs)

    # Flag duplicate field sample IDs.
    for sid, dupes in field_by_id.items():
        if len(dupes) > 1:
            flags.append(ReconciliationFlag(
                SampleID=sid, LocationID=dupes[0].location_id,
                FlagType="DUPLICATE_FIELD_SAMPLE",
                Severity=SEV_WARNING,
                Detail=f"{len(dupes)} field rows share sample_id '{sid}'",
            ))
            qa.add(SEV_WARNING, "duplicate_field_sample",
                   f"Duplicate field sample_id: {sid!r}")

    # Index lab results by sample_id.
    lab_by_id: dict[str, list[LabResultRecord]] = {}
    for lr in lab_results:
        lab_by_id.setdefault(lr.sample_id, []).append(lr)

    # Flag duplicate lab sample IDs (same sample_id, same analyte).
    seen_lab_keys: set = set()
    for lr in lab_results:
        key = (lr.sample_id, lr.analyte_name)
        if key in seen_lab_keys:
            flags.append(ReconciliationFlag(
                SampleID=lr.sample_id, LocationID=lr.location_id,
                FlagType="DUPLICATE_LAB_RESULT",
                Severity=SEV_WARNING,
                Detail=f"Duplicate lab result for sample '{lr.sample_id}', "
                       f"analyte '{lr.analyte_name}'",
            ))
            qa.add(SEV_WARNING, "duplicate_lab_result",
                   f"Duplicate lab: {lr.sample_id!r} / {lr.analyte_name!r}")
        seen_lab_keys.add(key)

    # Check: lab sample in field records?
    lab_sample_ids = set(lab_by_id.keys())
    field_sample_ids = set(field_by_id.keys())

    for sid in lab_sample_ids - field_sample_ids:
        lr = lab_by_id[sid][0]
        flags.append(ReconciliationFlag(
            SampleID=sid, LocationID=lr.location_id,
            FlagType="LAB_MISSING_FROM_FIELD",
            Severity=SEV_ERROR,
            Detail=f"Lab has results for sample '{sid}' "
                   f"({lr.location_id}) but no matching field record",
        ))
        qa.add(SEV_ERROR, "lab_missing_from_field",
               f"Lab sample {sid!r} has no field record",
               location_id=lr.location_id)

    # Check: field sample in lab?
    for sid in field_sample_ids - lab_sample_ids:
        fs = field_by_id[sid][0]
        flags.append(ReconciliationFlag(
            SampleID=sid, LocationID=fs.location_id,
            FlagType="FIELD_MISSING_FROM_LAB",
            Severity=SEV_ERROR,
            Detail=f"Field record for '{sid}' ({fs.location_id}) "
                   f"has no lab results",
        ))
        qa.add(SEV_ERROR, "field_missing_from_lab",
               f"Field sample {sid!r} has no lab results",
               location_id=fs.location_id)

    # Cross-check matching samples.
    for sid in field_sample_ids & lab_sample_ids:
        fs = field_by_id[sid][0]
        lr = lab_by_id[sid][0]

        # Location mismatch.
        if fs.location_id and lr.location_id and fs.location_id != lr.location_id:
            flags.append(ReconciliationFlag(
                SampleID=sid, LocationID=fs.location_id,
                FlagType="LOCATION_MISMATCH",
                Severity=SEV_ERROR,
                Detail=f"Field location '{fs.location_id}' ≠ "
                       f"lab location '{lr.location_id}'",
            ))
            qa.add(SEV_ERROR, "location_mismatch",
                   f"Sample {sid!r}: field={fs.location_id!r}, "
                   f"lab={lr.location_id!r}")

        # Date mismatch.
        fd = _date_from_str(fs.collection_date)
        ld = _date_from_str(lr.analysis_date)
        if fd and ld and abs((ld - fd).days) > date_tolerance_days:
            flags.append(ReconciliationFlag(
                SampleID=sid, LocationID=fs.location_id,
                FlagType="DATE_MISMATCH",
                Severity=SEV_WARNING,
                Detail=f"Collection date {fs.collection_date} vs "
                       f"analysis date {lr.analysis_date} "
                       f"({abs((ld - fd).days)} day gap)",
            ))
            qa.add(SEV_WARNING, "date_mismatch",
                   f"Sample {sid!r}: collection={fs.collection_date}, "
                   f"analysis={lr.analysis_date}",
                   location_id=fs.location_id)

        # Matrix mismatch (only if both have a matrix value).
        if fs.matrix and lr.matrix and fs.matrix.upper() != lr.matrix.upper():
            flags.append(ReconciliationFlag(
                SampleID=sid, LocationID=fs.location_id,
                FlagType="MATRIX_MISMATCH",
                Severity=SEV_WARNING,
                Detail=f"Field matrix '{fs.matrix}' ≠ lab matrix '{lr.matrix}'",
            ))
            qa.add(SEV_WARNING, "matrix_mismatch",
                   f"Sample {sid!r}: field={fs.matrix!r}, lab={lr.matrix!r}",
                   location_id=fs.location_id)

    qa.add(SEV_INFO, "reconcile_complete",
           f"reconcile_field_and_lab: {len(field_samples)} field, "
           f"{len(lab_results)} lab rows → {len(flags)} flag(s)",
           )
    return flags
