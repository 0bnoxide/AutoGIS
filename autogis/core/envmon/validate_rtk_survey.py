"""validate_rtk_survey.py — RTK QA checks (arcpy-free).

Operates on list[RTKPoint] from import_rtk_survey.parse_rtk_csv().
"""
from __future__ import annotations

from collections import Counter

from .import_rtk_survey import RTKPoint, assign_qa_flags
from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_WARNING, SEV_INFO

_RTK_FIX_TYPES = frozenset({"RTK_FIXED", "RTK_FLOAT", "NETWORK_RTK"})


def validate_rtk_points(
    points: list[RTKPoint],
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
) -> QACollector:
    qa = QACollector()

    if not points:
        qa.add(QARecord(SEV_INFO, "validation_complete",
                        "RTK validation: 0 points — nothing to check."))
        return qa

    # Duplicate point IDs
    id_counts = Counter(p.point_id for p in points)
    for pid, n in id_counts.items():
        if n > 1:
            qa.add(QARecord(SEV_WARNING, "duplicate_point_id",
                            f"PointID {pid!r} appears {n} times."))

    # Per-point QA
    passed = 0
    for pt in points:
        flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
        if not flags:
            passed += 1
            continue
        for flag in flags:
            qa.add(QARecord(SEV_WARNING, flag,
                            f"{pt.point_id}: {flag} "
                            f"(HRMS={pt.hrms_ft}, VRMS={pt.vrms_ft}, "
                            f"FixType={pt.fix_type})"))

    qa.add(QARecord(SEV_INFO, "validation_complete",
                    f"RTK validation: {passed}/{len(points)} points QA pass."))
    return qa
