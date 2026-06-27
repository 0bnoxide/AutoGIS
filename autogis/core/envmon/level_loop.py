"""Single-loop differential (height-of-instrument) leveling (Tool 8.1).

Headless, arcpy-free. Computes adjusted elevations + misclosure and emits QA.
Does NOT write ElevationHistory (that is Tool 8.2). See ADR-0026.
"""
from __future__ import annotations

import math
from datetime import date
from typing import List, Optional, Tuple

from ..common.schema.survey import LevelLoopObservation, LevelLoopRun
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
