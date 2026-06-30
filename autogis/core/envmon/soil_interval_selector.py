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


@dataclasses.dataclass
class _Item:
    sel: IntervalSelection
    screening: Optional[float]
    is_confirmation: bool


def _build_items(soil_rows: List[dict], rule: str,
                 qa: QACollector) -> List["_Item"]:
    """Build selections, carrying screening + confirmation with each row so no
    later step has to re-zip with soil_rows (which breaks once rows are skipped).
    Blank location_id and missing depths are surfaced as QA warnings."""
    items: List[_Item] = []
    for row in soil_rows:
        loc = str(row.get("location_id", "")).strip()
        if not loc:
            qa.add(SEV_WARNING, "blank_location_id",
                   "Soil row with blank location_id skipped")
            continue
        top = _f(row.get("depth_top"))
        bottom = _f(row.get("depth_bottom"))
        if top is None or bottom is None:
            qa.add(SEV_WARNING, "missing_depth",
                   f"{loc}/{str(row.get('analyte', '')).strip()}: missing depth "
                   f"interval; treated as 0 ft", location_id=loc)
        result = _f(row.get("result_value"))
        screening = _f(row.get("screening_level"))
        items.append(_Item(
            sel=IntervalSelection(
                location_id=loc,
                analyte=str(row.get("analyte", "")).strip(),
                depth_top=top if top is not None else 0.0,
                depth_bottom=bottom if bottom is not None else 0.0,
                result_value=result,
                exceeds=_exceeds(result, screening),
                selection_rule=rule),
            screening=screening,
            is_confirmation=bool(row.get("is_confirmation"))))
    return items


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

    items = _build_items(soil_rows, rule, qa)
    by_loc: Dict[str, List[_Item]] = {}
    for it in items:
        by_loc.setdefault(it.sel.location_id, []).append(it)

    selected: List[IntervalSelection] = []

    if rule == "all":
        selected = [it.sel for it in items]
    elif rule == "confirmation_only":
        selected = [it.sel for it in items if it.is_confirmation]
    elif rule == "interval_list":
        windows = interval_list or []
        selected = [it.sel for it in items
                    if any(wt <= it.sel.depth_top and it.sel.depth_bottom <= wb
                           for wt, wb in windows)]
    elif rule == "highest_result":
        best: Dict[Tuple[str, str], IntervalSelection] = {}
        for it in items:
            if it.sel.result_value is None:
                continue
            key = (it.sel.location_id, it.sel.analyte)
            cur = best.get(key)
            if cur is None or it.sel.result_value > cur.result_value:
                best[key] = it.sel
        selected = list(best.values())
    elif rule in ("shallowest", "deepest"):
        for loc, group in by_loc.items():
            if rule == "shallowest":
                anchor = min(it.sel.depth_top for it in group)
                selected.extend(it.sel for it in group
                                if it.sel.depth_top == anchor)
            else:
                anchor = max(it.sel.depth_bottom for it in group)
                selected.extend(it.sel for it in group
                                if it.sel.depth_bottom == anchor)
    elif rule == "highest_exceedance":
        for loc, group in by_loc.items():
            ranked = [(it, _ratio(it.sel.result_value, it.screening))
                      for it in group]
            ranked = [(it, r) for it, r in ranked if r is not None]
            if not ranked:
                qa.add(SEV_WARNING, "no_qualifying_interval",
                       f"{loc}: no interval has a screening level to rank by "
                       f"exceedance", location_id=loc)
                continue
            selected.append(max(ranked, key=lambda pair: pair[1])[0].sel)

    # Locations that contributed no selected row (the non-exceedance rules
    # already warn per location above).
    if rule != "highest_exceedance":
        kept_locs = {s.location_id for s in selected}
        for loc in by_loc:
            if loc not in kept_locs:
                qa.add(SEV_WARNING, "no_qualifying_interval",
                       f"{loc}: no interval qualified under rule {rule!r}",
                       location_id=loc)

    qa.add(SEV_INFO, "soil_intervals_selected",
           f"select_intervals[{rule}]: {len(selected)} of {len(items)} rows kept")
    return SelectionResult(selected=selected, rule=rule, qa=qa)
