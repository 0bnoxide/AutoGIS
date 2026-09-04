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
ADR-0077 doc-verification refreshed 2026-07-29:
EmpiricalBayesianKriging, GALayerToRasters (Geostatistical Analyst), Idw
(Spatial Analyst), management.CreateFeatureclass / AddField / Delete / Clip /
GetRasterProperties / CopyRaster, da.InsertCursor, and Raster.save — current
at Pro 3.6 and present at the Pro 3.5 compliance floor.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.common.units import UnitError, convert, normalize_unit
from autogis.core.envmon.canonical_read import canonical_result_rows
from autogis.core.envmon.export_geojson import load_well_coords

NONDETECT_RULES = ("exclude", "half_rl", "use_rl", "use_zero")
SURFACE_METHODS = ("IDW", "EBK")
EBK_MIN_NEIGHBORS = 10

# (LocationID, x, y, concentration) — mirrors the contour-point shape.
ConcPoint = Tuple[str, float, float, float]

_DRAFT_WARNING = (
    "DRAFT: interpolated concentration surface for analyst review only. "
    "Do not cite in regulatory deliverables without professional review. "
    "ReviewStatus=DRAFT in Env_SurfaceRegistry."
)
_GWE_DRAFT_WARNING = (
    "DRAFT: groundwater-elevation model uncertainty surface for reviewer "
    "use only. Do not cite in regulatory deliverables without professional "
    "review. ReviewStatus=DRAFT in Env_SurfaceRegistry."
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
    site_id: str,
    event_date: str,
    analyte: str,
    nondetect_rule: str = "exclude",
    surface_unit: str = "ug/L",
    matrix: Optional[str] = None,
    qa: QACollector,
) -> List[ConcPoint]:
    """Per-well concentration points for one site/event/analyte surface.

    Canonical-read first (fraction pairs resolved, QC rows dropped —
    ADR-0075). Rows are scoped to the requested SiteID, SampleDate
    (== event_date), optional Matrix, and analyte — a multi-site or
    multi-event export must never leak a foreign value into this surface
    (#241 review). Values (and the RL/DL a nondetect rule substitutes)
    are normalized into the declared ``surface_unit`` via the ADR-0022
    registry; rows with an unknown unit or a cross-dimension unit (e.g.
    mg/kg into an aqueous surface) warn and drop rather than corrupt the
    MAX aggregation. One point per well: MAX normalized value
    (conservative for plume mapping). Wells with no coordinates warn and
    drop, matching draft-plume-boundary.
    """
    if normalize_unit(surface_unit) is None:
        raise ValueError(f"surface_unit not in the ADR-0022 unit registry: "
                         f"{surface_unit!r}")
    coords = load_well_coords(coords_path)
    best: Dict[str, float] = {}
    with Path(results_path).open(newline="", encoding="utf-8") as fh:
        for row in canonical_result_rows(list(csv.DictReader(fh)), qa):
            if row.get("SiteID", "").strip() != site_id:
                continue
            if str(row.get("SampleDate", "")).strip()[:10] != event_date:
                continue
            if matrix is not None and \
                    row.get("Matrix", "").strip() != matrix:
                continue
            if row.get("AnalyteCanonicalName", "").strip() != analyte:
                continue
            v = resolve_result_value(row, nondetect_rule, qa)
            if v is None:
                continue
            loc = row.get("LocationID", "").strip()
            if not loc:
                continue
            row_unit = row.get("Units", "").strip()
            try:
                v = convert(v, row_unit, surface_unit)
            except UnitError as exc:
                qa.add(SEV_WARNING, "surface_unit_mismatch",
                       f"{loc}/{analyte}: {exc}; row excluded from the "
                       f"{surface_unit} surface.", location_id=loc)
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


def surface_tag(*parts) -> str:
    """Bounded, collision-resistant identity fragment (#241 review).

    slug() is lossy ('Ben zene' == 'Ben/zene'), so a readable sanitized
    prefix is paired with a stable sha1-8 of the ORIGINAL identity; the
    registry key keeps the originals, the raster/scratch names carry this.
    """
    raw = "|".join(str(p) for p in parts)
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    prefix = "_".join(slug(p)[:16] for p in parts if str(p).strip()) or "X"
    return f"{prefix[:40]}_{h}"


def scratch_tag(site_id: str, analyte: str) -> str:
    """Collision-resistant per-run scratch identity (#383)."""
    return f"{surface_tag(site_id, analyte)}_{uuid.uuid4().hex[:12]}"


def minimum_surface_points(method: str, configured_minimum: int = 4) -> int:
    """Method-aware preflight floor.

    ArcGIS Pro 3.6's default EBK standard circular neighborhood reports
    NBR_MIN=10 (live pin 2026-07-29); IDW keeps the caller-configured floor.
    """
    if method not in SURFACE_METHODS:
        raise ValueError(
            f"method must be one of {SURFACE_METHODS}, got {method!r}")
    return max(int(configured_minimum),
               EBK_MIN_NEIGHBORS if method == "EBK" else 0)


