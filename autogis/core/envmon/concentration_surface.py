"""concentration_surface.py — DRAFT continuous concentration surface (slice 2).

BuildAnalyticalConcentrationSurface, Phase-5 slice 2 (ADR-0085; spec
docs/superpowers/specs/2026-07-16-geostat-slice2-design.md): interpolate a
per-analyte concentration raster (IDW or EBK) from well results, apply the
configurable nondetect policy (ADR-0085 decision 4), optionally clip to the
site boundary, and register the raster in Env_SurfaceRegistry.

DRAFT convention for rasters (spec D3): rasters cannot carry a ReviewStatus
field, so outputs get a ``Draft_`` name prefix plus an Env_SurfaceRegistry
row with ReviewStatus='DRAFT', and every run emits a SEV_INFO referencing
DRAFT.

Headless (unit-tested): nondetect policy, point collection, raster naming,
registry-row shaping. arcpy work lives in the ``# pragma: no cover`` seams.
ADR-0077 doc-verification (this session, 2026-07-16): EmpiricalBayesianKriging,
GALayerToRasters (Geostatistical Analyst), Idw (Spatial Analyst),
management.Clip / CopyRaster / Raster.save (no extension) — all current,
none deprecated at Pro 3.x.
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.canonical_read import canonical_result_rows
from autogis.core.envmon.export_geojson import load_well_coords

NONDETECT_RULES = ("exclude", "half_rl", "use_rl", "use_zero")
SURFACE_METHODS = ("IDW", "EBK")

# (LocationID, x, y, concentration) — mirrors the contour-point shape.
ConcPoint = Tuple[str, float, float, float]

_DRAFT_WARNING = (
    "DRAFT: interpolated concentration surface for analyst review only. "
    "Do not cite in regulatory deliverables without professional review. "
    "ReviewStatus=DRAFT in Env_SurfaceRegistry."
)


def _num(row: dict, field: str) -> Optional[float]:
    try:
        v = str(row.get(field, "")).strip()
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def resolve_result_value(row: dict, rule: str,
                         qa: QACollector) -> Optional[float]:
    """Numeric value for one canonical result row under a nondetect rule.

    Detected results return ResultNumeric. Nondetects follow the rule
    (ADR-0085 decision 4): exclude -> None; half_rl / use_rl -> the
    ReportingLimit (x0.5 for half_rl), falling back to DetectionLimit;
    use_zero -> 0.0. A substitution rule with neither limit available
    excludes the row with a SEV_WARNING — inventing a value would be worse.
    """
    if rule not in NONDETECT_RULES:
        raise ValueError(
            f"nondetect_rule must be one of {NONDETECT_RULES}, got {rule!r}")
    nondetect = str(row.get("IsNonDetect", "")).strip() == "1"
    if not nondetect:
        return _num(row, "ResultNumeric")
    if rule == "exclude":
        return None
    if rule == "use_zero":
        return 0.0
    limit = _num(row, "ReportingLimit")
    if limit is None:
        limit = _num(row, "DetectionLimit")
    if limit is None:
        qa.add(SEV_WARNING, "nondetect_no_limit",
               f"{row.get('LocationID', '?')}/"
               f"{row.get('AnalyteCanonicalName', '?')}: nondetect with no "
               f"ReportingLimit or DetectionLimit; excluded despite "
               f"rule={rule}.",
               location_id=str(row.get("LocationID", "")))
        return None
    return limit * 0.5 if rule == "half_rl" else limit


def collect_concentration_points(
    results_path: Path,
    coords_path: Path,
    *,
    analyte: str,
    nondetect_rule: str = "exclude",
    qa: QACollector,
) -> List[ConcPoint]:
    """Per-well concentration points for one analyte, policy applied.

    Canonical-read first (fraction pairs resolved, QC rows dropped —
    ADR-0075), then the nondetect rule, then one point per well using the
    MAX value across its rows (conservative for plume mapping). Wells with
    no coordinates warn and drop, matching draft-plume-boundary.
    """
    coords = load_well_coords(coords_path)
    best: Dict[str, float] = {}
    with Path(results_path).open(newline="", encoding="utf-8") as fh:
        for row in canonical_result_rows(list(csv.DictReader(fh)), qa):
            if row.get("AnalyteCanonicalName", "").strip() != analyte:
                continue
            v = resolve_result_value(row, nondetect_rule, qa)
            if v is None:
                continue
            loc = row.get("LocationID", "").strip()
            if not loc:
                continue
            if loc not in best or v > best[loc]:
                best[loc] = v
    pts: List[ConcPoint] = []
    for loc, v in best.items():
        if loc not in coords:
            qa.add(SEV_WARNING, "missing_coords",
                   f"{loc}: has a usable {analyte} value but no coordinates "
                   "in the coords CSV; excluded from the surface.",
                   location_id=loc)
            continue
        x, y = coords[loc]
        pts.append((loc, x, y, v))
    return pts


def slug(text: str) -> str:
    """GDB-legal identifier fragment (alnum/underscore, no leading digit)."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(text).strip()) or "X"
    return ("_" + s) if s[0].isdigit() else s


