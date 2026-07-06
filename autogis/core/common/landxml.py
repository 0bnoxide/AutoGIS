"""landxml.py — read-only LandXML TIN surface parser (stdlib only).

Parses a ``<Surfaces><Surface><Definition>`` TIN block into points and
triangle faces, for rasterizing/diffing against a drone DEM
(:mod:`autogis.core.envmon.compare_drone_surfaces`). Write support (LandXML
export) is separate scope — see issues #164/#166.

LandXML point order is (northing, easting, elevation) per the LandXML 1.2
spec's default ``P`` element convention. Namespace-agnostic (``{*}tag``
wildcard) since LandXML files commonly declare a default namespace.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class LandXMLSurface:
    name: str
    points: dict          # point id -> (northing, easting, elevation)
    faces: list            # triples of point ids


def parse_landxml_surface(path: Path, *, surface_name: str = "") -> LandXMLSurface:
    """Parse a ``Surface`` from a LandXML file's TIN ``Definition`` block.

    Parses the first ``Surface`` unless *surface_name* selects one by its
    ``name`` attribute.
    """
    root = ET.parse(str(path)).getroot()
    surfaces = root.findall(".//{*}Surface")
    if not surfaces:
        raise ValueError(f"No <Surface> found in {path}")
    surface = surfaces[0]
    if surface_name:
        matched = [s for s in surfaces if s.get("name") == surface_name]
        if not matched:
            raise ValueError(f"Surface {surface_name!r} not found in {path}")
        surface = matched[0]

    points: dict = {}
    for p in surface.findall(".//{*}Pnts/{*}P"):
        pid = int(p.get("id"))
        n, e, z = (float(v) for v in p.text.split())
        points[pid] = (n, e, z)

    faces: list = []
    for f in surface.findall(".//{*}Faces/{*}F"):
        ids = tuple(int(x) for x in f.text.split())
        if len(ids) == 3:
            faces.append(ids)

    return LandXMLSurface(name=surface.get("name", ""), points=points, faces=faces)


def _barycentric(px: float, py: float, a: tuple, b: tuple, c: tuple):
    ax, ay, _ = a
    bx, by, _ = b
    cx, cy, _ = c
    denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if denom == 0:
        return None
    u = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denom
    v = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denom
    w = 1 - u - v
    if u < 0 or v < 0 or w < 0:
        return None
    return u, v, w


def elevation_at(surface: LandXMLSurface, northing: float,
                 easting: float) -> Optional[float]:
    """Barycentric-interpolate the surface elevation at (northing, easting);
    None if the point falls outside every triangle."""
    for a, b, c in surface.faces:
        pa, pb, pc = surface.points[a], surface.points[b], surface.points[c]
        bary = _barycentric(northing, easting, pa, pb, pc)
        if bary is not None:
            u, v, w = bary
            return u * pa[2] + v * pb[2] + w * pc[2]
    return None