def raster_names(site_id: str, event_date: str, analyte: str,
                 method: str) -> Dict[str, str]:
    """Draft_ raster names per spec D3: PREDICTION and (EBK only) STD_ERROR."""
    ev = event_date.replace("-", "")
    base = f"Draft_Conc_{surface_tag(site_id, analyte)}_{ev}_{method}"
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
    units: str = "",
) -> List[dict]:
    """Shape Env_SurfaceRegistry rows (one per raster type) — spec D3.

    ``units`` is the declared surface unit the raster values are in
    ('ug/L' for CONC, 'ft' for GWE) — provenance the raster itself cannot
    carry (#241 review).
    """
    return [{
        "SiteID": site_id, "EventDate": event_date, "SurfaceKind": kind,
        "AnalyteFilter": analyte, "Method": method, "RasterType": rtype,
        "NondetectRule": nondetect_rule, "Units": units, "RasterPath": name,
        "ReviewStatus": "DRAFT", "CreatedAt": now,
        "Notes": (_GWE_DRAFT_WARNING if kind == "GWE"
                  else _DRAFT_WARNING)[:200],  # #522
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
              "Method", "RasterType", "NondetectRule", "Units",
              "RasterPath", "ReviewStatus", "CreatedAt", "Notes"]

    def _q(v: str) -> str:
        # Apostrophe analytes (4,4'-DDT) are routine — escape every
        # interpolated value (#slice-2 review; pattern from approve_gw_model).
        return str(v).replace("'", "''")

    for r in rows:
        ymd = r["EventDate"]
        where = (f"SiteID = '{_q(r['SiteID'])}' AND "
                 f"SurfaceKind = '{_q(r['SurfaceKind'])}' AND "
                 f"AnalyteFilter = '{_q(r['AnalyteFilter'])}' AND "
                 f"Method = '{_q(r['Method'])}' AND "
                 f"RasterType = '{_q(r['RasterType'])}' AND "
                 f"EventDate >= date '{ymd} 00:00:00' AND "
                 f"EventDate <= date '{ymd} 23:59:59'")
        with arcpy.da.UpdateCursor(tbl, ["OID@"], where_clause=where) as cur:
            for _ in cur:
                cur.deleteRow()
        ev_dt = _dt.datetime.strptime(r["EventDate"], "%Y-%m-%d")
        with arcpy.da.InsertCursor(tbl, fields) as cur:
            cur.insertRow([r["SiteID"], ev_dt, r["SurfaceKind"],
                           r["AnalyteFilter"], r["Method"], r["RasterType"],
                           r["NondetectRule"], r["Units"], r["RasterPath"],
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
    surface_unit: str = "ug/L",
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
    required_points = minimum_surface_points(method, min_valid_points)
    if len(points) < required_points:
        qa.add(SEV_ERROR, "insufficient_surface_points",
               f"{method} requires at least {required_points} usable "
               f"{analyte} point(s) for {site_id} {event_date}; only "
               f"{len(points)} available. Surface skipped before scratch "
               "datasets or extension checkout; existing drafts untouched.",
               recommended_action=(
                   "Add wells or choose a nondetect rule that supplies at "
                   f"least {required_points} usable points."),
               site_id=site_id)
        summary["skipped"] = True
        return summary

    # Fail fast, before any license checkout or interpolation spend.
    if boundary_fc and not arcpy.Exists(boundary_fc):
        qa.add(SEV_ERROR, "boundary_missing",
               f"Requested boundary clip but {boundary_fc} does not "
               "exist. Surface skipped; existing drafts untouched.",
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

    # Interpolate into scratch; clip (if requested) also into scratch —
    # only a fully validated result replaces the existing draft rasters.
    # The checkout loop itself is inside try/finally and only extensions
    # actually acquired are checked back in (#241 review), so any failure
    # (partial checkout, missing MonitoringWells, EBK error, bad clip)
    # surfaces as QA without leaking a license.
    scratch_rasters: Dict[str, str] = {}
    scratch_objects: List[str] = []
    acquired: List[str] = []
    tag = scratch_tag(site_id, analyte)
    try:
        try:
            for e in need:
                arcpy.CheckOutExtension(e)
                acquired.append(e)
            scratch = Path(str(scratch or arcpy.env.scratchGDB))
            pt_name = f"conc_pts_{tag}"
            pt_fc = str(scratch / pt_name)
            scratch_objects.append(pt_fc)
            sr = arcpy.Describe(str(Path(str(gdb)) / "MonitoringWells")
                                ).spatialReference
            arcpy.management.CreateFeatureclass(
                str(scratch), pt_name, "POINT", spatial_reference=sr)
            arcpy.management.AddField(pt_fc, "CONC", "DOUBLE")
            with arcpy.da.InsertCursor(pt_fc, ["SHAPE@XY", "CONC"]) as cur:
                for _loc, x, y, v in points:
                    cur.insertRow([(x, y), v])

            xs = [p[1] for p in points]; ys = [p[2] for p in points]
            cs = cell_size or max((max(xs) - min(xs)), (max(ys) - min(ys)),
                                  1.0) / 250.0

            pred = str(scratch / f"conc_pred_{tag}")
            scratch_objects.append(pred)
            if method == "IDW":
                arcpy.sa.Idw(pt_fc, "CONC", cs).save(pred)
            else:
                lyr = f"conc_ebk_lyr_{tag}"
                scratch_objects.append(lyr)
                arcpy.ga.EmpiricalBayesianKriging(
                    pt_fc, "CONC", lyr, pred, cs)
                se = str(scratch / f"conc_se_{tag}")
                scratch_objects.append(se)
                arcpy.ga.GALayerToRasters(
                    lyr, se, "PREDICTION_STANDARD_ERROR", cell_size=cs)
                scratch_rasters["STD_ERROR"] = se
            scratch_rasters["PREDICTION"] = pred

            if boundary_fc:
                for rtype, ras in list(scratch_rasters.items()):
                    clipped = ras + "_clip"
                    scratch_objects.append(clipped)
                    arcpy.management.Clip(
                        ras, "#", clipped, boundary_fc, "",
                        "ClippingGeometry")
                    scratch_rasters[rtype] = clipped
                # A disjoint boundary can clip to all-NoData without raising.
                # GetRasterProperties(ALLNODATA) is the direct test (#241
                # review; ADR-0077 doc-verified 2026-07-16): '1' = confirmed
                # empty. An inspection failure is reported as its own QA
                # category, distinct from confirmed no-overlap — both skip
                # before any draft is replaced (spec D5).
                try:
                    allnodata = str(arcpy.management.GetRasterProperties(
                        scratch_rasters["PREDICTION"], "ALLNODATA"
                    ).getOutput(0)).strip()
                except Exception as exc:
                    qa.add(SEV_ERROR, "boundary_clip_inspect_failed",
                           f"Could not inspect the clipped raster ({exc}). "
                           "Surface skipped; existing drafts untouched.",
                           site_id=site_id)
                    summary["skipped"] = True
                    return summary
                if allnodata == "1":
                    qa.add(SEV_ERROR, "boundary_clip_empty",
                           f"Boundary clip produced no data (no overlap "
                           f"between {boundary_fc} and the interpolated "
                           "extent). Surface skipped; existing drafts "
                           "untouched.", site_id=site_id)
                    summary["skipped"] = True
                    return summary
        except Exception as exc:
            qa.add(SEV_ERROR, "surface_generation_failed",
                   f"{method} concentration surface failed: {exc}. Existing "
                   "drafts untouched.", site_id=site_id)
            summary["skipped"] = True
            return summary

        # Publish stage. Delete-then-copy cannot be atomic in a GDB; guard it
        # so a mid-loop failure (e.g. the old draft lock-held by an open map)
        # surfaces as QA with an explicit partial-replace warning, never a raw
        # traceback after drafts were already touched (#slice-2 review).
        names = raster_names(site_id, event_date, analyte, method)
        try:
            for rtype, name in names.items():
                final = str(Path(str(gdb)) / name)
                if arcpy.Exists(final):
                    arcpy.management.Delete(final)
                arcpy.management.CopyRaster(scratch_rasters[rtype], final)
                summary["rasters"][rtype] = name
        except Exception as exc:
            qa.add(SEV_ERROR, "surface_publish_failed",
                   f"Publishing {method} {analyte} raster(s) failed: {exc}. "
                   f"Written so far: {summary['rasters'] or 'none'} — "
                   "existing drafts may be partially replaced; close any "
                   "map layers locking them and re-run.", site_id=site_id)
            summary["skipped"] = True
            return summary

        rows = build_surface_registry_rows(
            site_id, event_date, "CONC", analyte, method, nondetect_rule,
            names, _dt.datetime.now(), units=surface_unit)
        summary["registry_written"] = write_surface_registry_rows(gdb, rows)
        if not summary["registry_written"]:
            qa.add(SEV_ERROR, "surface_registry_missing",
                   "Env_SurfaceRegistry missing — run upgrade-schema (v2.5) "
                   "first. Raster written but NOT registered.",
                   site_id=site_id)
        else:
            qa.add(SEV_INFO, "concentration_surface_generated",
                   f"DRAFT {method} {analyte} surface ({surface_unit}) from "
                   f"{len(points)} well(s), "
                   f"nondetect_rule={nondetect_rule}. {_DRAFT_WARNING}",
                   site_id=site_id)
        return summary
    finally:
        for obj in reversed(scratch_objects):
            try:
                if arcpy.Exists(obj):
                    arcpy.management.Delete(obj)
            except Exception as exc:
                qa.add(
                    SEV_WARNING, "scratch_cleanup_failed",
                    f"Could not delete scratch object {obj}: {exc}. Close "
                    "ArcGIS Pro layers or release locks, then delete this "
                    "path manually before retrying.",
                    recommended_action=(
                        f"Close layers using {obj}, delete it from Catalog, "
                        "then rerun Build Concentration Surface."),
                    site_id=site_id)
        for e in acquired:
            arcpy.CheckInExtension(e)
