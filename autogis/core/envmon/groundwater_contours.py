"""Draft groundwater elevation contours and a draft flow arrow.

Everything produced here is marked ReviewStatus='DRAFT'. Contours from
automated interpolation are a starting point for professional review,
never a deliverable on their own.

License handling: TIN needs 3D Analyst; IDW/Natural Neighbor need
Spatial Analyst; EBK needs Geostatistical Analyst + Spatial Analyst
(slice-2 D1: its contours route through the prediction raster and
sa.Contour). Missing licenses degrade to a skip with a QA ERROR
instead of crashing.
"""

from __future__ import annotations

import datetime as _dt
import math
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..common.logging import get_logger
from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

LOG = get_logger(__name__)

METHODS = ("TIN", "IDW", "NaturalNeighbor", "SkipContours", "EBK")

# Licenses per method (slice-2 D1: EBK contours route through the
# prediction raster + sa.Contour, so EBK needs GeoStats AND Spatial).
_METHOD_LICENSES = {"TIN": ("3D",), "IDW": ("Spatial",),
                    "NaturalNeighbor": ("Spatial",),
                    "EBK": ("GeoStats", "Spatial")}


from ...runtime.sessions import arcpy_env as _arcpy


def _where_date(field: str, ymd: str) -> str:
    return (f"{field} >= date '{ymd} 00:00:00' "
            f"AND {field} <= date '{ymd} 23:59:59'")


def fit_plane_gradient(points: Sequence[Tuple[float, float, float]]
                       ) -> Optional[Tuple[float, float]]:
    """Least-squares plane z = ax + by + c; returns down-gradient flow
    direction (-a, -b), or None if degenerate. Pure Python."""
    n = len(points)
    if n < 3:
        return None
    sx = sum(p[0] for p in points); sy = sum(p[1] for p in points)
    sz = sum(p[2] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    syy = sum(p[1] * p[1] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    sxz = sum(p[0] * p[2] for p in points)
    syz = sum(p[1] * p[2] for p in points)
    A = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]
    B = [sxz, syz, sz]
    sol = _solve3(A, B)
    if sol is None:
        return None
    a, b, _c = sol
    if abs(a) < 1e-12 and abs(b) < 1e-12:
        return None
    return (-a, -b)


def _solve3(A, B):
    """Gaussian elimination for a 3x3 system; None if singular."""
    M = [row[:] + [b] for row, b in zip(A, B)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(3):
            if r != col:
                f = M[r][col] / M[col][col]
                M[r] = [x - f * y for x, y in zip(M[r], M[col])]
    return [M[i][3] / M[i][i] for i in range(3)]


def collect_contour_points(
    gdb, site_id: str, event_date: str, qa: QACollector,
    zscore_warn: float = 3.0,
) -> List[Tuple[str, float, float, float]]:
    """(LocationID, x, y, GWE) for UseForContour=1 wells with valid GWE,
    with z-score outlier warnings."""
    arcpy = _arcpy()
    wl = str(gdb / "Env_WaterLevels")
    wells = str(gdb / "MonitoringWells")
    xy: Dict[str, Tuple[float, float]] = {}
    with arcpy.da.SearchCursor(wells, ["LocationID", "SHAPE@XY"],
                               where_clause=f"SiteID = '{site_id}'") as cur:
        for loc, p in cur:
            if loc and p:
                xy[str(loc).strip().upper()] = p

    where = (f"SiteID = '{site_id}' AND UseForContour = 1 "
             f"AND GroundwaterElevation_ft IS NOT NULL AND "
             + _where_date("EventDate", event_date))
    pts: List[Tuple[str, float, float, float]] = []
    with arcpy.da.SearchCursor(wl, ["LocationID", "GroundwaterElevation_ft"],
                               where_clause=where) as cur:
        for loc, gwe in cur:
            key = str(loc).strip().upper()
            if key in xy:
                pts.append((loc, xy[key][0], xy[key][1], float(gwe)))
            else:
                qa.add(SEV_WARNING, "contour_point_no_geometry",
                       f"{loc}: valid GWE but no MonitoringWells point; "
                       "excluded from contouring.", location_id=str(loc))
    if len(pts) >= 3:
        zs = [p[3] for p in pts]
        mu = statistics.mean(zs)
        sd = statistics.pstdev(zs)
        if sd > 0:
            for loc, _x, _y, z in pts:
                if abs(z - mu) / sd > zscore_warn:
                    qa.add(SEV_WARNING, "gwe_outlier",
                           f"{loc}: GWE {z:.2f} is {abs(z-mu)/sd:.1f} sigma "
                           f"from the event mean ({mu:.2f}); verify before "
                           "trusting the contours.", location_id=str(loc))
    return pts


def _write_contour_points(gdb, site_id: str, ev_dt, event_date: str,
                          pts, qa: QACollector) -> None:
    """Persist the points actually used (Env_GWContourPoints)."""
    arcpy = _arcpy()
    fc = str(gdb / "Env_GWContourPoints")
    if not arcpy.Exists(fc):
        return
    where = f"SiteID = '{site_id}' AND " + _where_date("EventDate", event_date)
    with arcpy.da.UpdateCursor(fc, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
    fields = ["SiteID", "EventDate", "LocationID",
              "GroundwaterElevation_ft", "UseForContour", "SHAPE@XY"]
    with arcpy.da.InsertCursor(fc, fields) as cur:
        for loc, x, y, z in pts:
            cur.insertRow([site_id, ev_dt, loc, z, 1, (x, y)])


def build_groundwater_contours(
    gdb,
    site_id: str,
    event_date: str,
    qa: QACollector,
    method: str = "TIN",
    contour_interval: float = 1.0,
    min_valid_points: int = 3,
    boundary_fc: Optional[str] = None,
    cell_size: Optional[float] = None,
    scratch: Optional[Path] = None,
) -> Dict:
    """Create Env_GWContours_Draft + Env_GWFlowArrow_Draft for one event."""
    arcpy = _arcpy()
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    summary = {"method": method, "points": 0, "contours_written": 0,
               "flow_arrow": False, "skipped": False, "se_raster": ""}
    try:
        ev_dt = _dt.datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"event_date must be YYYY-MM-DD, got {event_date!r}")

    pts = collect_contour_points(gdb, site_id, event_date, qa)
    summary["points"] = len(pts)
    _write_contour_points(gdb, site_id, ev_dt, event_date, pts, qa)
    if method == "SkipContours":
        summary["skipped"] = True
        return summary
    if len(pts) < min_valid_points:
        qa.add(SEV_ERROR, "insufficient_contour_points",
               f"Only {len(pts)} valid contourable wells for {site_id} "
               f"{event_date} (minimum {min_valid_points}). Contouring "
               "skipped.",
               recommended_action="Review UseForContour/ExclusionReason.",
               site_id=site_id)
        summary["skipped"] = True
        return summary

    needs = _METHOD_LICENSES[method]
    missing = [e for e in needs if arcpy.CheckExtension(e) != "Available"]
    if missing:
        qa.add(SEV_ERROR, "license_unavailable",
               f"{'/'.join(missing)} license unavailable; {method} "
               "contouring skipped. Configure licensing or use SkipContours.",
               site_id=site_id)
        summary["skipped"] = True
        return summary
    for ext in needs:
        arcpy.CheckOutExtension(ext)

    scratch = Path(scratch or arcpy.env.scratchGDB)
    pt_fc = str(scratch / f"gwe_pts_{site_id}")
    sr = arcpy.Describe(str(gdb / "MonitoringWells")).spatialReference
    if arcpy.Exists(pt_fc):
        arcpy.management.Delete(pt_fc)
    arcpy.management.CreateFeatureclass(str(scratch), Path(pt_fc).name,
                                        "POINT", spatial_reference=sr)
    arcpy.management.AddField(pt_fc, "GWE", "DOUBLE")
    with arcpy.da.InsertCursor(pt_fc, ["SHAPE@XY", "GWE"]) as cur:
        for _loc, x, y, z in pts:
            cur.insertRow([(x, y), z])

    raw_contours = str(scratch / f"gwe_ctr_{site_id}")
    if arcpy.Exists(raw_contours):
        arcpy.management.Delete(raw_contours)

    try:
        if method == "TIN":
            tin = str(Path(str(scratch)).parent / f"gwe_tin_{site_id}")
            if arcpy.Exists(tin):
                arcpy.management.Delete(tin)
            arcpy.ddd.CreateTin(tin, sr, [[pt_fc, "GWE", "Mass_Points"]])
            arcpy.ddd.SurfaceContour(tin, raw_contours, contour_interval)
        else:
            xs = [p[1] for p in pts]; ys = [p[2] for p in pts]
            cs = cell_size or max((max(xs) - min(xs)),
                                  (max(ys) - min(ys)), 1.0) / 250.0
            if method == "IDW":
                ras = arcpy.sa.Idw(pt_fc, "GWE", cs)
            elif method == "EBK":
                # Slice-2 D1 (ADR-0077 doc-verified 2026-07-16): EBK
                # prediction raster -> the same sa.Contour path as IDW,
                # honoring contour_interval; the standard-error companion
                # raster (D3) is exported here and published below only
                # after the contours succeed.
                ras = str(scratch / f"gwe_ebk_{site_id}")
                if arcpy.Exists(ras):
                    arcpy.management.Delete(ras)
                lyr = f"gwe_ebk_lyr_{site_id}"
                arcpy.ga.EmpiricalBayesianKriging(pt_fc, "GWE", lyr, ras, cs)
                ebk_se_scratch = str(scratch / f"gwe_ebk_se_{site_id}")
                if arcpy.Exists(ebk_se_scratch):
                    arcpy.management.Delete(ebk_se_scratch)
                arcpy.ga.GALayerToRasters(lyr, ebk_se_scratch,
                                          "PREDICTION_STANDARD_ERROR",
                                          cell_size=cs)
            else:
                ras = arcpy.sa.NaturalNeighbor(pt_fc, "GWE", cs)
            arcpy.sa.Contour(ras, raw_contours, contour_interval)
    except Exception as exc:  # pragma: no cover - arcpy runtime only
        qa.add(SEV_ERROR, "contour_generation_failed",
               f"{method} contouring failed: {exc}", site_id=site_id)
        summary["skipped"] = True
        return summary
    finally:
        for ext in needs:
            arcpy.CheckInExtension(ext)

    clipped = raw_contours
    if boundary_fc and arcpy.Exists(boundary_fc):
        clipped = str(scratch / f"gwe_ctr_clip_{site_id}")
        if arcpy.Exists(clipped):
            arcpy.management.Delete(clipped)
        arcpy.analysis.Clip(raw_contours, boundary_fc, clipped)

    out_fc = str(gdb / "Env_GWContours_Draft")
    where = f"SiteID = '{site_id}' AND " + _where_date("EventDate", event_date)
    # Replace only THIS method's draft rows: multi-method runs (the ADR-0085
    # pipeline) must not have the second method wipe the first's contours
    # (PR #240 review). Flow-arrow replacement below stays event-scoped — it
    # is method-independent (plane fit of the same points).
    ctr_where = where + f" AND InterpolationMethod = '{method}'"
    with arcpy.da.UpdateCursor(out_fc, ["OID@"],
                               where_clause=ctr_where) as cur:
        for _ in cur:
            cur.deleteRow()
    n = 0
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    note = f"Auto-generated {stamp}; review required"
    with arcpy.da.SearchCursor(clipped, ["Contour", "SHAPE@"]) as src, \
            arcpy.da.InsertCursor(
                out_fc,
                ["SiteID", "EventDate", "ContourElevation",
                 "ContourInterval", "InterpolationMethod", "ReviewStatus",
                 "Notes", "SHAPE@"]) as dst:
        for elev, shape in src:
            dst.insertRow([site_id, ev_dt, elev, contour_interval, method,
                           "DRAFT", note, shape])
            n += 1
    summary["contours_written"] = n

    grad = fit_plane_gradient([(x, y, z) for _l, x, y, z in pts])
    if grad is not None:
        gx, gy = grad
        mag = math.hypot(gx, gy)
        cx = sum(p[1] for p in pts) / len(pts)
        cy = sum(p[2] for p in pts) / len(pts)
        xs = [p[1] for p in pts]; ys = [p[2] for p in pts]
        arrow_len = 0.15 * max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        ex = cx + arrow_len * gx / mag
        ey = cy + arrow_len * gy / mag
        az = (math.degrees(math.atan2(gx, gy)) + 360.0) % 360.0
        fa_fc = str(gdb / "Env_GWFlowArrow_Draft")
        with arcpy.da.UpdateCursor(fa_fc, ["OID@"],
                                   where_clause=where) as cur:
            for _ in cur:
                cur.deleteRow()
        arr = arcpy.Array([arcpy.Point(cx, cy), arcpy.Point(ex, ey)])
        with arcpy.da.InsertCursor(
                fa_fc, ["SiteID", "EventDate", "PlacementMethod",
                        "ReviewStatus", "Notes", "SHAPE@"]) as cur:
            cur.insertRow([site_id, ev_dt, "computed_draft", "DRAFT",
                           f"Plane-fit azimuth {az:.0f} deg from "
                           f"{len(pts)} wells; {note}",
                           arcpy.Polyline(arr, sr)])
        summary["flow_arrow"] = True
        qa.add(SEV_INFO, "flow_arrow_draft",
               f"Draft flow arrow azimuth {az:.0f} deg from plane fit of "
               f"{len(pts)} wells. REQUIRES professional review.",
               site_id=site_id)
    else:
        qa.add(SEV_WARNING, "flow_arrow_degenerate",
               "Gradient fit degenerate (collinear wells or flat surface); "
               "no flow arrow generated.", site_id=site_id)

    if method == "EBK":
        # Publish the standard-error companion raster (slice-2 D3): only
        # after the contours succeeded, Draft_ prefix + registry row.
        from autogis.core.envmon.concentration_surface import (
            build_surface_registry_rows, slug, write_surface_registry_rows,
        )
        se_name = f"Draft_GWE_{slug(site_id)}_{ev_dt:%Y%m%d}_EBK_SE"
        final = str(gdb / se_name)
        if arcpy.Exists(final):
            arcpy.management.Delete(final)
        arcpy.management.CopyRaster(ebk_se_scratch, final)
        summary["se_raster"] = se_name
        rows = build_surface_registry_rows(
            site_id, event_date, "GWE", "", "EBK", "", {"STD_ERROR": se_name},
            _dt.datetime.now())
        if not write_surface_registry_rows(gdb, rows):
            qa.add(SEV_ERROR, "surface_registry_missing",
                   "Env_SurfaceRegistry missing — run upgrade-schema (v2.5). "
                   f"{se_name} written but NOT registered.", site_id=site_id)
        else:
            qa.add(SEV_INFO, "uncertainty_raster_generated",
                   f"DRAFT EBK standard-error raster {se_name} registered "
                   "in Env_SurfaceRegistry (ReviewStatus=DRAFT).",
                   site_id=site_id)

    qa.add(SEV_INFO, "contours_draft_generated",
           f"{n} DRAFT contour lines ({method}, {contour_interval} ft "
           f"interval) from {len(pts)} wells. All output is "
           "ReviewStatus=DRAFT and must be reviewed before use.",
           site_id=site_id)
    return summary
