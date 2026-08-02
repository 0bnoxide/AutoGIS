"""reconcile_survey123_lab.py — two-way Survey123 field vs lab EDD sample reconciliation."""
from __future__ import annotations

import csv
import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO
from .sample_id import qc_class

DEFAULT_HEADER_MAP = {
    "sample_id": "SampleID",
    "location_id": "LocationID",
    "sample_date": "SamplingDate",
    "matrix": "Matrix",
    "sampled_by": "SampledBy",
}


@dataclass
class Survey123Sample:
    sample_id: str
    location_id: str
    sample_date: str
    matrix: str
    sampled_by: str = ""


@dataclass
class LabSample:
    sample_id: str
    location_id: str
    sample_date: str
    matrix: str
    analyte_count: int = 0


@dataclass
class ReconcileS123LabResult:
    matched: list[tuple[Survey123Sample, LabSample]] = field(default_factory=list)
    field_only: list[Survey123Sample] = field(default_factory=list)
    lab_only: list[LabSample] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def load_survey123_csv(
    path: Path,
    header_map: Optional[dict[str, str]] = None,
) -> list[Survey123Sample]:
    hm = {**DEFAULT_HEADER_MAP, **(header_map or {})}
    out: list[Survey123Sample] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(Survey123Sample(
                sample_id=row.get(hm["sample_id"], ""),
                location_id=row.get(hm["location_id"], ""),
                sample_date=row.get(hm["sample_date"], ""),
                matrix=row.get(hm["matrix"], ""),
                sampled_by=row.get(hm["sampled_by"], ""),
            ))
    return out


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def reconcile_field_lab(
    field_samples: list[Survey123Sample],
    lab_samples: list[LabSample],
    threshold: float = 0.85,
    duplicate_markers: Optional[list[str]] = None,
) -> ReconcileS123LabResult:
    """Match field submissions to lab records.

    duplicate_markers: the parser profile's markers, used to recognize a
    laboratory duplicate that is not a lifecycle identity (this repo's
    profiles ship ``-DUP``/``-D``). Defaults to the same list the profiles do.
    """
    result = ReconcileS123LabResult()
    unmatched_lab = list(lab_samples)

    # Two passes, not one interleaved pass (#395): every exact match is
    # resolved across *all* field samples before any fuzzy match consumes a
    # lab record. Single-pass matching let an earlier typo'd ID fuzzy-claim
    # the lab record that a later field sample matched exactly, silently
    # pairing the wrong two and reporting the true owner as field_only.
    exact_by_index: dict[int, LabSample] = {}
    for i, fs in enumerate(field_samples):
        exact = next((ls for ls in unmatched_lab if ls.sample_id == fs.sample_id), None)
        if exact:
            unmatched_lab.remove(exact)
            exact_by_index[i] = exact

    # Pass 2 walks field samples in input order so matched/field_only keep
    # their original ordering.
    for i, fs in enumerate(field_samples):
        exact = exact_by_index.get(i)
        if exact:
            _check_pair(result, fs, exact)
            continue
        # fuzzy match - consider all unmatched lab samples, except that a
        # structural guard runs before any similarity score: IDs of different
        # QC class can never match, whichever side carries the marker. A
        # duplicate must not consume its own primary (~0.914 for -FD, 0.889
        # for -DUP, 0.941 for -D — all above the 0.85 threshold). Comparing
        # the QC *class* rather than the raw suffix keeps -FD/-FD-A and
        # -FD/-DUP matchable while still separating -MB from -FB.
        fs_class = qc_class(fs.sample_id, duplicate_markers)
        candidates = unmatched_lab
        if fs_class is not None:
            candidates = [
                ls for ls in unmatched_lab
                if (lc := qc_class(ls.sample_id, duplicate_markers)) is None
                or lc == fs_class
            ]
        best_score, best = max(
            ((_sim(fs.sample_id, ls.sample_id), ls) for ls in candidates),
            key=lambda x: x[0],
            default=(0.0, None),
        )
        if best and best_score >= threshold:
            unmatched_lab.remove(best)
            result.flags.append(
                f"sample_id_mismatch: field={fs.sample_id!r} lab={best.sample_id!r}")
            _check_pair(result, fs, best)
        else:
            result.field_only.append(fs)

    result.lab_only.extend(unmatched_lab)
    return result


def _check_pair(result: ReconcileS123LabResult,
                fs: Survey123Sample, ls: LabSample) -> None:
    result.matched.append((fs, ls))
    if fs.sample_date != ls.sample_date:
        result.flags.append(
            f"date_mismatch: field={fs.sample_date} lab={ls.sample_date} "
            f"sample={fs.sample_id}")
    if fs.matrix.upper() != ls.matrix.upper():
        result.flags.append(
            f"matrix_mismatch: field={fs.matrix} lab={ls.matrix} "
            f"sample={fs.sample_id}")
    if fs.location_id.upper() != ls.location_id.upper():
        result.flags.append(
            f"location_mismatch: field={fs.location_id} lab={ls.location_id} "
            f"sample={fs.sample_id}")


def reconcile_to_qa(result: ReconcileS123LabResult) -> QACollector:
    qa = QACollector()
    for flag in result.flags:
        if "matrix_mismatch" in flag:
            sev, cat = SEV_ERROR, "matrix_mismatch"
        elif "sample_id_mismatch" in flag:
            sev, cat = SEV_WARNING, "sample_id_mismatch"
        elif "date_mismatch" in flag:
            sev, cat = SEV_WARNING, "date_mismatch"
        elif "location_mismatch" in flag:
            sev, cat = SEV_WARNING, "location_mismatch"
        else:
            sev, cat = SEV_INFO, "unknown_flag"
        qa.add(QARecord(severity=sev, category=cat, message=flag))
    for fs in result.field_only:
        qa.add(QARecord(SEV_WARNING, "field_only_sample",
                        f"Field sample {fs.sample_id!r} has no lab result."))
    for ls in result.lab_only:
        qa.add(QARecord(SEV_WARNING, "lab_only_sample",
                        f"Lab sample {ls.sample_id!r} has no field submission."))
    qa.add(QARecord(SEV_INFO, "reconcile_complete",
                    f"Matched: {len(result.matched)}  "
                    f"Field-only: {len(result.field_only)}  "
                    f"Lab-only: {len(result.lab_only)}"))
    return qa
