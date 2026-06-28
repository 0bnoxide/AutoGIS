"""Validate a monitoring schedule YAML (Tool 10.2 extension)."""
from __future__ import annotations
from typing import Dict, Any, Optional, Set
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def validate_schedule(
    schedule: Dict[str, Any],
    analyte_dict: Optional[Set[str]],
    *,
    qa: QACollector,
) -> bool:
    """Validate schedule dict; return True if no ERRORs emitted."""
    errors_before = sum(1 for r in qa.records
                        if r.severity in ("ERROR", "CRITICAL"))

    site_id = schedule.get("site_id", "")
    if not site_id:
        qa.add(SEV_ERROR, "missing_site_id", "Schedule missing 'site_id'")

    event_label = schedule.get("event_label", "")
    if not event_label:
        qa.add(SEV_ERROR, "missing_event_label", "Schedule missing 'event_label'")

    wells = schedule.get("wells") or []
    if not wells:
        qa.add(SEV_ERROR, "missing_wells", "Schedule 'wells' is absent or empty")
    else:
        seen: Set[str] = set()
        for w in wells:
            if w in seen:
                qa.add(SEV_WARNING, "duplicate_well",
                       f"Duplicate well ID {w!r} in wells list",
                       site_id=site_id)
            seen.add(w)

    required_analytes = schedule.get("required_analytes") or []
    if not required_analytes:
        qa.add(SEV_WARNING, "no_required_analytes",
               "Schedule has no required_analytes; all wells count as sampled",
               site_id=site_id)
    elif analyte_dict:
        for a in required_analytes:
            if a not in analyte_dict:
                qa.add(SEV_WARNING, "unknown_analyte",
                       f"Analyte {a!r} not in analyte dictionary",
                       site_id=site_id, analyte_name=a)

    well_analytes = schedule.get("well_analytes") or {}
    well_set = set(wells)
    for w, analytes in well_analytes.items():
        if w not in well_set:
            qa.add(SEV_WARNING, "unknown_well_in_overrides",
                   f"well_analytes key {w!r} not in wells list",
                   site_id=site_id)
        if analyte_dict:
            for a in (analytes or []):
                if a not in analyte_dict:
                    qa.add(SEV_WARNING, "unknown_analyte",
                           f"Analyte {a!r} in well_analytes override not in dict",
                           site_id=site_id, analyte_name=a)

    errors_after = sum(1 for r in qa.records
                       if r.severity in ("ERROR", "CRITICAL"))
    new_errors = errors_after - errors_before
    qa.add(SEV_INFO, "validate_schedule_complete",
           f"Schedule validation for {site_id!r} event {event_label!r}: "
           f"{new_errors} error(s)")
    return new_errors == 0
