"""manage_screening_levels.py — validate screening_levels.yaml (headless)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.config import load_config
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING


@dataclass
class ScreeningEntry:
    analyte: str
    matrix: str
    value: Optional[float]
    units: str
    source: str


def load_screening_entries(path: Path) -> list[ScreeningEntry]:
    data = load_config(path)
    sl = data.get("screening_levels", {})
    out: list[ScreeningEntry] = []
    for matrix, analytes in sl.items():
        for analyte, entry in (analytes or {}).items():
            v = entry.get("value") if isinstance(entry, dict) else None
            u = entry.get("units", "") if isinstance(entry, dict) else ""
            s = entry.get("source", "") if isinstance(entry, dict) else ""
            out.append(ScreeningEntry(analyte=analyte, matrix=matrix,
                                      value=v, units=u, source=s))
    return out


def check_screening_levels(
    screening_path: Path,
    analytes_path: Optional[Path] = None,
) -> QACollector:
    qa = QACollector()
    data = load_config(screening_path)
    sl = data.get("screening_levels", {})

    for matrix, analytes in sl.items():
        for analyte, entry in (analytes or {}).items():
            ctx = f"{matrix}/{analyte}"
            if not isinstance(entry, dict):
                qa.add(QARecord(SEV_ERROR, "invalid_entry",
                                f"{ctx}: expected a mapping, got {type(entry).__name__}"))
                continue
            for key in ("value", "units", "source"):
                if key not in entry:
                    qa.add(QARecord(SEV_ERROR, "missing_entry_key",
                                    f"{ctx}: missing required key '{key}'"))
            source = entry.get("source", "")
            value = entry.get("value")
            if value is None:
                qa.add(QARecord(SEV_WARNING, "null_value",
                                f"{ctx}: value is null (pre-production stub)"))
            if "_TODO" in str(source):
                qa.add(QARecord(SEV_WARNING, "placeholder_source",
                                f"{ctx}: source contains _TODO: {source!r}",
                                recommended_action="Replace with citation before production use"))

    if analytes_path is not None:
        analytes_data = load_config(analytes_path)
        covered: set[tuple[str, str]] = set()
        for matrix, ents in sl.items():
            for analyte in (ents or {}):
                covered.add((analyte, matrix))
        for analyte, info in analytes_data.items():
            matrices = info.get("default_units_by_matrix", {}) if isinstance(info, dict) else {}
            for matrix in matrices:
                if (analyte, matrix) not in covered:
                    qa.add(QARecord(SEV_WARNING, "analyte_not_covered",
                                    f"Analyte {analyte!r} has no screening level for matrix {matrix}",
                                    recommended_action="Add entry to screening_levels.yaml or mark null"))

    counts = qa.counts_by_severity()
    sev = SEV_WARNING if counts.get("ERROR") else SEV_INFO
    qa.add(QARecord(sev, "validation_complete",
                    f"Screening levels check: {counts.get('ERROR', 0)} error(s), "
                    f"{counts.get('WARNING', 0)} warning(s)"))
    return qa
