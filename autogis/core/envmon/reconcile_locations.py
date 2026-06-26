"""ReconcileSampleLocations — pre-flight check that workbook location IDs match
the monitoring-well feature class (headless core, arcpy-free).

The core compares two lists of IDs and reports exact matches, unmatched
workbook IDs (with a fuzzy suggestion where one scores above threshold), and
wells that were never sampled. Read-only: it suggests, never modifies.
"""
from __future__ import annotations

import csv
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

_SEP = re.compile(r"[-_ ]+")


def normalize_id(value: str) -> str:
    return _SEP.sub("", str(value).strip().upper())


@dataclass
class Suggestion:
    workbook_id: str
    suggestion: Optional[str]
    score: float


@dataclass
class ReconcileResult:
    matches: List[str] = field(default_factory=list)
    unmatched_workbook: List[Suggestion] = field(default_factory=list)
    unmatched_wells: List[str] = field(default_factory=list)


def _best_match(target_norm: str, candidates: List[str]):
    best, score = None, 0.0
    for cand in candidates:
        ratio = difflib.SequenceMatcher(None, target_norm,
                                        normalize_id(cand)).ratio()
        if ratio > score:
            best, score = cand, ratio
    return best, score


def reconcile(workbook_ids: List[str], well_ids: List[str],
              threshold: float = 0.8) -> ReconcileResult:
    result = ReconcileResult()
    well_norms = {normalize_id(w) for w in well_ids}
    workbook_norms = set()

    seen = set()
    for wb in workbook_ids:
        nb = normalize_id(wb)
        workbook_norms.add(nb)
        if nb in seen:
            continue
        seen.add(nb)
        if nb in well_norms:
            result.matches.append(wb)
            continue
        best, score = _best_match(nb, well_ids)
        result.unmatched_workbook.append(
            Suggestion(workbook_id=wb,
                       suggestion=best if score >= threshold else None,
                       score=round(score, 3)))

    for w in well_ids:
        if normalize_id(w) not in workbook_norms:
            result.unmatched_wells.append(w)
    return result


def reconcile_to_qa(result: ReconcileResult) -> QACollector:
    qa = QACollector()
    for s in result.unmatched_workbook:
        if s.suggestion is not None:
            qa.add(QARecord(
                severity=SEV_WARNING, category="location_id_typo",
                message=(f"workbook location {s.workbook_id!r} has no exact "
                         f"well match"),
                recommended_action=(f"did you mean {s.suggestion!r}? "
                                    f"(similarity {s.score:.2f})"),
                location_id=str(s.workbook_id)))
        else:
            qa.add(QARecord(
                severity=SEV_ERROR, category="location_id_unmatched",
                message=(f"workbook location {s.workbook_id!r} matches no well "
                         f"(best similarity {s.score:.2f})"),
                recommended_action="add the well to the feature class or fix the "
                                   "workbook ID",
                location_id=str(s.workbook_id)))
    for w in result.unmatched_wells:
        qa.add(QARecord(severity=SEV_INFO, category="well_not_sampled",
                        message=f"well {w!r} has no sample in the workbook",
                        location_id=str(w)))
    qa.add(QARecord(
        severity=SEV_INFO, category="reconcile_complete",
        message=(f"Reconcile finished: {len(result.matches)} matched, "
                 f"{len(result.unmatched_workbook)} unmatched workbook ID(s), "
                 f"{len(result.unmatched_wells)} unsampled well(s).")))
    return qa


def extract_location_ids(reader, profile) -> List[str]:
    """Ordered, de-duplicated location IDs from every sheet's id_column."""
    ordered: List[str] = []
    seen = set()
    for sheet_profile in profile.sheets.values():
        col = sheet_profile.id_column or sheet_profile.sample_id_column
        if not col:
            continue
        if not reader.require_sheet(sheet_profile):
            continue
        for row in reader.iter_data_rows(sheet_profile):
            text = reader.cell(sheet_profile.sheet_name, row, col).raw_text.strip()
            if text and text not in seen:
                seen.add(text)
                ordered.append(text)
    return ordered


def read_well_ids_csv(path: Path) -> List[str]:
    rows = list(csv.reader(Path(path).open(newline="", encoding="utf-8")))
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    loc_idx = next((i for i, h in enumerate(header)
                    if h.lower() == "locationid"), None)
    if loc_idx is not None:
        data_rows, idx = rows[1:], loc_idx
    else:
        data_rows, idx = rows, 0          # no header match: treat all as data, col 0
    out: List[str] = []
    for r in data_rows:
        if len(r) > idx and r[idx].strip():
            out.append(r[idx].strip())
    return out
