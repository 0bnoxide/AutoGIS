"""Shared canonical-read policy for the widened Env_AnalyticalResults grain.

After Step 1, one (sample, analyte, depth) may legitimately hold multiple
rows split by ResultFraction / QCType / MethodDilutionKey. Every consumer
that pivots or groups results by analyte must read through this helper or
it will double-count / silently drop data the moment Step 2 imports real
WQX fractions (ADR-0075). Step-1 policy: drop lab/field-QC-flagged rows,
resolve each group to a single fraction. MethodDilutionKey rerun
disambiguation (IsReportable) is deferred to Step 3.

arcpy-free: operates on plain row dicts.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

#: Default fraction preference, most-canonical first. "" (legacy /
#: unfractionated) never competes: single-fraction groups pass through.
DEFAULT_FRACTION_PREFERENCE: tuple[str, ...] = ("Total", "Dissolved")


def _group_key(r: dict) -> Tuple:
    return (r.get("LocationID"), r.get("SampleID"), str(r.get("SampleDate")),
            r.get("AnalyteCanonicalName"),
            str(r.get("DepthIntervalText") or ""))


def canonical_result_rows(
    rows: Sequence[dict],
    qa: QACollector,
    fraction_preference: Sequence[str] = DEFAULT_FRACTION_PREFERENCE,
) -> List[dict]:
    """Return rows filtered to the canonical-read policy (order preserved)."""
    kept: List[dict] = []
    qc_dropped = 0
    for r in rows:
        if (r.get("QCType") or ""):
            qc_dropped += 1
            continue
        kept.append(r)
    if qc_dropped:
        qa.add(SEV_INFO, "qc_rows_excluded",
               f"{qc_dropped} QCType-flagged row(s) excluded by the "
               "canonical-read policy.")

    fractions_by_group: Dict[Tuple, set] = defaultdict(set)
    for r in kept:
        fractions_by_group[_group_key(r)].add(r.get("ResultFraction") or "")

    chosen: Dict[Tuple, str] = {}
    for key, fracs in fractions_by_group.items():
        if len(fracs) == 1:
            continue                      # nothing to resolve
        pick = next((p for p in fraction_preference if p in fracs),
                    sorted(fracs)[0])
        chosen[key] = pick
        qa.add(SEV_WARNING if pick not in fraction_preference else SEV_INFO,
               "fraction_resolved",
               f"{key[0]} {key[3]}: fractions {sorted(fracs)} resolved to "
               f"'{pick}' by the canonical-read policy.",
               location_id=key[0], analyte_name=key[3])

    out = [r for r in kept
           if _group_key(r) not in chosen
           or (r.get("ResultFraction") or "") == chosen[_group_key(r)]]
    return out
