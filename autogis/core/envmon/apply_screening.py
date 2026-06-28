"""Re-evaluate ExceedsScreeningLevel on existing records (Tool 3.5)."""
from __future__ import annotations
import dataclasses
from typing import List
from .gdb_schema import AnalyticalResultRecord
from ..common.units import same_dimension, convert
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


def apply_screening_levels(
    results: List[AnalyticalResultRecord],
    screening_levels: dict,
    *,
    qa: QACollector,
) -> List[AnalyticalResultRecord]:
    """Re-evaluate ExceedsScreeningLevel using unit-conversion gate.

    screening_levels format:
        {canonical_name: {matrix: {"unit": str, "level": float, "source": str}}}

    Returns new AnalyticalResultRecord instances with updated screening fields.
    Records with no matching screening entry are returned unchanged.
    """
    updated = []
    changed = 0
    for r in results:
        sl_entry = (screening_levels
                    .get(r.AnalyteCanonicalName, {})
                    .get(r.Matrix, {}))
        if not sl_entry:
            updated.append(r)
            continue
        sl_val = sl_entry.get("level")
        sl_unit = sl_entry.get("unit", r.Units)
        sl_source = sl_entry.get("source", "")
        if sl_val is None:
            updated.append(r)
            continue
        result_val = r.ResultNumeric
        if result_val is None:
            # Non-detect never exceeds screening level.
            new_exceed = 0
        elif r.Units != sl_unit:
            try:
                if not same_dimension(r.Units, sl_unit):
                    raise ValueError(
                        f"incompatible dimensions: {r.Units!r} vs {sl_unit!r}")
                result_val = convert(result_val, r.Units, sl_unit)
                new_exceed = 1 if result_val > sl_val else 0
            except Exception as exc:
                qa.add(SEV_WARNING, "unit_conversion_failed",
                       f"{r.LocationID}/{r.AnalyteCanonicalName}: {exc}",
                       location_id=r.LocationID,
                       analyte_name=r.AnalyteCanonicalName)
                updated.append(r)
                continue
        else:
            new_exceed = 1 if result_val > sl_val else 0
        color = {1: "EXCEED", 0: "OK"}.get(new_exceed, "UNKNOWN")
        new_r = dataclasses.replace(
            r,
            ScreeningLevel=sl_val,
            ScreeningLevelSource=sl_source,
            ExceedsScreeningLevel=new_exceed,
            DisplayColorClass=color,
        )
        if new_r != r:
            changed += 1
        updated.append(new_r)
    qa.add(SEV_INFO, "apply_screening_complete",
           f"apply_screening_levels: {changed} record(s) updated out of {len(results)}")
    return updated
