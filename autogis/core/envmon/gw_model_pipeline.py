"""gw_model_pipeline.py — Phase-5 slice 1: multi-model GW surface pipeline.

RunFieldToGroundwaterModelPipeline (ADR-0085): orchestrates the already-shipped
pieces — draft contours per method via ``groundwater_contours``, leave-one-out
cross-validation ranked by ``evaluate_gw_models`` — and persists one
``GW_ModelRun`` + per-model ``GW_ModelCrossValidation`` rows (ReviewStatus=
'DRAFT'). BuildGroundwaterSurfaceModel is this pipeline with a single method
plus ``approve_gw_model`` (hydro judgment trumps rank — ADR-0085 decision 3).

Slice 1 is TIN/IDW only; EBK/kriging and uncertainty surfaces are slice 2.

Headless (unit-tested): run-id, LOO glue, registry-row shaping, CSV audit
writer. arcpy work lives in the ``# pragma: no cover`` seam functions.
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.evaluate_gw_models import (
    ModelStats, ObservationRow, evaluate_gw_models,
)

PIPELINE_METHODS = ("TIN", "IDW")

# (LocationID, x, y, GroundwaterElevation_ft) — the shape
# groundwater_contours.collect_contour_points already returns.
Point = Tuple[str, float, float, float]

# predict(method, remaining_points, held_out_point) -> predicted GWE or None
# (None = no prediction, e.g. held-out point outside the TIN of the rest;
# evaluate_gw_models treats a missing prediction as a skipped cell).
Predictor = Callable[[str, Sequence[Point], Point], Optional[float]]


def make_run_id(site_id: str, event_date: str, now: _dt.datetime) -> str:
    """Deterministic run id: GWM_<site>_<event>_<timestamp>."""
    return f"GWM_{site_id}_{event_date}_{now:%Y%m%d%H%M%S}"


def loo_observation_rows(
    points: Sequence[Point],
    methods: Sequence[str],
    predict: Predictor,
    qa: QACollector,
) -> List[ObservationRow]:
    """Leave-one-out predictions for every input point, per method.

    LOO needs at least 4 points (each fold must leave >= 3 to build a
    surface); below that cross-validation is skipped with a QA WARNING —
    draft contours are still useful without a ranking.
    """
    for m in methods:
        if m not in PIPELINE_METHODS:
            raise ValueError(
                f"method must be one of {PIPELINE_METHODS}, got {m!r}")
    if len(points) < 4:
        qa.add(SEV_WARNING, "insufficient_cv_points",
               f"Only {len(points)} contourable point(s); leave-one-out "
               "cross-validation needs at least 4. Model ranking skipped.")
        return []

    rows: List[ObservationRow] = []
    for i, held in enumerate(points):
        rest = [p for j, p in enumerate(points) if j != i]
        predictions: Dict[str, float] = {}
        for m in methods:
            v = predict(m, rest, held)
            if v is not None:
                predictions[m] = float(v)
        rows.append(ObservationRow(
            well_id=held[0], observed_ft=held[3], predictions=predictions))
    return rows


def build_run_records(
    run_id: str,
    site_id: str,
    event_date: str,
    methods: Sequence[str],
    stats: Sequence[ModelStats],
    now: _dt.datetime,
) -> Tuple[dict, List[dict]]:
    """Shape one GW_ModelRun row + GW_ModelCrossValidation rows (ADR-0085).

    ReviewStatus starts 'DRAFT' and ApprovedModel empty: rank 1 is a default
    suggestion only — approval is the hydrogeologist's call
    (``approve_gw_model``).
    """
    best = min(stats, key=lambda s: s.rank) if stats else None
    note = (f"Rank-1 suggestion: {best.model_name} (RMSE={best.rmse:.4f} ft). "
            "Suggestion only — requires hydrogeologist approval."
            if best else "No cross-validation ranking (insufficient points).")
    run_row = {
        "RunID": run_id, "SiteID": site_id, "EventDate": event_date,
        "Methods": ",".join(methods), "RunTimestamp": now,
        "ApprovedModel": "", "ReviewStatus": "DRAFT", "Notes": note,
    }
    cv_rows = [{
        "RunID": run_id, "ModelName": s.model_name, "NPoints": s.n_points,
        "RMSE": s.rmse, "MeanError": s.mean_error, "MAE": s.mae,
        "PctWithinTolerance": s.pct_within_tolerance, "Rank": s.rank,
    } for s in stats]
    return run_row, cv_rows


def write_observations_csv(rows: Sequence[ObservationRow],
                           output_path: Path) -> None:
    """Audit CSV in the exact wide shape ``evaluate-gw-models`` consumes."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    models: List[str] = []
    for r in rows:
        for name in r.predictions:
            if name not in models:
                models.append(name)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["well_id", "observed_ft", *models])
        for r in rows:
            w.writerow([r.well_id, r.observed_ft,
                        *(r.predictions.get(m, "") for m in models)])


def cross_validate_and_rank(
    points: Sequence[Point],
    methods: Sequence[str],
    predict: Predictor,
    qa: QACollector,
    *,
    site_id: str,
    event_date: str,
    now: _dt.datetime,
    tolerance_ft: float = 0.5,
    requested_methods: Optional[Sequence[str]] = None,
) -> Tuple[List[ObservationRow], List[ModelStats], dict, List[dict]]:
    """Headless pipeline core: LOO -> evaluate_gw_models -> registry rows.

    ``methods`` is what actually cross-validates; ``requested_methods``
    (default: same) is what GW_ModelRun.Methods records — the ADR-0085 field
    is "methods requested", which must survive a license-skipped method.
    """
    run_id = make_run_id(site_id, event_date, now)
    rows = loo_observation_rows(points, methods, predict, qa)
    stats = evaluate_gw_models(rows, tolerance_ft=tolerance_ft, qa=qa) \
        if rows else []
    run_row, cv_rows = build_run_records(
        run_id, site_id, event_date, requested_methods or methods, stats, now)
    return rows, stats, run_row, cv_rows


# ---------------------------------------------------------------------------
# arcpy seams — LOCAL only (ArcGIS Pro). ADR-0077 doc-verification 2026-07-16:
#   CreateTin, AddSurfaceInformation (3D Analyst), Idw (Spatial Analyst),
#   GetCellValue (no extension) — all current, none deprecated at Pro 3.x.
# ---------------------------------------------------------------------------

def _make_point_fc(arcpy, scratch, name, sr, pts):  # pragma: no cover
    """(Re)create a scratch point FC with a GWE double field from pts."""
    fc = str(Path(str(scratch)) / name)
    if arcpy.Exists(fc):
        arcpy.management.Delete(fc)
    arcpy.management.CreateFeatureclass(str(scratch), name, "POINT",
                                        spatial_reference=sr)
    arcpy.management.AddField(fc, "GWE", "DOUBLE")
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY", "GWE"]) as cur:
        for _loc, x, y, z in pts:
            cur.insertRow([(x, y), z])
    return fc


def make_arcpy_loo_predictor(sr, scratch,
                             cell_size=None):  # pragma: no cover
    """Build a Predictor that re-interpolates with arcpy per LOO fold.

    TIN: CreateTin over the N-1 points + AddSurfaceInformation 'Z' at the
    held-out point (None when it falls outside the TIN data area).
    IDW: arcpy.sa.Idw raster + GetCellValue at the held-out point (None on
    'NoData'). ponytail: N surface builds per method — fine for monitoring
    networks (tens of wells); batch it if a site ever has hundreds.
    """
    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    scratch = Path(str(scratch))

    def predict(method: str, rest: Sequence[Point],
                held: Point) -> Optional[float]:
        pt_fc = _make_point_fc(arcpy, scratch, "gwm_loo_pts", sr, rest)
        _loc, x, y, _z = held
        if method == "TIN":
            tin = str(Path(str(scratch)).parent / "gwm_loo_tin")
            if arcpy.Exists(tin):
                arcpy.management.Delete(tin)
            arcpy.ddd.CreateTin(tin, sr, [[pt_fc, "GWE", "Mass_Points"]])
            held_fc = _make_point_fc(arcpy, scratch, "gwm_loo_held", sr,
                                     [held])
            arcpy.ddd.AddSurfaceInformation(held_fc, tin, "Z", "LINEAR")
            with arcpy.da.SearchCursor(held_fc, ["Z"]) as cur:
                for (z,) in cur:
                    return float(z) if z is not None else None
            return None
        # IDW
        xs = [p[1] for p in rest]; ys = [p[2] for p in rest]
        cs = cell_size or max((max(xs) - min(xs)),
                              (max(ys) - min(ys)), 1.0) / 250.0
        ras = arcpy.sa.Idw(pt_fc, "GWE", cs)
        out = arcpy.management.GetCellValue(ras, f"{x} {y}").getOutput(0)
        try:
            return float(out)
        except (TypeError, ValueError):
            return None  # 'NoData' outside the interpolated extent

    return predict


def write_model_run_to_gdb(gdb, run_row: dict,
                           cv_rows: List[dict]) -> bool:  # pragma: no cover
    """Insert the run + cross-validation rows. False if tables are missing
    (run the schema upgrade first) — callers must not report success then."""
    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    run_tbl = str(Path(str(gdb)) / "GW_ModelRun")
    cv_tbl = str(Path(str(gdb)) / "GW_ModelCrossValidation")
    if not (arcpy.Exists(run_tbl) and arcpy.Exists(cv_tbl)):
        return False
    ev_dt = _dt.datetime.strptime(run_row["EventDate"], "%Y-%m-%d")
    with arcpy.da.InsertCursor(
            run_tbl, ["RunID", "SiteID", "EventDate", "Methods",
                      "RunTimestamp", "ApprovedModel", "ReviewStatus",
                      "Notes"]) as cur:
        cur.insertRow([run_row["RunID"], run_row["SiteID"], ev_dt,
                       run_row["Methods"], run_row["RunTimestamp"],
                       run_row["ApprovedModel"], run_row["ReviewStatus"],
                       run_row["Notes"]])
    with arcpy.da.InsertCursor(
            cv_tbl, ["RunID", "ModelName", "NPoints", "RMSE", "MeanError",
                     "MAE", "PctWithinTolerance", "Rank"]) as cur:
        for r in cv_rows:
            cur.insertRow([r["RunID"], r["ModelName"], r["NPoints"],
                           r["RMSE"], r["MeanError"], r["MAE"],
                           r["PctWithinTolerance"], r["Rank"]])
    return True


def run_field_to_groundwater_model_pipeline(  # pragma: no cover
    gdb,
    site_id: str,
    event_date: str,
    qa: QACollector,
    methods: Sequence[str] = PIPELINE_METHODS,
    contour_interval: float = 1.0,
    min_valid_points: int = 3,
    boundary_fc: Optional[str] = None,
    tolerance_ft: float = 0.5,
    observations_csv: Optional[Path] = None,
    stats_csv: Optional[Path] = None,
) -> dict:
    """RunFieldToGroundwaterModelPipeline (LOCAL): contours per method,
    LOO cross-validation, persisted DRAFT run record."""
    from autogis.runtime.sessions import arcpy_env as _arcpy
    from autogis.core.envmon.groundwater_contours import (
        build_groundwater_contours, collect_contour_points,
    )
    from autogis.core.envmon.evaluate_gw_models import write_model_stats_csv
    arcpy = _arcpy()

    for m in methods:
        if m not in PIPELINE_METHODS:
            raise ValueError(
                f"method must be one of {PIPELINE_METHODS}, got {m!r}")
    try:
        _dt.datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"event_date must be YYYY-MM-DD, got {event_date!r}")

    summary: dict = {"run_id": "", "methods": list(methods), "points": 0,
                     "contours": {}, "models_ranked": 0,
                     "registry_written": False}

    # Draft contours per method — reuses the shipped, license-degrading tool.
    for m in methods:
        summary["contours"][m] = build_groundwater_contours(
            gdb, site_id, event_date, qa, method=m,
            contour_interval=contour_interval,
            min_valid_points=min_valid_points, boundary_fc=boundary_fc)

    pts = collect_contour_points(gdb, site_id, event_date, qa)
    summary["points"] = len(pts)

    # LOO needs the same licenses the contour stage needs; a method whose
    # contour stage was license-skipped is dropped from ranking too.
    cv_methods = [m for m in methods
                  if not summary["contours"][m].get("skipped")]
    now = _dt.datetime.now()
    if cv_methods and len(pts) >= 4:
        need = {"TIN": "3D", "IDW": "Spatial"}
        for ext in {need[m] for m in cv_methods}:
            arcpy.CheckOutExtension(ext)
        try:
            sr = arcpy.Describe(
                str(Path(str(gdb)) / "MonitoringWells")).spatialReference
            predict = make_arcpy_loo_predictor(sr, arcpy.env.scratchGDB)
            rows, stats, run_row, cv_rows = cross_validate_and_rank(
                pts, cv_methods, predict, qa, site_id=site_id,
                event_date=event_date, now=now, tolerance_ft=tolerance_ft,
                requested_methods=methods)
        finally:
            for ext in {need[m] for m in cv_methods}:
                arcpy.CheckInExtension(ext)
    else:
        rows, stats, run_row, cv_rows = cross_validate_and_rank(
            pts, cv_methods, lambda *_: None, qa, site_id=site_id,
            event_date=event_date, now=now, tolerance_ft=tolerance_ft,
            requested_methods=methods)

    summary["run_id"] = run_row["RunID"]
    summary["models_ranked"] = len(stats)
    if observations_csv and rows:
        write_observations_csv(rows, Path(observations_csv))
    if stats_csv and stats:
        write_model_stats_csv(list(stats), Path(stats_csv))

    summary["registry_written"] = write_model_run_to_gdb(gdb, run_row, cv_rows)
    if not summary["registry_written"]:
        qa.add(SEV_ERROR, "gw_model_registry_missing",
               "GW_ModelRun/GW_ModelCrossValidation tables missing — run "
               "upgrade-schema (v2.4) first. Run record NOT persisted.",
               site_id=site_id)
    else:
        qa.add(SEV_INFO, "gw_model_pipeline_complete",
               f"Run {run_row['RunID']}: {len(stats)} model(s) ranked over "
               f"{len(pts)} well(s). ReviewStatus=DRAFT — rank 1 is a "
               "suggestion; approve with approve-gw-model.", site_id=site_id)
    return summary


def approve_gw_model(gdb, run_id: str, model_name: str,
                     reviewer: str = "") -> bool:  # pragma: no cover
    """Record the hydrogeologist's model choice on GW_ModelRun.

    The chosen model must have been part of the run (any rank — hydro
    judgment trumps the metric, ADR-0085 decision 3). Returns False when the
    run id is unknown or the model was not in the run.
    """
    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    run_tbl = str(Path(str(gdb)) / "GW_ModelRun")
    cv_tbl = str(Path(str(gdb)) / "GW_ModelCrossValidation")
    if not (arcpy.Exists(run_tbl) and arcpy.Exists(cv_tbl)):
        return False
    # --run-id is user input: escape quotes so the where clause can't break.
    where = "RunID = '{}'".format(run_id.replace("'", "''"))
    ran = set()
    with arcpy.da.SearchCursor(cv_tbl, ["ModelName"],
                               where_clause=where) as cur:
        for (name,) in cur:
            ran.add(name)
    if model_name not in ran:
        return False
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    updated = False
    with arcpy.da.UpdateCursor(
            run_tbl, ["ApprovedModel", "ReviewStatus", "Notes"],
            where_clause=where) as cur:
        for _am, _rs, notes in cur:
            cur.updateRow([model_name, "APPROVED",
                           f"{notes or ''} | Approved {model_name} "
                           f"by {reviewer or 'unspecified'} {stamp}"[:256]])
            updated = True
    return updated