def raster_names(site_id: str, event_date: str, analyte: str,
                 method: str) -> Dict[str, str]:
    """Draft_ raster names per spec D3: PREDICTION and (EBK only) STD_ERROR."""
    ev = event_date.replace("-", "")
    base = f"Draft_Conc_{slug(site_id)}_{ev}_{slug(analyte)}_{method}"
    names = {"PREDICTION": base}
    if method == "EBK":
        names["STD_ERROR"] = base + "_SE"
    return names


def build_surface_registry_rows(
    site_id: str,
    event_date: str,
    kind: str,
    analyte: str,
    method: str,
    nondetect_rule: str,
    rasters: Dict[str, str],
    now: _dt.datetime,
) -> List[dict]:
    """Shape Env_SurfaceRegistry rows (one per raster type) — spec D3."""
    return [{
        "SiteID": site_id, "EventDate": event_date, "SurfaceKind": kind,
        "AnalyteFilter": analyte, "Method": method, "RasterType": rtype,
        "NondetectRule": nondetect_rule, "RasterPath": name,
        "ReviewStatus": "DRAFT", "CreatedAt": now,
        "Notes": f"{_DRAFT_WARNING[:200]}",
    } for rtype, name in sorted(rasters.items())]


# ---------------------------------------------------------------------------
# arcpy seams — LOCAL only (ArcGIS Pro)
# ---------------------------------------------------------------------------

def write_surface_registry_rows(gdb, rows: Sequence[dict]
                                ) -> bool:  # pragma: no cover
    """Replace-then-insert registry rows. False if the table is missing
    (run upgrade-schema v2.5 first) — callers must not report success then."""
    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    tbl = str(Path(str(gdb)) / "Env_SurfaceRegistry")
    if not arcpy.Exists(tbl):
        return False
    fields = ["SiteID", "EventDate", "SurfaceKind", "AnalyteFilter",
              "Method", "RasterType", "NondetectRule", "RasterPath",
              "ReviewStatus", "CreatedAt", "Notes"]
    for r in rows:
        ymd = r["EventDate"]
        where = (f"SiteID = '{r['SiteID']}' AND "
                 f"SurfaceKind = '{r['SurfaceKind']}' AND "
                 f"AnalyteFilter = '{r['AnalyteFilter']}' AND "
                 f"Method = '{r['Method']}' AND "
                 f"RasterType = '{r['RasterType']}' AND "
                 f"EventDate >= date '{ymd} 00:00:00' AND "
                 f"EventDate <= date '{ymd} 23:59:59'")
        with arcpy.da.UpdateCursor(tbl, ["OID@"], where_clause=where) as cur:
            for _ in cur:
                cur.deleteRow()
        ev_dt = _dt.datetime.strptime(r["EventDate"], "%Y-%m-%d")
        with arcpy.da.InsertCursor(tbl, fields) as cur:
            cur.insertRow([r["SiteID"], ev_dt, r["SurfaceKind"],
                           r["AnalyteFilter"], r["Method"], r["RasterType"],
                           r["NondetectRule"], r["RasterPath"],
                           r["ReviewStatus"], r["CreatedAt"], r["Notes"]])
    return True


