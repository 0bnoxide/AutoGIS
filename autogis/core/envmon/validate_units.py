"""ValidateAndConvertUnits — config unit-integrity checks (headless, arcpy-free).

Loads the analyte dictionary and screening-level configs, runs the pure
``validate_units`` validator into a single QACollector, and adds a closing INFO
summary. File loads are defensive (a failure becomes an ERROR record rather than
an exception), reusing ``validate_config.safe_load``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..common import config_validation as cv
from ..common.config import load_analyte_dictionary, load_screening_levels
from ..common.qa import QACollector, QARecord, SEV_INFO
from .validate_config import safe_load


def validate_units_config(analytes_path: Optional[Path],
                          screening_path: Optional[Path]) -> QACollector:
    qa = QACollector()
    analytes: dict = {}
    screening: dict = {}

    if analytes_path:
        analytes = safe_load(qa, f"analyte dictionary {Path(analytes_path).name}",
                         lambda: load_analyte_dictionary(Path(analytes_path))) or {}
    if screening_path:
        screening = safe_load(qa, f"screening levels {Path(screening_path).name}",
                          lambda: load_screening_levels(Path(screening_path))) or {}

    if analytes or screening:
        qa.extend(cv.validate_units(analytes, screening))

    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="validation_complete",
                    message=(f"Unit validation finished: "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa
