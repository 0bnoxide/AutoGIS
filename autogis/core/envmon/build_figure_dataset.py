"""Generate the four callout feature classes from current-event data.

Pipeline:
  wide rows (build_current_event)  ->  CalloutTable (callout_templates)
  ->  CalloutGeometry (callout_geometry)  ->  placement (callout_collision)
  ->  Env_CalloutBoxes / Env_CalloutGridLines / Env_CalloutLeaderLines /
      Env_CalloutCellAnchors

arcpy is imported lazily; `assemble_callouts` is pure and unit-testable.
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from ..common.logging import get_logger
from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from .callout_templates import build_callout_rows
from .callout_geometry import (
    build_callout_geometry, compute_box_size, leader_attachment,
    map_units_per_point, quadrant_offsets, QUADRANT_ORDER_DEFAULT,
)
from .callout_collision import (
    CalloutRequest, place_callouts, PM_AUTO_COLLISION_WARNING,
)
from .manage_callout_overrides import load_overrides as _load_overrides
from ..common import numpy_geom as _numpy_geom

LOG = get_logger(__name__)

# Cell style -> Env_CalloutCellAnchors boolean flags
_STYLE_FLAGS = {
    "TITLE": ("IsHeader",),
    "LABEL": ("IsHeader",),
    "GROUP_HEADER": ("IsGroupHeader",),
}
_COLOR_FLAGS = {
    "EXCEEDANCE": ("IsExceedance", "IsDetected"),
    "DETECTED": ("IsDetected",),
    "NONDETECT": ("IsNonDetect",),
    "NOT_SAMPLED": ("IsNotSampled",),
}


from ...runtime.sessions import arcpy_env as _arcpy


def _where_date(field: str, ymd: str) -> str:
    return (f"{field} >= date '{ymd} 00:00:00' "
            f"AND {field} <= date '{ymd} 23:59:59'")


def assemble_callouts(
    wide_rows: Sequence[dict],
    locations_xy: Dict[str, Tuple[float, float]],
    figure_spec,
    analyte_dictionary: Dict[str, dict],
    qa: QACollector,
    extent: Optional[Tuple[float, float, float, float]],
    map_units: str,
    overrides: Optional[Dict[str, dict]] = None,
    use_hull_collision: bool = False,
) -> List[dict]:
    """Pure assembly: returns callout dicts with table, geometry, placement.

    overrides[LOCATIONID upper] = {origin:(x,y)|None, locked:bool,
                                   preferred_quadrant:str|None}
    """
    spec = figure_spec
    tmpl = spec.get("callout_template", {}) or {}
    ref_scale = float(spec.get("reference_scale", 1200))
    font_pts = float(tmpl.get("base_font_points", 6))
    standoff_pts = float(tmpl.get("standoff_points", 18))
    buffer_pts = float(tmpl.get("point_buffer_points", 10))
    quadrant_order = tuple(tmpl.get("quadrant_order", QUADRANT_ORDER_DEFAULT))
    analytes = spec.analyte_list(analyte_dictionary)
    overrides = overrides or {}

    mupp = map_units_per_point(ref_scale, map_units)
    standoff = standoff_pts * mupp
    point_buffer = buffer_pts * mupp

    if use_hull_collision:
        import numpy as _np
    else:
        _np = None

    prepared: List[dict] = []
    requests: List[CalloutRequest] = []
    for w in wide_rows:
        loc = w["LocationID"]
        xy = locations_xy.get(str(loc).strip().upper())
        if xy is None:
            qa.add(SEV_ERROR, "callout_location_missing_point",
                   f"{loc}: no map point found; callout NOT generated.",
                   recommended_action="Add the well/boring point feature.",
                   location_id=str(loc))
            continue
        table = build_callout_rows(w, spec, analyte_dictionary, analytes)
        width, height, _, _ = compute_box_size(table, ref_scale, map_units,
                                               font_pts)
        if use_hull_collision:
            _corners = _np.array(
                [(0.0, 0.0), (0.0, height), (width, height), (width, 0.0)],
                dtype=float,
            )
            _hull = _numpy_geom.convex_hull(_corners)
            eff_w = float(_hull[:, 0].max() - _hull[:, 0].min())
            eff_h = float(_hull[:, 1].max() - _hull[:, 1].min())
        else:
            eff_w, eff_h = width, height
        depth = w.get("DepthIntervalText") or ""
        key = f"{loc}|{depth}|{spec.figure_spec_id}"
        ov = overrides.get(str(loc).strip().upper()) or {}
        origin = ov.get("origin")
        if origin is None and ov.get("preferred_quadrant"):
            # Unlocked quadrant preference: make it the first candidate by
            # converting it to an unlocked override origin.
            try:
                (_q, dx, dy), = [t for t in quadrant_offsets(
                    width, height, standoff, (ov["preferred_quadrant"],))]
                origin = (xy[0] + dx, xy[1] + dy)
            except ValueError:
                qa.add(SEV_WARNING, "bad_preferred_quadrant",
                       f"{loc}: unknown PreferredQuadrant "
                       f"{ov['preferred_quadrant']!r} ignored.",
                       location_id=str(loc))
        requests.append(CalloutRequest(
            callout_id=key, location_id=str(loc), source_point=xy,
            box_width=eff_w, box_height=eff_h,
            override_origin=tuple(origin) if origin else None,
            locked=bool(ov.get("locked")) and origin is not None,
        ))
        prepared.append({"key": key, "location_id": loc, "table": table,
                         "wide": w, "source": xy})

    placements = place_callouts(requests, extent, point_buffer, standoff,
                                quadrant_order=quadrant_order)
    by_key = {p.callout_id: p for p in placements}

    out: List[dict] = []
    for prep in prepared:
        p = by_key.get(prep["key"])
        if p is None:   # defensive; place_callouts never drops
            qa.add(SEV_ERROR, "callout_placement_failed",
                   f"{prep['location_id']}: placement engine returned no "
                   "result.", location_id=str(prep["location_id"]))
            continue
        geom = build_callout_geometry(prep["table"], ref_scale, map_units,
                                      font_pts, origin=p.origin)
        geom.leader = (prep["source"],
                       leader_attachment(geom.bounds(), prep["source"]))
        if p.placement_method == PM_AUTO_COLLISION_WARNING:
            qa.add(SEV_WARNING, "callout_collision",
                   f"{prep['location_id']}: all candidate positions collide "
                   f"(score {p.collision_score:.1f}; "
                   f"{', '.join(p.collided_with[:5])}). Best candidate used — "
                   "review and add a placement override.",
                   location_id=str(prep["location_id"]))
        out.append({"callout_key": prep["key"],
                    "location_id": prep["location_id"],
                    "table": prep["table"], "geometry": geom,
                    "placement": p, "wide": prep["wide"]})
    return out


# --------------------------------------------------------------------------
# arcpy persistence
# --------------------------------------------------------------------------

def read_location_points(gdb, fc_names: Sequence[str],
                         site_id: str) -> Dict[str, Tuple[float, float]]:
    arcpy = _arcpy()
    pts: Dict[str, Tuple[float, float]] = {}
    for fc in fc_names:
        path = str(gdb / fc)
        if not arcpy.Exists(path):
            continue
        with arcpy.da.SearchCursor(path, ["LocationID", "SHAPE@XY"],
                                   where_clause=f"SiteID = '{site_id}'") as cur:
            for loc, xy in cur:
                if loc and xy:
                    pts[str(loc).strip().upper()] = xy
    return pts



def _delete_existing(gdb, fc: str, where: str) -> int:
    arcpy = _arcpy()
    n = 0
    with arcpy.da.UpdateCursor(str(gdb / fc), ["OID@"],
                               where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
            n += 1
    return n


def generate_callout_features(
    gdb,
    site_id: str,
    figure_spec,
    wide_rows: Sequence[dict],
    analyte_dictionary: Dict[str, dict],
    qa: QACollector,
    event_date: str,
    map_type: str,
    extent: Optional[Tuple[float, float, float, float]] = None,
    replace_existing: bool = True,
    points_fcs: Sequence[str] = ("MonitoringWells", "SoilBorings"),
    map_units: str = "feet",
    batch_id: str = "",
    use_hull_collision: bool = False,
) -> int:
    """Write callouts to the four feature classes; returns callout count."""
    arcpy = _arcpy()
    spec = figure_spec
    spec_id = spec.figure_spec_id
    matrix = spec.get("matrix", "GW")
    try:
        ev_dt = _dt.datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        ev_dt = None
        qa.add(SEV_WARNING, "bad_event_date",
               f"Event date {event_date!r} is not YYYY-MM-DD; stored NULL.")

    locations = read_location_points(gdb, points_fcs, site_id)
    if not locations:
        qa.add(SEV_ERROR, "missing_required_map_layer",
               f"No location points for {site_id} in {tuple(points_fcs)}; "
               "callouts cannot be placed.",
               recommended_action="Populate MonitoringWells/SoilBorings.",
               site_id=site_id)
        return 0

    overrides = _load_overrides(gdb, site_id, spec_id)
    callouts = assemble_callouts(wide_rows, locations, spec,
                                 analyte_dictionary, qa, extent, map_units,
                                 overrides,
                                 use_hull_collision=use_hull_collision)

    where = (f"SiteID = '{site_id}' AND FigureSpecID = '{spec_id}' "
             f"AND MapType = '{map_type}'")
    if ev_dt is not None:
        where += " AND " + _where_date("EventDate", event_date)
    if replace_existing:
        for fc in ("Env_CalloutBoxes", "Env_CalloutGridLines",
                   "Env_CalloutLeaderLines", "Env_CalloutCellAnchors"):
            n = _delete_existing(gdb, fc, where)
            LOG.info("Removed %s stale rows from %s", n, fc)

    sr = None  # geometry inherits the FC's spatial reference on insert

    box_fields = ["SiteID", "EventDate", "MapType", "FigureSpecID",
                  "LocationID", "SampleID", "Matrix", "CalloutID",
                  "AnchorX", "AnchorY", "WidthMapUnits", "HeightMapUnits",
                  "PlacementMethod", "PlacementQuadrant", "CollisionScore",
                  "PlacementLocked", "CollisionStatus", "ImportBatchID",
                  "SHAPE@"]
    with arcpy.da.InsertCursor(str(gdb / "Env_CalloutBoxes"),
                               box_fields) as cur:
        for c in callouts:
            g = c["geometry"]; p = c["placement"]; w = c["wide"]
            ring = arcpy.Array([arcpy.Point(*pt) for pt in g.box_corners])
            status = ("COLLISION_WARNING"
                      if p.placement_method == PM_AUTO_COLLISION_WARNING
                      else "OK")
            cur.insertRow([
                site_id, ev_dt, map_type, spec_id, c["location_id"],
                w.get("SampleID"), matrix, c["callout_key"],
                g.origin[0], g.origin[1], g.width, g.height,
                p.placement_method, p.quadrant or "",
                p.collision_score,
                int(p.placement_method == "OVERRIDE_LOCKED"),
                status, batch_id, arcpy.Polygon(ring, sr),
            ])

    gl_fields = ["SiteID", "EventDate", "MapType", "FigureSpecID",
                 "LocationID", "CalloutID", "GridLineType", "RowNum",
                 "ColNum", "StyleClass", "SHAPE@"]
    with arcpy.da.InsertCursor(str(gdb / "Env_CalloutGridLines"),
                               gl_fields) as cur:
        for c in callouts:
            for gl in c["geometry"].gridlines:
                arr = arcpy.Array([arcpy.Point(*gl.start),
                                   arcpy.Point(*gl.end)])
                cur.insertRow([
                    site_id, ev_dt, map_type, spec_id, c["location_id"],
                    c["callout_key"], gl.line_type, gl.row_number,
                    gl.column_number, gl.line_type,
                    arcpy.Polyline(arr, sr),
                ])

    ld_fields = ["SiteID", "EventDate", "MapType", "FigureSpecID",
                 "LocationID", "SampleID", "CalloutID", "LeaderStyle",
                 "SourcePointX", "SourcePointY", "TargetPointX",
                 "TargetPointY", "SHAPE@"]
    with arcpy.da.InsertCursor(str(gdb / "Env_CalloutLeaderLines"),
                               ld_fields) as cur:
        for c in callouts:
            leader = c["geometry"].leader
            if leader is None:
                continue
            (sx, sy), (tx, ty) = leader
            arr = arcpy.Array([arcpy.Point(sx, sy), arcpy.Point(tx, ty)])
            cur.insertRow([site_id, ev_dt, map_type, spec_id,
                           c["location_id"], c["wide"].get("SampleID"),
                           c["callout_key"], "DEFAULT", sx, sy, tx, ty,
                           arcpy.Polyline(arr, sr)])

    an_fields = ["SiteID", "EventDate", "MapType", "FigureSpecID",
                 "LocationID", "SampleID", "Matrix", "CalloutID", "RowNum",
                 "ColNum", "TextValue", "TextStyleClass",
                 "DisplayColorClass", "IsHeader", "IsGroupHeader",
                 "IsAnalyteName", "IsResultValue", "IsExceedance",
                 "IsDetected", "IsNonDetect", "IsNotSampled",
                 "HorizontalAlignment", "FontSize", "SHAPE@XY"]
    with arcpy.da.InsertCursor(str(gdb / "Env_CalloutCellAnchors"),
                               an_fields) as cur:
        for c in callouts:
            for a in c["geometry"].cell_anchors:
                flags = {f: 0 for f in
                         ("IsHeader", "IsGroupHeader", "IsAnalyteName",
                          "IsResultValue", "IsExceedance", "IsDetected",
                          "IsNonDetect", "IsNotSampled")}
                for f in _STYLE_FLAGS.get(a.style_class, ()):
                    flags[f] = 1
                if a.style_class == "RESULT":
                    flags["IsResultValue"] = 1
                    for f in _COLOR_FLAGS.get(a.display_color_class, ()):
                        flags[f] = 1
                if a.style_class == "LABEL" and a.column_number == 1:
                    flags["IsAnalyteName"] = 1
                cur.insertRow([
                    site_id, ev_dt, map_type, spec_id, c["location_id"],
                    c["wide"].get("SampleID"), matrix, c["callout_key"],
                    a.row_number, a.column_number, a.cell_text[:128],
                    a.style_class, a.display_color_class,
                    flags["IsHeader"], flags["IsGroupHeader"],
                    flags["IsAnalyteName"], flags["IsResultValue"],
                    flags["IsExceedance"], flags["IsDetected"],
                    flags["IsNonDetect"], flags["IsNotSampled"],
                    a.h_align[:8], a.font_size_points, (a.x, a.y),
                ])

    qa.add(SEV_INFO, "callouts_generated",
           f"{len(callouts)} callouts generated for {site_id} / {spec_id} / "
           f"{event_date}.", site_id=site_id)
    return len(callouts)