def build_concentration_surface(  # pragma: no cover
    gdb,
    site_id: str,
    event_date: str,
    analyte: str,
    points: Sequence[ConcPoint],
    qa: QACollector,
    method: str = "IDW",
    nondetect_rule: str = "exclude",
    cell_size: Optional[float] = None,
    boundary_fc: Optional[str] = None,
    min_valid_points: int = 4,
    scratch: Optional[Path] = None,
) -> dict:
    """Interpolate + optionally clip + write the DRAFT surface (LOCAL).

    License degrade matches groundwater_contours: missing license ->
    SEV_ERROR + skip. Boundary-clip contract matches the plume tool
    (PR #240 review): a requested clip that cannot happen — missing FC or
    a failed clip — skips the run BEFORE any existing draft raster or
    registry row is replaced.
    """
    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()

    if method not in SURFACE_METHODS:
        raise ValueError(
            f"method must be one of {SURFACE_METHODS}, got {method!r}")
    if nondetect_rule not in NONDETECT_RULES:
        raise ValueError(
            f"nondetect_rule must be one of {NONDETECT_RULES}, "
            f"got {nondetect_rule!r}")
    try:
        _dt.datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"event_date must be YYYY-MM-DD, got {event_date!r}")

    summary = {"points": len(points), "rasters": {}, "skipped": False,
               "registry_written": False}
    if len(points) < min_valid_points:
        qa.add(SEV_ERROR, "insufficient_surface_points",
               f"Only {len(points)} usable {analyte} point(s) for {site_id} "
               f"{event_date} (minimum {min_valid_points}). Surface skipped.",
               recommended_action="Add wells or relax the nondetect rule.",
               site_id=site_id)
        summary["skipped"] = True
        return summary

    need = ("Spatial",) if method == "IDW" else ("GeoStats",)
    missing = [e for e in need if arcpy.CheckExtension(e) != "Available"]
    if missing:
        qa.add(SEV_ERROR, "license_unavailable",
               f"{'/'.join(missing)} license unavailable; {method} "
               "concentration surface skipped.", site_id=site_id)
        summary["skipped"] = True
        return summary
    for e in need:
        arcpy.CheckOutExtension(e)

    scratch = Path(str(scratch or arcpy.env.scratchGDB))
    pt_fc = str(scratch / "conc_pts")
    sr = arcpy.Describe(str(Path(str(gdb)) / "MonitoringWells")
                        ).spatialReference
    if arcpy.Exists(pt_fc):
        arcpy.management.Delete(pt_fc)
    arcpy.management.CreateFeatureclass(str(scratch), "conc_pts", "POINT",
                                        spatial_reference=sr)
    arcpy.management.AddField(pt_fc, "CONC", "DOUBLE")
    with arcpy.da.InsertCursor(pt_fc, ["SHAPE@XY", "CONC"]) as cur:
        for _loc, x, y, v in points:
            cur.insertRow([(x, y), v])

    xs = [p[1] for p in points]; ys = [p[2] for p in points]
    cs = cell_size or max((max(xs) - min(xs)), (max(ys) - min(ys)),
                          1.0) / 250.0

    # Interpolate into scratch; clip (if requested) also into scratch —
    # only a fully validated result replaces the existing draft rasters.
    scratch_rasters: Dict[str, str] = {}
    try:
        pred = str(scratch / "conc_pred")
        if arcpy.Exists(pred):
            arcpy.management.Delete(pred)
        if method == "IDW":
            arcpy.sa.Idw(pt_fc, "CONC", cs).save(pred)
        else:
            lyr = "conc_ebk_lyr"
            arcpy.ga.EmpiricalBayesianKriging(pt_fc, "CONC", lyr, pred, cs)
            se = str(scratch / "conc_se")
            if arcpy.Exists(se):
                arcpy.management.Delete(se)
            arcpy.ga.GALayerToRasters(lyr, se, "PREDICTION_STANDARD_ERROR",
                                      cell_size=cs)
            scratch_rasters["STD_ERROR"] = se
        scratch_rasters["PREDICTION"] = pred

        if boundary_fc:
            if not arcpy.Exists(boundary_fc):
                qa.add(SEV_ERROR, "boundary_missing",
                       f"Requested boundary clip but {boundary_fc} does not "
                       "exist. Surface skipped; existing drafts untouched.",
                       site_id=site_id)
                summary["skipped"] = True
                return summary
            for rtype, ras in list(scratch_rasters.items()):
                clipped = ras + "_clip"
                if arcpy.Exists(clipped):
                    arcpy.management.Delete(clipped)
                arcpy.management.Clip(ras, "#", clipped, boundary_fc, "",
                                      "ClippingGeometry")
                scratch_rasters[rtype] = clipped
    except Exception as exc:
        qa.add(SEV_ERROR, "surface_generation_failed",
               f"{method} concentration surface failed: {exc}. Existing "
               "drafts untouched.", site_id=site_id)
        summary["skipped"] = True
        return summary
    finally:
        for e in need:
            arcpy.CheckInExtension(e)

    names = raster_names(site_id, event_date, analyte, method)
    for rtype, name in names.items():
        final = str(Path(str(gdb)) / name)
        if arcpy.Exists(final):
            arcpy.management.Delete(final)
        arcpy.management.CopyRaster(scratch_rasters[rtype], final)
        summary["rasters"][rtype] = name

    rows = build_surface_registry_rows(
        site_id, event_date, "CONC", analyte, method, nondetect_rule,
        names, _dt.datetime.now())
    summary["registry_written"] = write_surface_registry_rows(gdb, rows)
    if not summary["registry_written"]:
        qa.add(SEV_ERROR, "surface_registry_missing",
               "Env_SurfaceRegistry missing — run upgrade-schema (v2.5) "
               "first. Raster written but NOT registered.", site_id=site_id)
    else:
        qa.add(SEV_INFO, "concentration_surface_generated",
               f"DRAFT {method} {analyte} surface from {len(points)} "
               f"well(s), nondetect_rule={nondetect_rule}. "
               f"{_DRAFT_WARNING}", site_id=site_id)
    return summary
