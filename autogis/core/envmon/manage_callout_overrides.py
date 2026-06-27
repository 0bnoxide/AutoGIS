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


def load_overrides(
    gdb_path, site_id: str, figure_spec_id: str
) -> Dict[str, dict]:
    """Return override dicts keyed by LocationID (upper-cased).

    Return shape matches what assemble_callouts expects for its ``overrides``
    parameter: each value has keys ``origin`` (tuple|None),
    ``preferred_quadrant`` (str|None), and ``locked`` (bool).
    """
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        return {}
    out: Dict[str, dict] = {}
    where = f"SiteID = '{site_id}' AND FigureSpecID = '{figure_spec_id}'"
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


def save_override(gdb_path, override: CalloutOverride) -> None:
    """Upsert one row in Env_CalloutPlacementOverrides.

    Deletes any existing row with the same (SiteID, MapType, FigureSpecID,
    LocationID) logical key, then inserts the new row.
    """
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        raise RuntimeError(f"Table not found: {table}")
    where = (
        f"SiteID = '{override.site_id}' "
        f"AND FigureSpecID = '{override.figure_spec_id}' "
        f"AND MapType = '{override.map_type}' "
        f"AND LocationID = '{override.location_id}'"
    )
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
    gdb_path, site_id: str, figure_spec_id: str
) -> int:
    """Delete all unlocked overrides for the given site/spec; return count."""
    arcpy = _arcpy()
    table = str(Path(gdb_path) / _TABLE)
    if not arcpy.Exists(table):
        return 0
    where = (
        f"SiteID = '{site_id}' AND FigureSpecID = '{figure_spec_id}' "
        f"AND (LockedPlacement = 0 OR LockedPlacement IS NULL)"
    )
    n = 0
    with arcpy.da.UpdateCursor(table, ["OID@"], where_clause=where) as cur:
        for _ in cur:
            cur.deleteRow()
            n += 1
    return n
