"""Single-loop differential (height-of-instrument) leveling (Tool 8.1)
plus the elevation-update push (Tool 8.2).

Headless, arcpy-free except update_well_elevations() (# pragma: no cover).
process_level_loop() computes adjusted elevations + misclosure and emits QA
but does NOT write ElevationHistory — that gap is closed here by
select_elevations_for_update() / update_well_elevations(). See ADR-0026.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from ..common.schema.survey import (
    ElevationHistory, LevelLoopObservation, LevelLoopRun)
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def process_level_loop(
    observations: List[LevelLoopObservation],
    *,
    run_id: str,
    site_id: str,
    survey_date: date,
    benchmark_id: str,
    known_elevation: float,
    tolerance: Optional[float],
    qa: QACollector,
) -> Tuple[LevelLoopRun, List[LevelLoopObservation]]:
    """Process single-loop differential leveling observations.

    Returns (LevelLoopRun, adjusted LevelLoopObservation rows).
    See ADR-0026 for locked design decisions (HI rules, equal-per-setup
    adjustment, QA flag set).
    """
    # 1. Validate readings: flag negative values.
    for obs in observations:
        for reading_name, reading_val in (
            ("backsight", obs.backsight),
            ("foresight", obs.foresight),
            ("intermediate_sight", obs.intermediate_sight),
        ):
            if reading_val is not None and reading_val < 0:
                qa.add(SEV_ERROR, "negative_reading",
                       f"Negative {reading_name} {reading_val} at "
                       f"setup={obs.setup_id} point={obs.point_id}",
                       site_id=site_id)

    # 2. Forward pass: compute raw elevations using HI method.
    #    State: current HI, current known elevation of last turning point.
    current_elev: dict[str, float] = {benchmark_id: known_elevation}
    hi: Optional[float] = None
    n_setups = 0
    turning_point_uses: dict[str, int] = {}  # counts turning-point appearances

    # We'll build output rows as we go; start with copies of input rows.
    out_rows: List[LevelLoopObservation] = []
    # setup_index records which logical setup each TP elevation belongs to
    # so we can distribute the adjustment later.
    # setup_sequence: list of (setup_id, point_id) for turning points in order.
    setup_sequence: List[Tuple[str, str]] = []  # (setup_id, tp_point_id)
    closing_found = False
    closing_elev: Optional[float] = None

    for obs in observations:
        row_hi: Optional[float] = None
        row_elev: Optional[float] = None

        # Process foresight first (closes prior setup), then backsight (opens next).
        # A row may carry both (ADR-0026: "process foresight first, then backsight").

        if obs.foresight is not None and obs.foresight >= 0:
            if hi is None:
                qa.add(SEV_ERROR, "missing_backsight",
                       f"Foresight at setup={obs.setup_id} point={obs.point_id} "
                       f"but no HI established yet",
                       site_id=site_id)
            else:
                elev = hi - obs.foresight
                row_elev = elev
                if obs.point_id == benchmark_id:
                    closing_found = True
                    closing_elev = elev
                else:
                    current_elev[obs.point_id] = elev
                    # Track turning-point usage for duplicate detection.
                    turning_point_uses[obs.point_id] = (
                        turning_point_uses.get(obs.point_id, 0) + 1)
                    if turning_point_uses[obs.point_id] > 1:
                        qa.add(SEV_WARNING, "duplicate_turning_point",
                               f"Point {obs.point_id!r} used as turning point "
                               f"more than once",
                               site_id=site_id)
                    setup_sequence.append((obs.setup_id, obs.point_id))

        if obs.backsight is not None and obs.backsight >= 0:
            pt_elev = current_elev.get(obs.point_id)
            if pt_elev is None:
                qa.add(SEV_ERROR, "missing_backsight",
                       f"Backsight at setup={obs.setup_id} point={obs.point_id} "
                       f"but elevation of {obs.point_id!r} not yet known",
                       site_id=site_id)
            else:
                hi = pt_elev + obs.backsight
                row_hi = hi
                n_setups += 1

        if obs.intermediate_sight is not None and obs.intermediate_sight >= 0:
            if hi is None:
                qa.add(SEV_ERROR, "missing_backsight",
                       f"Intermediate sight at setup={obs.setup_id} "
                       f"point={obs.point_id} but no HI established",
                       site_id=site_id)
            else:
                row_elev = hi - obs.intermediate_sight
                current_elev[obs.point_id] = row_elev

        out_rows.append(LevelLoopObservation(
            run_id=obs.run_id,
            setup_id=obs.setup_id,
            point_id=obs.point_id,
            backsight=obs.backsight,
            foresight=obs.foresight,
            intermediate_sight=obs.intermediate_sight,
            hi=row_hi if obs.backsight is not None else None,
            elevation=row_elev,
        ))

    # 3. Closure checks.
    if not closing_found:
        qa.add(SEV_WARNING, "unclosed_loop",
               f"Loop never returned a foresight onto benchmark {benchmark_id!r}",
               site_id=site_id)
        qa.add(SEV_ERROR, "benchmark_mismatch",
               f"No closing shot onto benchmark {benchmark_id!r}",
               site_id=site_id)
        misclosure = None
    else:
        misclosure = (closing_elev - known_elevation)  # type: ignore[operator]

    # 4. Default tolerance: 0.05 * sqrt(n_setups).
    if tolerance is None:
        tolerance = 0.05 * math.sqrt(max(n_setups, 1))
        qa.add(SEV_INFO, "closure_tolerance_default",
               f"Default tolerance = 0.05 * sqrt({n_setups}) = {tolerance:.6f} ft",
               site_id=site_id)

    # 5. QA: misclosure vs tolerance.
    adjusted = False
    if misclosure is not None and abs(misclosure) > tolerance:
        qa.add(SEV_ERROR, "misclosure_exceeds_tolerance",
               f"Misclosure {misclosure:.6f} ft exceeds tolerance {tolerance:.6f} ft",
               site_id=site_id)

    # 6. Adjustment: distribute -misclosure equally per setup.
    if misclosure is not None and n_setups > 0 and misclosure != 0:
        correction_per_setup = -misclosure / n_setups
        # Build setup ordering: map each turning point to its setup index
        # (1-based: setup_sequence[0] was closed in the 1st setup, etc.)
        # Assign correction cumulatively: TP from setup i gets i * correction.
        tp_corrections: dict[str, float] = {}
        for idx, (_, tp_id) in enumerate(setup_sequence, start=1):
            tp_corrections[tp_id] = idx * correction_per_setup
        # Apply to out_rows: turning points and their side-shots.
        # Side-shots use the same HI as their setup's closing TP correction,
        # approximated by the preceding TP's correction index.
        # For simplicity: a row's correction = correction of the current
        # "active" turning point at time of reading.
        active_correction = 0.0
        for row in out_rows:
            if row.foresight is not None and row.point_id != benchmark_id:
                active_correction = tp_corrections.get(row.point_id,
                                                        active_correction)
                if row.elevation is not None:
                    row.elevation = row.elevation + active_correction
            elif row.intermediate_sight is not None:
                if row.elevation is not None:
                    row.elevation = row.elevation + active_correction
        adjusted = True

    # 7. Info complete record.
    misc_str = f"{misclosure:.6f}" if misclosure is not None else "N/A"
    qa.add(SEV_INFO, "level_loop_complete",
           f"run={run_id} setups={n_setups} misclosure={misc_str} ft "
           f"adjusted={adjusted}",
           site_id=site_id)

    run = LevelLoopRun(
        run_id=run_id,
        site_id=site_id,
        survey_date=survey_date,
        benchmark_id=benchmark_id,
        known_elevation=known_elevation,
        misclosure_ft=misclosure if misclosure is not None else None,
        closure_tolerance_ft=tolerance,
        adjusted=adjusted,
    )
    return run, out_rows


@dataclass
class ElevationUpdatePlan:
    """Headless output of select_elevations_for_update() (Tool 8.2).

    updates: point_id -> final (adjusted) elevation ready to push to wells.
    skipped: point_ids seen in the run but absent from the known well_ids set.
    blocked: True when the run's own closure result forbids promotion; see
        block_reason ("not_adjusted" | "misclosure_exceeds_tolerance").
    survey_date: carried from LevelLoopRun for the ElevationHistory record —
        not part of the update decision itself, but update_well_elevations()
        needs a survey_date and ElevationUpdatePlan is its only input, so it
        rides along here (lazier than adding a second parameter/thread-through).
    """
    run_id: str
    updates: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
    survey_date: Optional[date] = None


def select_elevations_for_update(
    run: LevelLoopRun,
    observations: List[LevelLoopObservation],
    well_ids: set[str],
) -> ElevationUpdatePlan:
    """Decide which points from a closed level-loop run may update wells (Tool 8.2).

    Blocks (updates/skipped left empty) when the run itself isn't usable:
    - run.adjusted is False: process_level_loop() never applied a correction,
      either because the loop never closed onto the benchmark, or (edge case)
      the raw misclosure was exactly zero -- see ADR-0026 / test_level_loop.py
      test_perfect_closing_loop_zero_misclosure, which itself treats
      run.adjusted as ambiguous in that case. This function blocks
      conservatively either way (judgement call: a human should re-run/confirm
      rather than have 8.2 silently promote a run the source tool didn't mark
      adjusted).
    - misclosure exceeds tolerance: process_level_loop() still distributes the
      correction (adjusted=True) even when out of tolerance -- it only *logs*
      a QA error. Tool 8.2 re-checks the same numbers and blocks the push
      independently of that flag.

    Otherwise: the last elevation recorded per point_id wins (a point can
    appear as both a turning-point foresight and a later intermediate sight);
    the benchmark itself is never eligible for a well update.
    """
    if not run.adjusted:
        return ElevationUpdatePlan(run_id=run.run_id, blocked=True,
                                    block_reason="not_adjusted",
                                    survey_date=run.survey_date)
    if (run.misclosure_ft is not None and run.closure_tolerance_ft is not None
            and abs(run.misclosure_ft) > run.closure_tolerance_ft):
        return ElevationUpdatePlan(run_id=run.run_id, blocked=True,
                                    block_reason="misclosure_exceeds_tolerance",
                                    survey_date=run.survey_date)

    updates: dict[str, float] = {}
    skipped: list[str] = []
    for obs in observations:
        if obs.point_id == run.benchmark_id or obs.elevation is None:
            continue
        if obs.point_id in well_ids:
            updates[obs.point_id] = obs.elevation  # last write wins
        elif obs.point_id not in skipped:
            skipped.append(obs.point_id)

    return ElevationUpdatePlan(run_id=run.run_id, updates=updates,
                                skipped=skipped, survey_date=run.survey_date)


def update_well_elevations(gdb_path: str, site_id: str,  # pragma: no cover
                            plan: ElevationUpdatePlan) -> int:
    """Push a closed level-loop run's elevations to wells (ArcGIS Pro) (Tool 8.2).

    Mirrors write_rtk_elevations_to_wells() in survey_to_well_elevation.py
    (Tool 8.5's sibling path): supersede prior ElevationHistory rows for each
    LocationID/ElevationType, update MonitoringWells.TOC_ft, then insert new
    ElevationHistory rows tagged SurveyMethod="DifferentialLevel". Vertical
    datum defaults to "NAVD88" (judgement call: not modeled anywhere in the
    LevelLoop* schema, so hardcoded the same as Tool 8.5's CLI default).
    Returns the count of MonitoringWells rows updated.
    """
    if plan.blocked:
        raise ValueError(f"ElevationUpdatePlan is blocked: {plan.block_reason}")

    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    from .survey_to_well_elevation import sql_quote

    elevation_type = "TOC"
    vertical_datum = "NAVD88"

    history_records = [
        ElevationHistory(
            location_id=loc_id, elevation_type=elevation_type, elevation=elev,
            vertical_datum=vertical_datum, survey_date=plan.survey_date,
            survey_method="DifferentialLevel", source_run_id=plan.run_id,
            approved_for_use=False, superseded=False,
        )
        for loc_id, elev in plan.updates.items()
    ]

    _ax = _arcpy()
    gdb = str(gdb_path)
    wells_fc = str(_P(gdb) / "MonitoringWells")
    elev_table = str(_P(gdb) / "ElevationHistory")
    updated = 0

    for loc_id, elev in plan.updates.items():
        if _ax.Exists(elev_table):
            where_prior = (
                f"LocationID='{sql_quote(loc_id)}' AND "
                f"ElevationType='{sql_quote(elevation_type)}' AND Superseded=0"
            )
            with _ax.da.UpdateCursor(elev_table, ["Superseded"], where_prior) as cur:
                for _ in cur:
                    cur.updateRow([1])

        if _ax.Exists(wells_fc):
            where_well = (f"SiteID='{sql_quote(site_id)}' AND "
                          f"LocationID='{sql_quote(loc_id)}'")
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
