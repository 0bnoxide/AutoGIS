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

import dataclasses
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

#: Default fraction preference, most-canonical first. "" (legacy /
#: unfractionated) never competes: single-fraction groups pass through.
DEFAULT_FRACTION_PREFERENCE: tuple[str, ...] = ("Total", "Dissolved")


def _group_key(r: dict) -> Tuple:
    # SiteID and Matrix included: this is the shared policy for consumers that
    # read the analytical table broadly, several of which do NOT pre-filter by
    # site/matrix. Two otherwise-identical sample/analyte rows from different
    # sites or matrices are distinct grains and must not resolve into one
    # (ADR-0075 P1).
    return (r.get("SiteID"), r.get("Matrix"),
            r.get("LocationID"), r.get("SampleID"), str(r.get("SampleDate")),
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
        location_id, analyte_name = key[2], key[5]
        qa.add(SEV_WARNING if pick not in fraction_preference else SEV_INFO,
               "fraction_resolved",
               f"{location_id} {analyte_name}: fractions {sorted(fracs)} "
               f"resolved to '{pick}' by the canonical-read policy.",
               location_id=location_id, analyte_name=analyte_name)

    out = [r for r in kept
           if _group_key(r) not in chosen
           or (r.get("ResultFraction") or "") == chosen[_group_key(r)]]
    return out


def canonical_records(
    records: Sequence,
    qa: QACollector,
    fraction_preference: Sequence[str] = DEFAULT_FRACTION_PREFERENCE,
) -> List:
    """Record-aware adapter for consumers that hold `AnalyticalResultRecord`
    dataclasses (from `read_records_csv`) rather than dicts. Applies the exact
    same policy as `canonical_result_rows` and returns the SAME record objects,
    order preserved — callers rely on identity / `dataclasses.replace`.

    `AnalyticalResultRecord` is flat (no nested dataclasses/lists), so `asdict`
    is safe and its field names already match `_group_key`; an `_i` sentinel
    survives the pure filter and maps surviving rows back to their records.
    """
    rows = [{**dataclasses.asdict(r), "_i": i} for i, r in enumerate(records)]
    kept = canonical_result_rows(rows, qa, fraction_preference)
    return [records[row["_i"]] for row in kept]
