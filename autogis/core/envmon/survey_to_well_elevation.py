"""survey_to_well_elevation.py — push QA-passed RTK elevations to wells (Tool 8.5).

``select_rtk_elevations_for_wells`` and ``build_elevation_history_records`` are
arcpy-free and fully unit-testable. ``write_rtk_elevations_to_wells`` requires
arcpy — ``# pragma: no cover``.

Design (distinct from Tool 8.2 differential-leveling path):
- "QA-passed" means ``assign_qa_flags(pt) == []``. Human approval is out of scope.
- Point matching is EXACT: point_id must equal LocationID (no fuzzy matching).
- Input is assumed already orthometric (NAVD88); no datum transformation.
- SurveyMethod tag: "GPS_RTK" (vs "DifferentialLevel" for 8.2).
- MonitoringWells elevation column is TOC_ft (gdb_schema.py FEATURE_SCHEMAS).
- Each write supersedes prior ElevationHistory rows for the LocationID.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ..common.schema.survey import ElevationHistory
from .import_rtk_survey import RTKPoint, assign_qa_flags


@dataclass
class RTKElevationUpdatePlan:
    """Headless output of select_rtk_elevations_for_wells().

    updates:   point_id → elevation_ft; wells that will receive a new TOC_ft.
    skipped:   point_ids that passed QA but are not in the supplied well_ids set.
    failed_qa: point_ids whose auto QA flags prevent elevation promotion.
    """
    batch_id: str
    updates: dict[str, float]
    skipped: list[str]
    failed_qa: list[str]
    elevation_type: str = "TOC"


def select_rtk_elevations_for_wells(
    points: list[RTKPoint],
    well_ids: set[str],
    batch_id: str,
    qa: QACollector,
    *,
    hrms_threshold_ft: float = 0.03,
    vrms_threshold_ft: float = 0.05,
    elevation_type: str = "TOC",
) -> RTKElevationUpdatePlan:
    """Filter RTK points by QA and well membership; produce an update plan.

    Each point is evaluated independently: fails QA → failed_qa (WARNING);
    passes QA but unknown well → skipped (INFO); passes QA and known well →
    updates (INFO). A final INFO "plan_complete" record summarises the tally.
    """
    updates: dict[str, float] = {}
    skipped: list[str] = []
    failed_qa: list[str] = []

    for pt in points:
        flags = assign_qa_flags(pt, hrms_threshold_ft, vrms_threshold_ft)
        if flags:
            failed_qa.append(pt.point_id)
            for flag in flags:
                qa.add(SEV_WARNING, flag,
                       f"{pt.point_id}: {flag} — excluded from elevation update",
                       location_id=pt.point_id)
            continue
        if pt.point_id not in well_ids:
            skipped.append(pt.point_id)
            qa.add(SEV_INFO, "point_not_in_well_list",
                   f"{pt.point_id}: QA-passed but not a known well — skipped",
                   location_id=pt.point_id)
            continue
        updates[pt.point_id] = pt.elevation_ft
        qa.add(SEV_INFO, "elevation_update_planned",
               f"{pt.point_id}: {pt.elevation_ft:.3f} ft ({elevation_type}) "
               f"→ update planned",
               location_id=pt.point_id)

    qa.add(SEV_INFO, "plan_complete",
           f"RTK elevation plan: {len(updates)} updates, "
           f"{len(skipped)} skipped, {len(failed_qa)} failed QA")

    return RTKElevationUpdatePlan(
        batch_id=batch_id, updates=updates, skipped=skipped,
        failed_qa=failed_qa, elevation_type=elevation_type,
    )


def build_elevation_history_records(
    plan: RTKElevationUpdatePlan,
    survey_date: date,
    *,
    vertical_datum: str = "NAVD88",
    approved_for_use: bool = False,
) -> list[ElevationHistory]:
    """Construct ElevationHistory rows for every planned update (arcpy-free)."""
    return [
        ElevationHistory(
            location_id=loc_id,
            elevation_type=plan.elevation_type,
            elevation=elev,
            vertical_datum=vertical_datum,
            survey_date=survey_date,
            survey_method="GPS_RTK",
            source_run_id=plan.batch_id,
            approved_for_use=approved_for_use,
            superseded=False,
        )
        for loc_id, elev in plan.updates.items()
    ]


def write_rtk_elevations_to_wells(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    plan: RTKElevationUpdatePlan,
    history_records: list[ElevationHistory],
) -> int:
    """Update MonitoringWells.TOC_ft and write ElevationHistory rows (ArcGIS Pro).

    For each planned well: supersede prior ElevationHistory rows, then update
    MonitoringWells.TOC_ft. Then insert the supplied history_records. Returns
    the count of MonitoringWells rows updated.
    """
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)
    wells_fc = str(_P(gdb) / "MonitoringWells")
    elev_table = str(_P(gdb) / "ElevationHistory")
    updated = 0

    for loc_id, elev in plan.updates.items():
        if _ax.Exists(elev_table):
            where_prior = (
                f"LocationID='{loc_id}' AND "
                f"ElevationType='{plan.elevation_type}' AND Superseded=0"
            )
            with _ax.da.UpdateCursor(elev_table, ["Superseded"], where_prior) as cur:
                for _ in cur:
                    cur.updateRow([1])

        if _ax.Exists(wells_fc):
            where_well = f"SiteID='{site_id}' AND LocationID='{loc_id}'"
            with _ax.da.UpdateCursor(wells_fc, ["TOC_ft"], where_well) as cur:
                for _ in cur:
                    cur.updateRow([elev])
                    updated += 1

    if history_records and _ax.Exists(elev_table):
        fields = [
            "LocationID", "ElevationType", "Elevation_ft", "VerticalDatum",
            "SurveyDate", "SurveyMethod", "SourceRunID", "ApprovedForUse",
            "Superseded",
        ]
        with _ax.da.InsertCursor(elev_table, fields) as cur:
            for rec in history_records:
                cur.insertRow([
                    rec.location_id, rec.elevation_type, rec.elevation,
                    rec.vertical_datum, rec.survey_date, rec.survey_method,
                    rec.source_run_id, int(rec.approved_for_use),
                    int(rec.superseded),
                ])

    return updated
