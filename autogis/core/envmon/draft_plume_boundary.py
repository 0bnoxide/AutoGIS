"""draft_plume_boundary.py — DRAFT plume extent polygon from exceedance points.

WARNING: All output is ReviewStatus='DRAFT'. This module builds a geometric
approximation (convex or concave hull) around wells exceeding a screening
level. It is a drafting aid for analyst review — NOT a geostatistical surface
model, NOT a regulatory deliverable. Phase 5 kriging/EBK is deferred and
separate (docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md Phase 5).

DRAFT label appears on every output path:
  - GeoJSON properties:  "review_status": "DRAFT", "draft_warning": "<text>"
  - WKT console output:  printed with [DRAFT] prefix
  - GDB feature class:   ReviewStatus = "DRAFT"  (matches groundwater_contours.py)
  - QA messages:         every run emits a SEV_INFO referencing DRAFT

arcpy usage: ONLY in write_plume_draft_to_gdb() — # pragma: no cover.
All other functions import without arcpy or arcgis.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from autogis.core.envmon.canonical_read import canonical_result_rows
from autogis.core.common.numpy_geom import convex_hull, concave_hull
from autogis.core.envmon.export_geojson import load_well_coords


_DRAFT_WARNING = (
    "DRAFT: Geometric approximation (hull around exceedance points) for "
    "analyst review only. Not a geostatistical model. Do not cite in "
    "regulatory deliverables without professional review and field "
    "verification. Phase 5 geostatistical modeling (kriging/EBK) is "
    "deferred."
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ExceedancePoint:
    """A monitoring location where at least one analyte exceeds a screening level."""
    location_id: str
    x: float
    y: float
    analyte: Optional[str] = None
    event_date: Optional[str] = None


@dataclass
class DraftPlumeBoundaryResult:
    """Result of a draft plume boundary computation.

    hull_vertices is an OPEN ring: last vertex != first.
    Serializers (result_to_geojson, result_to_wkt) are responsible for closing
    the ring by appending hull_vertices[0].
    review_status is always 'DRAFT'.
    """
    site_id: str
    analyte: Optional[str]            # None = all exceedances combined
    hull_method: str                   # "convex" | "concave"
    k_neighbors: Optional[int]        # only relevant for concave
    n_exceedance_points: int
    hull_vertices: list[list[float]]  # open ring: [[x0,y0], [x1,y1], ...]
    review_status: str = "DRAFT"      # always "DRAFT" — do not override
    draft_warning: str = _DRAFT_WARNING


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_exceedance_points_csv(path: Path) -> list[ExceedancePoint]:
    """Load from a simple CSV with columns: location_id, x, y [, analyte, event_date].

    All rows are treated as exceedance points (caller is responsible for
    pre-filtering to exceedances only).
    """
    pts: list[ExceedancePoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pts.append(ExceedancePoint(
                location_id=row["location_id"].strip(),
                x=float(row["x"]),
                y=float(row["y"]),
                analyte=row.get("analyte", "").strip() or None,
                event_date=row.get("event_date", "").strip() or None,
            ))
    return pts


def filter_results_to_exceedance_points(
    results_path: Path,
    coords_path: Path,
    *,
    analyte: Optional[str] = None,
    qa: QACollector,
) -> list[ExceedancePoint]:
    """Filter an AnalyticalResultRecord CSV to exceedance points with coordinates.

    Reads coords via export_geojson.load_well_coords (columns: location_id, x, y).
    Filters rows by ExceedsScreeningLevel == '1'.
    Applies optional analyte filter (AnalyteCanonicalName).
    Deduplicates: one ExceedancePoint per well (first exceedance wins when
    no analyte filter; any exceedance qualifies the well).
    Emits SEV_WARNING for wells with exceedances but no coordinates.
    """
    coords = load_well_coords(coords_path)
    seen: set[str] = set()
    pts: list[ExceedancePoint] = []
    with Path(results_path).open(newline="", encoding="utf-8") as fh:
        # Canonical-read before the per-well exceedance dedup: resolve fraction
        # pairs and drop QC rows so a well exceeding only on the non-preferred
        # fraction (or in a QC blank) never seeds a plume vertex (ADR-0075).
        for row in canonical_result_rows(list(csv.DictReader(fh)), qa):
            if str(row.get("ExceedsScreeningLevel", "0")).strip() != "1":
                continue
            a = row.get("AnalyteCanonicalName", "").strip()
            if analyte is not None and a != analyte:
                continue
            loc = row.get("LocationID", "").strip()
            if loc in seen:
                continue
            if loc not in coords:
                qa.add(SEV_WARNING, "missing_coords",
                       f"{loc}: exceeds screening level but has no coordinates "
                       "in the coords CSV; excluded from plume boundary.",
                       location_id=loc)
                continue
            x, y = coords[loc]
            pts.append(ExceedancePoint(
                location_id=loc, x=x, y=y, analyte=a or None))
            seen.add(loc)
    return pts


# ---------------------------------------------------------------------------
# Hull computation
# ---------------------------------------------------------------------------

def compute_draft_plume_boundary(
    points: list[ExceedancePoint],
    *,
    hull_method: str = "convex",
    k_neighbors: int = 3,
    site_id: str = "",
    analyte: Optional[str] = None,
    qa: QACollector,
) -> Optional[DraftPlumeBoundaryResult]:
    """Compute a DRAFT plume extent polygon from exceedance points.

    Parameters
    ----------
    points : list[ExceedancePoint]
        Wells that exceed a screening level. Must have >= 3 members.
    hull_method : str
        "convex" (default) or "concave".
    k_neighbors : int
        Starting k for concave hull (ignored for convex). npg enforces k >= 3.
    site_id : str
        Stored on the result for provenance; does not affect computation.
    analyte : str | None
        Stored on the result for provenance; does not affect computation.
    qa : QACollector
        Receives at minimum one SEV_INFO noting DRAFT status.

    Returns
    -------
    DraftPlumeBoundaryResult with OPEN hull_vertices (first != last), or None
    if fewer than 3 points were supplied.
    """
    if hull_method not in ("convex", "concave"):
        raise ValueError(
            f"hull_method must be 'convex' or 'concave', got {hull_method!r}")

    if len(points) < 3:
        qa.add(SEV_ERROR, "insufficient_exceedance_points",
               f"Only {len(points)} exceedance point(s) supplied "
               f"(minimum 3 required for a polygon). No boundary generated.",
               recommended_action="Add more exceedance points or lower the "
                                  "screening level threshold.",
               site_id=site_id)
        return None

    xy = np.array([[p.x, p.y] for p in points], dtype=float)

    if hull_method == "convex":
        hull_arr = convex_hull(xy)
    else:
        hull_arr = concave_hull(xy, k=k_neighbors)

    # Ensure open ring (convex_hull already strips closing duplicate;
    # concave_hull wrapper does the same — but be defensive).
    if len(hull_arr) > 1 and np.allclose(hull_arr[0], hull_arr[-1]):
        hull_arr = hull_arr[:-1]

    hull_vertices = hull_arr.tolist()

    qa.add(SEV_INFO, "draft_plume_boundary_generated",
           f"DRAFT plume boundary: {len(hull_vertices)}-vertex {hull_method} "
           f"hull from {len(points)} exceedance point(s). "
           f"ReviewStatus=DRAFT. {_DRAFT_WARNING}",
           site_id=site_id)

    return DraftPlumeBoundaryResult(
        site_id=site_id,
        analyte=analyte,
        hull_method=hull_method,
        k_neighbors=k_neighbors if hull_method == "concave" else None,
        n_exceedance_points=len(points),
        hull_vertices=hull_vertices,
        review_status="DRAFT",
        draft_warning=_DRAFT_WARNING,
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def result_to_geojson(result: DraftPlumeBoundaryResult) -> dict:
    """Serialize to a GeoJSON Feature (Polygon).

    The coordinate ring is CLOSED: last coordinate == first coordinate.
    Always includes review_status='DRAFT' and draft_warning in properties.
    Caller is responsible for json.dumps().
    """
    import datetime
    closed_ring = result.hull_vertices + [result.hull_vertices[0]]
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [closed_ring],
        },
        "properties": {
            "site_id": result.site_id,
            "analyte": result.analyte or "all_exceedances",
            "hull_method": result.hull_method,
            "k_neighbors": result.k_neighbors,
            "n_exceedance_points": result.n_exceedance_points,
            "review_status": "DRAFT",
            "draft_warning": result.draft_warning,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        },
    }


def result_to_wkt(result: DraftPlumeBoundaryResult) -> str:
    """Serialize to a WKT POLYGON string (ring is closed: first == last pair).

    The WKT string itself does NOT include the [DRAFT] warning prefix;
    the CLI is responsible for printing the prefix before echoing the WKT
    so that the WKT string remains valid geometry text.

    Example return value:
        POLYGON ((0.0 0.0, 1.0 0.0, 1.0 1.0, 0.0 1.0, 0.0 0.0))
    """
    verts = result.hull_vertices + [result.hull_vertices[0]]  # close ring
    coords_str = ", ".join(f"{xy[0]} {xy[1]}" for xy in verts)
    return f"POLYGON (({coords_str}))"


# ---------------------------------------------------------------------------
# arcpy GDB write seam — LOCAL only
# ---------------------------------------------------------------------------

def write_plume_draft_to_gdb(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    result: DraftPlumeBoundaryResult,
    boundary_fc: Optional[str] = None,
) -> bool:
    """Write the draft plume polygon to Env_PlumeBoundary_Draft (ArcGIS Pro).

    ReviewStatus='DRAFT' matches the convention in groundwater_contours.py.
    Requires arcpy. Wrapped by the CLI --gdb flag behind _guard().

    boundary_fc: optional site-boundary polygon feature class; when given,
    the hull is clipped to it (Geometry.intersect — ADR-0085 decision 5,
    doc-verified 2026-07-16) so the draft plume never extends past the site
    boundary. A boundary_fc that does not exist, or an empty intersection,
    writes nothing and returns False — a requested clip is never silently
    skipped.

    Returns True if the row was written, False if the target feature class
    does not exist (e.g. schema tooling hasn't been run against this GDB
    yet) — callers must not report success when this returns False.
    """
    import datetime
    from pathlib import Path as _P

    from autogis.runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()

    fc = str(_P(gdb_path) / "Env_PlumeBoundary_Draft")
    if not arcpy.Exists(fc):
        return False

    sr = arcpy.Describe(fc).spatialReference
    # Delete existing draft polygon for this site
    where = f"SiteID = '{site_id}'"
    if result.analyte:
        where += f" AND AnalyteFilter = '{result.analyte}'"
    with arcpy.da.UpdateCursor(fc, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()

    # Build closed ring polygon
    closed = result.hull_vertices + [result.hull_vertices[0]]
    ring = arcpy.Array([arcpy.Point(xy[0], xy[1]) for xy in closed])
    polygon = arcpy.Polygon(ring, sr)

    clip_note = ""
    if boundary_fc:
        if not arcpy.Exists(boundary_fc):
            return False  # requested clip must not be silently skipped
        site_poly = None
        with arcpy.da.SearchCursor(boundary_fc, ["SHAPE@"]) as cur:
            for (shape,) in cur:
                site_poly = shape if site_poly is None \
                    else site_poly.union(shape)
        if site_poly is not None:
            polygon = polygon.intersect(site_poly, 4)  # 4 = polygon output
            if polygon.area == 0:
                return False
            clip_note = " Clipped to site boundary."

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    note = (f"DRAFT boundary — {result.hull_method} hull, "
            f"{result.n_exceedance_points} exceedance point(s)."
            f"{clip_note} Auto-generated {stamp}; review required.")

    fields = ["SiteID", "AnalyteFilter", "HullMethod", "KNeighbors",
              "NExceedancePoints", "ReviewStatus", "Notes", "SHAPE@"]
    with arcpy.da.InsertCursor(fc, fields) as cur:
        cur.insertRow([
            site_id,
            result.analyte or "",
            result.hull_method,
            result.k_neighbors,
            result.n_exceedance_points,
            "DRAFT",
            note,
            polygon,
        ])
    return True
