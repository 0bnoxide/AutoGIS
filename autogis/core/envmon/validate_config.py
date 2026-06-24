"""ValidateEnvConfig — per-bundle config integrity checks (headless, arcpy-free).

Loads the explicit (site, parser profiles, figure specs, analyte dictionary,
screening levels) bundle a run would use, runs every validator into a single
QACollector, and adds a closing INFO summary record. File loads are defensive:
a failure becomes an ERROR record rather than an exception, so one bad file
never hides problems in the others.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..common import config_validation as cv
from ..common.config import (load_analyte_dictionary, load_config,
                             load_screening_levels)
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO


def _safe(qa: QACollector, label: str, fn):
    try:
        return fn()
    except Exception as exc:  # ConfigError, yaml errors, etc.
        qa.add(QARecord(severity=SEV_ERROR, category="load_error",
                        message=f"could not load {label}: {exc}"))
        return None


def validate_env_config(site_path: Optional[Path],
                        profile_paths: Optional[List[Path]],
                        figure_paths: Optional[List[Path]],
                        analytes_path: Optional[Path],
                        screening_path: Optional[Path]) -> QACollector:
    qa = QACollector()
    figure_specs: List[dict] = []
    analytes: dict = {}
    screening: dict = {}

    if site_path:
        data = _safe(qa, f"site config {Path(site_path).name}",
                     lambda: load_config(Path(site_path)))
        if data is not None:
            qa.extend(cv.validate_site(data))

    for pp in profile_paths or []:
        data = _safe(qa, f"parser profile {Path(pp).name}",
                     lambda pp=pp: load_config(Path(pp)))
        if data is not None:
            qa.extend(cv.validate_parser_profile(data))

    for fp in figure_paths or []:
        data = _safe(qa, f"figure spec {Path(fp).name}",
                     lambda fp=fp: load_config(Path(fp)))
        if data is not None:
            figure_specs.append(data)
            qa.extend(cv.validate_figure_spec(data))

    if analytes_path:
        analytes = _safe(qa, f"analyte dictionary {Path(analytes_path).name}",
                         lambda: load_analyte_dictionary(Path(analytes_path))) or {}
        if analytes:
            qa.extend(cv.validate_analyte_dictionary(analytes))

    if screening_path:
        screening = _safe(qa, f"screening levels {Path(screening_path).name}",
                          lambda: load_screening_levels(Path(screening_path))) or {}
        if screening:
            qa.extend(cv.validate_screening_levels(screening))

    # Cross-file checks only run when the dictionary is present to compare against.
    if analytes:
        qa.extend(cv.validate_bundle(figure_specs, screening, analytes))
    else:
        qa.add(QARecord(severity=SEV_INFO, category="cross_file_skipped",
                        message="analyte dictionary not supplied; cross-file "
                                "reference checks skipped",
                        recommended_action="pass --analytes to enable figure/"
                                           "screening reference validation"))

    counts = qa.counts_by_severity()
    qa.add(QARecord(severity=SEV_INFO, category="validation_complete",
                    message=(f"Config validation finished: "
                             f"{counts.get('ERROR', 0)} error(s), "
                             f"{counts.get('WARNING', 0)} warning(s).")))
    return qa
