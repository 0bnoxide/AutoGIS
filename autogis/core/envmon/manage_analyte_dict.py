"""ManageAnalyteDictionary — read-only curation/validation of the analyte
dictionary (headless, arcpy-free). Never writes the YAML; edits stay manual.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from ..common import config_validation as cv
from ..common.config import load_analyte_dictionary
from ..common.qa import QACollector, QARecord, SEV_INFO


def _clean(path: Path) -> dict:
    analytes = load_analyte_dictionary(Path(path))
    return {k: v for k, v in analytes.items() if not str(k).startswith("_")}


def check_analyte_dictionary(path: Path) -> QACollector:
    qa = QACollector()
    analytes = _clean(path)
    qa.extend(cv.validate_analyte_dictionary(analytes))
    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="check_complete",
                    message=(f"Analyte dictionary check finished: "
                             f"{len(analytes)} analytes, "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa


def list_analytes(path: Path) -> List[dict]:
    analytes = _clean(path)
    rows = []
    for canonical, entry in analytes.items():
        rows.append({
            "canonical": canonical,
            "abbreviation": entry.get("abbreviation", ""),
            "analytical_group": entry.get("analytical_group", ""),
            "display_order": entry.get("display_order", 9999),
            "alias_count": len(entry.get("aliases", []) or []),
            "include_in_default_figures": entry.get("include_in_default_figures",
                                                    False),
        })
    rows.sort(key=lambda r: (r["display_order"], r["canonical"]))
    return rows
