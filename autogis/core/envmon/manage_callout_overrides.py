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
