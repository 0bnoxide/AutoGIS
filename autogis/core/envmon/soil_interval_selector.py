"""Select soil depth intervals for analytical map callouts (Tool 4.8).

A boring has many sampled intervals; a map callout can show only a few. This
headless selector applies one defensible rule and records that rule per kept
row, for auditability. Emits the selection table consumed by build-callouts
(arcpy); builds no map graphics itself.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Dict, List, Optional, Tuple

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

SELECTION_RULES = (
    "all", "shallowest", "deepest", "highest_result",
    "highest_exceedance", "interval_list", "confirmation_only",
)


@dataclasses.dataclass
class IntervalSelection:
    location_id: str
    analyte: str
    depth_top: float
    depth_bottom: float
    result_value: Optional[float]
    exceeds: bool
    selection_rule: str


@dataclasses.dataclass
class SelectionResult:
    selected: List[IntervalSelection]
    rule: str
    qa: QACollector


def _f(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _exceeds(result: Optional[float], screening: Optional[float]) -> bool:
    # is-not-None guards: a screening level of exactly 0.0 is a real threshold,
    # not "missing" (#82 bug class).
    return (result is not None and screening is not None
            and result > screening)


def _ratio(result: Optional[float], screening: Optional[float]) -> Optional[float]:
    """Exceedance ratio result/screening. A 0.0 screening with a positive
    result is an infinite exceedance (ranks highest); no screening -> None."""
    if result is None or screening is None:
        return None
    if screening == 0:
        return math.inf if result > 0 else 0.0
    return result / screening


def _to_selection(row: dict, rule: str) -> IntervalSelection:
    result = _f(row.get("result_value"))
    screening = _f(row.get("screening_level"))
    return IntervalSelection(
        location_id=str(row.get("location_id", "")).strip(),
        analyte=str(row.get("analyte", "")).strip(),
        depth_top=_f(row.get("depth_top")) or 0.0,
        depth_bottom=_f(row.get("depth_bottom")) or 0.0,
        result_value=result,
        exceeds=_exceeds(result, screening),
        selection_rule=rule,
    )


def select_intervals(
    soil_rows: List[dict],
    *,
    rule: str = "highest_exceedance",
    interval_list: Optional[List[Tuple[float, float]]] = None,
    qa: Optional[QACollector] = None,
) -> SelectionResult:
    """Apply the selection rule; record the rule on each kept row."""
    if rule not in SELECTION_RULES:
        raise ValueError(
            f"unknown rule {rule!r}; expected one of {SELECTION_RULES}")
    if qa is None:
        qa = QACollector()

    sels = [_to_selection(r, rule) for r in soil_rows]
    # Group by location for the per-location rules.
    by_loc: Dict[str, List[IntervalSelection]] = {}
    for s in sels:
        by_loc.setdefault(s.location_id, []).append(s)

    selected: List[IntervalSelection] = []

    if rule == "all":
        selected = list(sels)
    elif rule == "confirmation_only":
        flags = [bool(r.get("is_confirmation")) for r in soil_rows]
        selected = [s for s, keep in zip(sels, flags) if keep]
    elif rule == "interval_list":
        windows = interval_list or []
        for s in sels:
            if any(wt <= s.depth_top and s.depth_bottom <= wb
                   for wt, wb in windows):
                selected.append(s)
    elif rule == "highest_result":
        best: Dict[Tuple[str, str], IntervalSelection] = {}
        for s in sels:
            if s.result_value is None:
                continue
            key = (s.location_id, s.analyte)
            cur = best.get(key)
            if cur is None or s.result_value > cur.result_value:
                best[key] = s
        selected = list(best.values())
    elif rule in ("shallowest", "deepest"):
        for loc, group in by_loc.items():
            if rule == "shallowest":
                anchor = min(g.depth_top for g in group)
                selected.extend(g for g in group if g.depth_top == anchor)
            else:
                anchor = max(g.depth_bottom for g in group)
                selected.extend(g for g in group if g.depth_bottom == anchor)
    elif rule == "highest_exceedance":
        # one row per location: the max exceedance ratio.
        ratios = {id(s): _ratio(s.result_value,
                                _f(r.get("screening_level")))
                  for s, r in zip(sels, soil_rows)}
        for loc, group in by_loc.items():
            ranked = [g for g in group if ratios[id(g)] is not None]
            if not ranked:
                qa.add(SEV_WARNING, "no_qualifying_interval",
                       f"{loc}: no interval has a screening level to rank by "
                       f"exceedance", location_id=loc)
                continue
            selected.append(max(ranked, key=lambda g: ratios[id(g)]))

    # Locations that contributed no selected row (other rules).
    if rule not in ("highest_exceedance",):
        kept_locs = {s.location_id for s in selected}
        for loc in by_loc:
            if loc not in kept_locs:
                qa.add(SEV_WARNING, "no_qualifying_interval",
                       f"{loc}: no interval qualified under rule {rule!r}",
                       location_id=loc)

    qa.add(SEV_INFO, "soil_intervals_selected",
           f"select_intervals[{rule}]: {len(selected)} of {len(sels)} rows kept")
    return SelectionResult(selected=selected, rule=rule, qa=qa)
