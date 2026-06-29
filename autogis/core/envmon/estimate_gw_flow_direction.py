"""estimate_gw_flow_direction.py — hydraulic gradient from water-level plane fit (Tool 4.3).

Headless, arcpy-free. Fits a least-squares plane h = a·E + b·N + c to 3+
well GWEs, then derives flow direction and gradient magnitude. Outputs are
DRAFT_REVIEW_REQUIRED — professional review is mandatory before publication.

Math
----
For n wells at (Eᵢ, Nᵢ, hᵢ):
  A = [[E₁ N₁ 1], ..., [Eₙ Nₙ 1]]  (design matrix)
  θ = lstsq(A, h)  →  θ = [a, b, c]

  gradient = (a, b)            ← ∂h/∂E, ∂h/∂N
  gradient_magnitude = ‖(a,b)‖
  flow_vector = (-a, -b)       ← water flows down-gradient
  flow_azimuth_deg = degrees(atan2(-a, -b)) % 360   [0°=N, 90°=E, CW]
"""
from __future__ import annotations

import csv
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

# Condition-number threshold for collinearity detection.
# 1e8 is conservative: normal site networks (triangular/quadrilateral layouts)
# have cond(A) < 1e4; perfectly collinear wells produce cond >> 1e12.
_COLLINEAR_THRESHOLD = 1e8


@dataclass
class WellWaterLevel:
    """One well's location and groundwater elevation (input to plane fit)."""
    well_id: str
    easting: float
    northing: float
    gwe_ft: float


@dataclass
class GWFlowResult:
    """Plane-fit result for one site/event run."""
    run_id: str
    site_id: str
    event_date: str
    n_wells: int
    well_ids: List[str]
    plane_a: float          # ∂h/∂easting
    plane_b: float          # ∂h/∂northing
    plane_c: float          # intercept
    gradient_magnitude: float
    flow_azimuth_deg: float
    condition_number: float
    method: str             # "THREE_POINT" | "LEAST_SQUARES" | ""
    qa_status: str          # "PASS" | "COLLINEAR" | "INSUFFICIENT"
    qa_notes: str
    draft: bool = True      # always True — outputs require professional review


def _fit_plane(
    wells: List[WellWaterLevel],
    qa: QACollector,
    site_id: str,
    collinear_threshold: float,
) -> Optional[tuple]:
    """Fit h = a·E + b·N + c by least-squares.

    Returns (a, b, c, condition_number, method_str) or None if infeasible.
    Adds QA records for all failure modes.
    """
    n = len(wells)
    if n < 3:
        qa.add(SEV_ERROR, "insufficient_wells",
               f"Need at least 3 wells; got {n}.",
               site_id=site_id,
               recommended_action="Supply 3 or more wells with valid GWEs.")
        return None

    A = np.array([[w.easting, w.northing, 1.0] for w in wells],
                 dtype=float)
    h = np.array([w.gwe_ft for w in wells], dtype=float)

    cond = float(np.linalg.cond(A))

    if cond > collinear_threshold:
        qa.add(SEV_ERROR, "collinear_wells",
               f"Wells appear collinear (condition number {cond:.2e} "
               f"> threshold {collinear_threshold:.2e}). "
               f"Gradient plane cannot be reliably resolved.",
               site_id=site_id,
               recommended_action=(
                   "Add a well that is not on the same line as existing "
                   "wells, or check for duplicate coordinates."))
        return None

    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(A, h, rcond=None)
    a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
    method = "THREE_POINT" if n == 3 else "LEAST_SQUARES"
    return a, b, c, cond, method


def estimate_gw_flow_direction(
    wells: List[WellWaterLevel],
    *,
    run_id: Optional[str] = None,
    site_id: str,
    event_date: str,
    collinear_threshold: float = _COLLINEAR_THRESHOLD,
    qa: QACollector,
) -> GWFlowResult:
    """Fit a plane to well water levels; return hydraulic gradient and azimuth.

    Parameters
    ----------
    wells : list[WellWaterLevel]
        Must have >= 3 wells that are not collinear.
    run_id : str, optional
        Unique run identifier; a UUID4 is auto-generated if omitted.
    site_id : str
        Site identifier written to QA records and output.
    event_date : str
        Event date string (e.g. ``"2026-06-28"``); metadata only.
    collinear_threshold : float
        Condition-number threshold above which wells are flagged collinear.
        Default 1e8.
    qa : QACollector
        Receives ERROR on failure, INFO on success.

    Returns
    -------
    GWFlowResult
        ``qa_status`` is ``"PASS"``, ``"COLLINEAR"``, or ``"INSUFFICIENT"``.
        ``draft`` is always ``True`` — these outputs require professional review.
    """
    run_id = run_id or str(uuid.uuid4())
    well_ids = [w.well_id for w in wells]
    n = len(wells)
    _nan = float("nan")

    fit = _fit_plane(wells, qa, site_id, collinear_threshold)
    if fit is None:
        qa_status = "INSUFFICIENT" if n < 3 else "COLLINEAR"
        return GWFlowResult(
            run_id=run_id, site_id=site_id, event_date=event_date,
            n_wells=n, well_ids=well_ids,
            plane_a=_nan, plane_b=_nan, plane_c=_nan,
            gradient_magnitude=_nan, flow_azimuth_deg=_nan,
            condition_number=_nan, method="",
            qa_status=qa_status,
            qa_notes="Plane fit failed — see QA records. DRAFT_REVIEW_REQUIRED.",
        )

    a, b, c, cond, method = fit
    grad_mag = math.sqrt(a**2 + b**2)

    # Flow azimuth: steepest-descent direction, CW from North.
    # flow_vector in (east, north) = (-a, -b)
    # azimuth = atan2(east_component, north_component) % 360
    azimuth_deg = math.degrees(math.atan2(-a, -b)) % 360.0

    qa.add(SEV_INFO, "gw_flow_computed",
           f"run={run_id} site={site_id} event={event_date} "
           f"n_wells={n} method={method} "
           f"gradient={grad_mag:.6f} ft/ft azimuth={azimuth_deg:.1f}deg "
           f"cond={cond:.2e} DRAFT_REVIEW_REQUIRED",
           site_id=site_id)

    return GWFlowResult(
        run_id=run_id, site_id=site_id, event_date=event_date,
        n_wells=n, well_ids=well_ids,
        plane_a=a, plane_b=b, plane_c=c,
        gradient_magnitude=grad_mag,
        flow_azimuth_deg=azimuth_deg,
        condition_number=cond,
        method=method,
        qa_status="PASS",
        qa_notes=f"DRAFT_REVIEW_REQUIRED — {method}, cond={cond:.2e}",
    )


def parse_wells_csv(path: Path) -> List[WellWaterLevel]:
    """Read a wells CSV with columns: well_id, easting, northing, gwe_ft.

    Parameters
    ----------
    path : Path
        Input CSV path.

    Returns
    -------
    list[WellWaterLevel]
        One entry per data row; header row is consumed by DictReader.

    Raises
    ------
    KeyError
        If a required column is missing.
    ValueError
        If a numeric field cannot be parsed as float.
    """
    wells: List[WellWaterLevel] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            wells.append(WellWaterLevel(
                well_id=row["well_id"].strip(),
                easting=float(row["easting"]),
                northing=float(row["northing"]),
                gwe_ft=float(row["gwe_ft"]),
            ))
    return wells
