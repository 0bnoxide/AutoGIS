"""landxml.py — read-only LandXML TIN surface parser (stdlib only).

Parses a ``<Surfaces><Surface><Definition>`` TIN block into points and
triangle faces, for rasterizing/diffing against a drone DEM
(:mod:`autogis.core.envmon.compare_drone_surfaces`). Write support (LandXML
export) is separate scope — see issues #164/#166.

LandXML point order is (northing, easting, elevation) per the LandXML 1.2
spec's default ``P`` element convention. Namespace-agnostic (``{*}tag``
wildcard) since LandXML files commonly declare a default namespace.

Known limitation: point order is assumed, not read from the file's own
``<CgPoints>``/units declarations. An exporter emitting easting-first ``P``
values would silently swap the axes here — no validation catches it.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LandXMLSurface:
    name: str
    points: dict          # point id -> (northing, easting, elevation)
    faces: list            # triples of point ids
    _grid: Optional[tuple] = field(default=None, init=False, repr=False,
                                   compare=False)


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
    # ponytail: a point exactly on a shared edge can round to a tiny negative
    # barycentric coordinate in either adjacent face; a strict < 0 can drop it
    # from both. Tolerate float noise, not real exteriority.
    if u < -1e-9 or v < -1e-9 or w < -1e-9:
        return None
    return u, v, w


def _cell(x: float, y: float, min_x: float, min_y: float,
         size_x: float, size_y: float) -> tuple:
    return (int((x - min_x) / size_x), int((y - min_y) / size_y))


def _build_grid(surface: LandXMLSurface) -> tuple:
    """Bucket faces by bounding-box grid cell.

    A drone DEM has millions of cells; a brute-force per-pixel scan over
    every TIN face (O(rows * cols * faces)) is infeasible at that scale. A
    uniform grid sized for ~1 face per cell (on average, for a roughly
    evenly-triangulated surface) turns each lookup into a scan of the few
    faces whose bounding box overlaps the query point's cell — no missed
    hits, since a face is registered in every cell its bounding box spans,
    which always includes the cell of any point actually inside it.
    """
    if not surface.points:
        raise ValueError(f"LandXML surface {surface.name!r} has no points.")
    for face in surface.faces:
        missing = [pid for pid in face if pid not in surface.points]
        if missing:
            raise ValueError(
                f"Face {face} references unknown point id(s) {missing} — "
                f"malformed LandXML surface {surface.name!r}.")
    xs = [p[0] for p in surface.points.values()]
    ys = [p[1] for p in surface.points.values()]
    min_x, min_y = min(xs), min(ys)
    span_x, span_y = max(xs) - min_x, max(ys) - min_y
    n = max(1, round(len(surface.faces) ** 0.5))
    size_x, size_y = (span_x / n) or 1.0, (span_y / n) or 1.0

    grid: dict = {}
    for face in surface.faces:
        pts = [surface.points[pid] for pid in face]
        gx0, gy0 = _cell(min(p[0] for p in pts), min(p[1] for p in pts),
                         min_x, min_y, size_x, size_y)
        gx1, gy1 = _cell(max(p[0] for p in pts), max(p[1] for p in pts),
                         min_x, min_y, size_x, size_y)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid.setdefault((gx, gy), []).append(face)
    return grid, min_x, min_y, size_x, size_y


def elevation_at(surface: LandXMLSurface, northing: float,
                 easting: float) -> Optional[float]:
    """Barycentric-interpolate the surface elevation at (northing, easting);
    None if the point falls outside every triangle. The face grid is built
    once per surface (lazily, on first call) and cached on the instance —
    callers sample the same surface many times (once per DEM cell)."""
    if surface._grid is None:
        surface._grid = _build_grid(surface)
    grid, min_x, min_y, size_x, size_y = surface._grid
    key = _cell(northing, easting, min_x, min_y, size_x, size_y)
    for a, b, c in grid.get(key, ()):
        pa, pb, pc = surface.points[a], surface.points[b], surface.points[c]
        bary = _barycentric(northing, easting, pa, pb, pc)
        if bary is not None:
            u, v, w = bary
            return u * pa[2] + v * pb[2] + w * pc[2]
    return None
