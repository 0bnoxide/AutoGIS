"""Generate a planned sampling event plan (Tool 7.2).

Headless, arcpy-free. Reads a well network CSV and an analyte groups YAML,
then produces a planned sample list, bottle count summary, and COC draft.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


# Bottle volumes in mL per matrix/analyte group — tuneable via config.
_DEFAULT_BOTTLE_MAP: dict[str, int] = {
    "voc":  40,    # VOA vial
    "svoc": 1000,
    "metals": 500,
    "gw_parameters": 250,
    "tph": 1000,
    "default": 250,
}


@dataclass
class PlannedSample:
    SiteID: str
    EventDate: str
    LocationID: str
    AnalyteGroup: str
    SampleID: str
    Matrix: str
    BottleSizeML: int
    BottleCount: int
    PreservationNotes: str
    PriorEventDate: str


@dataclass
class BottleCountRow:
    SiteID: str
    EventDate: str
    AnalyteGroup: str
    WellCount: int
    BottleSizeML: int
    BottleCount: int
    TotalVolumeML: int


@dataclass
class SamplingPlan:
    samples: List[PlannedSample] = field(default_factory=list)
    bottle_summary: List[BottleCountRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def read_well_network_csv(path: Path) -> list[dict]:
    """Read wells CSV. Required column: location_id. Optional: matrix, notes."""
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if rows and "location_id" not in rows[0]:
        raise ValueError("Wells CSV missing required column: location_id")
    return rows


def create_sampling_plan(
    wells: list[dict],
    analyte_groups: dict,
    *,
    site_id: str,
    event_date: date,
    prior_event_date: Optional[date] = None,
    bottle_map: Optional[dict] = None,
    qa: Optional[QACollector] = None,
) -> SamplingPlan:
    """Build a planned sampling event.

    Args:
        wells: List of dicts from read_well_network_csv.
        analyte_groups: Dict mapping group_name -> {bottles, matrix,
                        preservation, bottle_size_ml, ...}.
        site_id: Site identifier.
        event_date: Planned sampling date.
        prior_event_date: Prior event date for comparison column.
        bottle_map: Override analyte_group -> bottle_size_ml.
        qa: QA collector (created if not supplied).

    Returns:
        SamplingPlan with samples, bottle_summary, and warnings.
    """
    if qa is None:
        qa = QACollector()
    bmap = {**_DEFAULT_BOTTLE_MAP, **(bottle_map or {})}
    plan = SamplingPlan()
    event_str = event_date.isoformat()
    prior_str = prior_event_date.isoformat() if prior_event_date else ""

    if not wells:
        qa.add(SEV_WARNING, "no_wells", "Well network is empty", site_id=site_id)
        return plan

    if not analyte_groups:
        qa.add(SEV_WARNING, "no_analyte_groups",
               "No analyte groups defined", site_id=site_id)
        return plan

    # Count wells per group for bottle summary.
    group_well_counts: dict[str, int] = {}

    for well in wells:
        loc = well.get("location_id", "").strip()
        if not loc:
            qa.add(SEV_WARNING, "empty_location_id",
                   "Well row has empty location_id — skipped", site_id=site_id)
            continue
        matrix = well.get("matrix", "GW").strip() or "GW"

        # Determine which analyte groups apply to this well.
        well_groups_raw = well.get("analyte_groups", "")
        if well_groups_raw:
            well_groups = [g.strip() for g in well_groups_raw.split(",") if g.strip()]
        else:
            well_groups = list(analyte_groups.keys())

        for group_name in well_groups:
            if group_name not in analyte_groups:
                qa.add(SEV_WARNING, "unknown_analyte_group",
                       f"Well {loc!r}: group {group_name!r} not in analyte_groups",
                       site_id=site_id, location_id=loc)
                continue
            grp = analyte_groups[group_name]
            bottle_size = grp.get("bottle_size_ml") or bmap.get(
                group_name.lower(), bmap["default"])
            bottle_count = grp.get("bottles", 1)
            preservation = grp.get("preservation", "")
            # Non-lifecycle identity: per-analyte-group granularity,
            # deliberately NOT the lifecycle SampleID format —
            # sample_id.parse_sample_id returns None for it.
            sample_id = f"{site_id}-{loc}-{event_str}-{group_name}"
            plan.samples.append(PlannedSample(
                SiteID=site_id,
                EventDate=event_str,
                LocationID=loc,
                AnalyteGroup=group_name,
                SampleID=sample_id,
                Matrix=matrix,
                BottleSizeML=bottle_size,
                BottleCount=bottle_count,
                PreservationNotes=preservation,
                PriorEventDate=prior_str,
            ))
            group_well_counts[group_name] = group_well_counts.get(group_name, 0) + 1

    # Build bottle summary.
    for group_name, well_count in sorted(group_well_counts.items()):
        grp = analyte_groups[group_name]
        bottle_size = grp.get("bottle_size_ml") or bmap.get(
            group_name.lower(), bmap["default"])
        bottles_per_well = grp.get("bottles", 1)
        total_bottles = well_count * bottles_per_well
        plan.bottle_summary.append(BottleCountRow(
            SiteID=site_id,
            EventDate=event_str,
            AnalyteGroup=group_name,
            WellCount=well_count,
            BottleSizeML=bottle_size,
            BottleCount=total_bottles,
            TotalVolumeML=total_bottles * bottle_size,
        ))

    qa.add(SEV_INFO, "sampling_plan_complete",
           f"create_sampling_plan: {len(plan.samples)} planned samples across "
           f"{len(group_well_counts)} analyte groups for {len(wells)} wells",
           site_id=site_id)
    return plan
