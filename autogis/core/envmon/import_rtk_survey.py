"""import_rtk_survey.py — parse RTK survey CSV → SurveyPoints_Raw/QA GDB tables."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RTKColumnMap:
    point_id: str = "PointID"
    northing: str = "Northing"
    easting: str = "Easting"
    elevation_ft: str = "Elevation_ft"
    feature_code: str = "FeatureCode"
    description: str = "Description"
    hrms_ft: str = "HRMS_ft"
    vrms_ft: str = "VRMS_ft"
    fix_type: str = "FixType"
    collected_at: str = "CollectedAt"
    operator: str = "Operator"

    RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


@dataclass
class RTKPoint:
    point_id: str
    northing: float
    easting: float
    elevation_ft: float
    feature_code: str = ""
    description: str = ""
    hrms_ft: Optional[float] = None
    vrms_ft: Optional[float] = None
    fix_type: str = ""
    collected_at: str = ""
    operator: str = ""


def _f(row, key, default=None):
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def parse_rtk_csv(
    path: Path,
    column_map: Optional[RTKColumnMap] = None,
) -> list[RTKPoint]:
    cm = column_map or RTKColumnMap()
    out: list[RTKPoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            n = _f(row, cm.northing)
            e = _f(row, cm.easting)
            z = _f(row, cm.elevation_ft)
            if n is None or e is None or z is None:
                continue
            out.append(RTKPoint(
                point_id=row.get(cm.point_id, "").strip(),
                northing=n, easting=e, elevation_ft=z,
                feature_code=row.get(cm.feature_code, "").strip(),
                description=row.get(cm.description, "").strip(),
                hrms_ft=_f(row, cm.hrms_ft),
                vrms_ft=_f(row, cm.vrms_ft),
                fix_type=row.get(cm.fix_type, "").strip(),
                collected_at=row.get(cm.collected_at, "").strip(),
                operator=row.get(cm.operator, "").strip(),
            ))
    return out


_RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


def assign_qa_flags(
    point: RTKPoint,
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> list[str]:
    flags: list[str] = []
    if point.hrms_ft is not None and point.hrms_ft > hrms_threshold_ft:
        flags.append("hrms_exceeds_threshold")
    if point.vrms_ft is not None and point.vrms_ft > vrms_threshold_ft:
        flags.append("vrms_exceeds_threshold")
    if point.fix_type and point.fix_type.upper() not in _RTK_FIX_TYPES:
        flags.append("fix_type_not_rtk")
    return flags


def import_rtk_survey(    # pragma: no cover
    gdb_path: str,
    site_id: str,
    batch_id: str,
    points: list[RTKPoint],
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> None:
    """Write RTKPoint list to SurveyPoints_Raw and SurveyPoints_QA (ArcGIS Pro)."""
    import arcpy
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    raw_table = str(_P(gdb) / "SurveyPoints_Raw")
    qa_table = str(_P(gdb) / "SurveyPoints_QA")
    import json

    if _ax.Exists(raw_table):
        with _ax.da.InsertCursor(raw_table,
                                 ["PointID", "Northing", "Easting", "Elevation_ft",
                                  "FeatureCode", "Description", "HRMS_ft", "VRMS_ft",
                                  "FixType", "CollectedAt", "Operator"]) as cur:
            for pt in points:
                cur.insertRow([pt.point_id, pt.northing, pt.easting, pt.elevation_ft,
                               pt.feature_code, pt.description, pt.hrms_ft, pt.vrms_ft,
                               pt.fix_type, pt.collected_at, pt.operator])

    if _ax.Exists(qa_table):
        with _ax.da.InsertCursor(qa_table,
                                 ["PointID", "QAStatus", "QAFlags", "Approved"]) as cur:
            for pt in points:
                flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
                status = "FAIL" if flags else "PASS"
                cur.insertRow([pt.point_id, status, json.dumps(flags), 0])
