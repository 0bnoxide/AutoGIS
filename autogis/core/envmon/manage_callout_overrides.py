"""Callout placement override CRUD for Env_CalloutPlacementOverrides.

arcpy is imported lazily (ADR-002).  All functions follow the same lazy
import pattern as build_figure_dataset.py.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from ...runtime.sessions import arcpy_env as _arcpy
from .survey_to_well_elevation import sql_quote as _q

_TABLE = "Env_CalloutPlacementOverrides"
_READ_FIELDS = [
    "LocationID", "AnchorX", "AnchorY", "OffsetX", "OffsetY",
    "PreferredQuadrant", "LockedPlacement",
]


@dataclass
class CalloutOverride:
    """One row from Env_CalloutPlacementOverrides."""
    site_id: str
    location_id: str
    figure_spec_id: str
    map_type: str = ""
    event_date: Optional[datetime.datetime] = None
    sample_id: str = ""
    anchor_x: Optional[float] = None
    anchor_y: Optional[float] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    preferred_quadrant: Optional[str] = None
    locked: bool = False
    notes: str = ""


def _scope_where(site_id: str, figure_spec_id: str, map_type: str) -> str:
    """SiteID/FigureSpecID/MapType scope shared by load_overrides + _key_where.

    A blank map_type matches both '' and NULL — file GDBs may store an empty
    text value either way. LocationID is NOT part of the scope; the logical
    row key is (SiteID, FigureSpecID, MapType, LocationID), so within one
    scope each LocationID is unique.
    """
    mt = (f"MapType = '{_q(map_type)}'" if map_type
          else "(MapType = '' OR MapType IS NULL)")
    return (f"SiteID = '{_q(site_id)}' "
            f"AND FigureSpecID = '{_q(figure_spec_id)}' "
            f"AND {mt}")


def load_overrides(
    gdb_path, site_id: str, figure_spec_id: str, map_type: str = ""
) -> Dict[str, dict]:
    """Return override dicts keyed by LocationID (upper-cased).

    Scoped to one map_type: overrides are stored per
    (SiteID, FigureSpecID, MapType, LocationID), and a figure render targets a
    single MapType. WITHOUT this scope, two rows for the same LocationID under
    different MapTypes collapse (last-read-wins) into this location-keyed dict.
    Callers that render/list per map_type must pass their map_type.

    Return shape matches what assemble_callouts expects for its ``overrides``
    parameter: each value has keys ``origin`` (tuple|None),
    ``preferred_quadrant`` (str|None), and ``locked`` (bool).
    """
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        return {}
    out: Dict[str, dict] = {}
    where = _scope_where(site_id, figure_spec_id, map_type)
    with arcpy.da.SearchCursor(table, _READ_FIELDS, where_clause=where) as cur:
        for loc, ax, ay, ox, oy, pq, locked in cur:
            origin = None
            if ax is not None and ay is not None:
                origin = (float(ax) + float(ox or 0.0),
                          float(ay) + float(oy or 0.0))
            out[str(loc).strip().upper()] = {
                "origin": origin,
                "preferred_quadrant": (pq or "").strip() or None,
                "locked": bool(locked),
            }
    return out


_WRITE_FIELDS = [
    "SiteID", "EventDate", "MapType", "FigureSpecID", "LocationID",
    "SampleID", "AnchorX", "AnchorY", "OffsetX", "OffsetY",
    "PreferredQuadrant", "LockedPlacement", "Notes",
]


def _key_where(site_id: str, figure_spec_id: str, location_id: str,
               map_type: str) -> str:
    """Where clause for the full (SiteID, FigureSpecID, MapType, LocationID)
    row key — the scope plus a LocationID equality."""
    return (_scope_where(site_id, figure_spec_id, map_type)
            + f" AND LocationID = '{_q(location_id)}'")


def get_override(
    gdb_path, site_id: str, figure_spec_id: str, location_id: str,
    map_type: str = "",
) -> Optional[CalloutOverride]:
    """Read one full override row by its logical key, or None.

    save_override rewrites the whole row, so any partial update (lock,
    unlock) must read every field first to round-trip without data loss.
    """
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        return None
    where = _key_where(site_id, figure_spec_id, location_id, map_type)
    with arcpy.da.SearchCursor(table, _WRITE_FIELDS, where_clause=where) as cur:
        for row in cur:
            d = dict(zip(_WRITE_FIELDS, row))
            return CalloutOverride(
                site_id=str(d["SiteID"]),
                location_id=str(d["LocationID"]),
                figure_spec_id=str(d["FigureSpecID"]),
                map_type=str(d["MapType"] or ""),
                event_date=d["EventDate"],
                sample_id=str(d["SampleID"] or ""),
                anchor_x=d["AnchorX"],
                anchor_y=d["AnchorY"],
                offset_x=float(d["OffsetX"] or 0.0),
                offset_y=float(d["OffsetY"] or 0.0),
                preferred_quadrant=(str(d["PreferredQuadrant"]).strip() or None
                                    if d["PreferredQuadrant"] else None),
                locked=bool(d["LockedPlacement"]),
                notes=str(d["Notes"] or ""),
            )
    return None


def save_override(gdb_path, override: CalloutOverride) -> None:
    """Upsert one row in Env_CalloutPlacementOverrides.

    Deletes any existing row with the same (SiteID, MapType, FigureSpecID,
    LocationID) logical key, then inserts the new row.
    """
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        raise RuntimeError(f"Table not found: {table}")
    where = _key_where(override.site_id, override.figure_spec_id,
                       override.location_id, override.map_type)
    with arcpy.da.UpdateCursor(table, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
    row = [
        override.site_id,
        override.event_date,
        override.map_type,
        override.figure_spec_id,
        override.location_id,
        override.sample_id,
        override.anchor_x,
        override.anchor_y,
        override.offset_x,
        override.offset_y,
        override.preferred_quadrant,
        int(override.locked),
        override.notes,
    ]
    with arcpy.da.InsertCursor(table, _WRITE_FIELDS) as cur:
        cur.insertRow(row)


def clear_unlocked_overrides(
    gdb_path, site_id: str, figure_spec_id: str, map_type: str = ""
) -> int:
    """Delete unlocked overrides for the given site/spec/map type; return count."""
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        return 0
    where = (_scope_where(site_id, figure_spec_id, map_type)
             + " AND (LockedPlacement = 0 OR LockedPlacement IS NULL)")
    n = 0
    with arcpy.da.UpdateCursor(table, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
            n += 1
    return n
