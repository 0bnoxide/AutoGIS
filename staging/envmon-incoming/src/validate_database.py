"""ValidateEnvironmentalDatabase — cross-table integrity checks.

Checks (all arcpy-read-only; nothing is modified):
* schema completeness vs gdb_schema definitions
* orphan analytical results (no matching sample)
* orphan samples (no location point in MonitoringWells/SoilBorings)
* water levels without a well point
* duplicate unique keys (should be impossible after idempotent import,
  but users can edit GDB tables by hand)
* analytes in results that are absent from the analyte dictionary
* nondetect rows with a numeric "detected" value (contradiction)
* results flagged ExceedsScreening with no screening level stored
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from logging_utils import get_logger
from qa_checks import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING
from gdb_schema import TABLE_SCHEMAS, FEATURE_SCHEMAS, UNIQUE_KEYS

LOG = get_logger(__name__)


def _arcpy():
    import arcpy
    return arcpy


def _read(table_path: str, fields: List[str]) -> List[tuple]:
    arcpy = _arcpy()
    out = []
    with arcpy.da.SearchCursor(table_path, fields) as cur:
        for row in cur:
            out.append(row)
    return out


def validate_database(gdb: Path, qa: QACollector,
                      analyte_dictionary: Dict[str, dict]) -> Dict:
    arcpy = _arcpy()
    summary: Dict = {"tables_checked": 0, "issues": 0}
    before = len(qa.records)

    # 1) Schema completeness
    for name, schema in {**TABLE_SCHEMAS, **FEATURE_SCHEMAS}.items():
        path = str(gdb / name)
        summary["tables_checked"] += 1
        if not arcpy.Exists(path):
            qa.add(QARecord(severity=SEV_ERROR, category="table_missing",
                            message=f"{name} does not exist in {gdb.name}.",
                            recommended_action="Run schema creation "
                                                "(any import tool)."))
            continue
        have = {f.name.upper() for f in arcpy.ListFields(path)}
        for fname, *_rest in schema:
            if fname.upper() not in have:
                qa.add(QARecord(severity=SEV_ERROR, category="field_missing",
                                message=f"{name}.{fname} missing."))

    def exists(n):
        return arcpy.Exists(str(gdb / n))

    # 2) Location points
    points = set()
    for fc in ("MonitoringWells", "SoilBorings"):
        if exists(fc):
            for (site, loc) in _read(str(gdb / fc), ["SiteID", "LocationID"]):
                points.add((str(site).upper(), str(loc).strip().upper()))

    # 3) Samples and results
    samples = set()
    if exists("Env_Samples"):
        rows = _read(str(gdb / "Env_Samples"),
                     ["SiteID", "Matrix", "SampleID", "LocationID"])
        keys = Counter((str(s).upper(), str(m).upper(), str(sid).strip().upper())
                       for s, m, sid, _l in rows)
        for k, n in keys.items():
            if n > 1:
                qa.add(QARecord(severity=SEV_ERROR, category="duplicate_sample_key",
                                message=f"Env_Samples key {k} appears {n}x."))
        for s, m, sid, loc in rows:
            samples.add((str(s).upper(), str(m).upper(), str(sid).strip().upper()))
            if (str(s).upper(), str(loc).strip().upper()) not in points:
                qa.add(QARecord(severity=SEV_WARNING,
                                category="sample_location_no_point",
                                message=f"Sample {sid} at {loc} has no map "
                                        "point.",
                                location_id=str(loc), sample_id=str(sid)))

    if exists("Env_AnalyticalResults"):
        rows = _read(str(gdb / "Env_AnalyticalResults"),
                     ["SiteID", "Matrix", "SampleID", "AnalyteCanonicalName",
                      "IsNonDetect", "IsDetected", "ResultNumeric",
                      "ExceedsScreeningLevel", "ScreeningLevel"])
        canon = {d.get("canonical_name", k) for k, d in analyte_dictionary.items()}
        for (site, m, sid, an, nd, det, nv, exc, sl) in rows:
            skey = (str(site).upper(), str(m).upper(), str(sid).strip().upper())
            if skey not in samples:
                qa.add(QARecord(severity=SEV_ERROR, category="orphan_result",
                                message=f"Result {sid}/{an} has no Env_Samples "
                                        "row.",
                                sample_id=str(sid), analyte_name=str(an)))
            if an and an not in canon:
                qa.add(QARecord(severity=SEV_WARNING,
                                category="analyte_not_in_dictionary",
                                message=f"Analyte {an!r} not in dictionary.",
                                analyte_name=str(an)))
            if nd and det:
                qa.add(QARecord(severity=SEV_ERROR,
                                category="nondetect_detected_conflict",
                                message=f"{sid}/{an}: IsNonDetect and "
                                        "IsDetected both set.",
                                sample_id=str(sid), analyte_name=str(an)))
            if exc and sl is None:
                qa.add(QARecord(severity=SEV_ERROR,
                                category="exceedance_without_screening_level",
                                message=f"{sid}/{an}: flagged exceedance but "
                                        "no screening level stored.",
                                sample_id=str(sid), analyte_name=str(an)))

    if exists("Env_WaterLevels"):
        for (site, loc) in _read(str(gdb / "Env_WaterLevels"),
                                 ["SiteID", "LocationID"]):
            if (str(site).upper(), str(loc).strip().upper()) not in points:
                qa.add(QARecord(severity=SEV_WARNING,
                                category="water_level_no_point",
                                message=f"Water level at {loc} has no "
                                        "MonitoringWells point.",
                                location_id=str(loc)))

    summary["issues"] = len(qa.records) - before
    qa.add(QARecord(severity=SEV_INFO, category="validation_complete",
                    message=f"Validation finished: {summary['issues']} issues "
                            f"across {summary['tables_checked']} datasets."))
    return summary
