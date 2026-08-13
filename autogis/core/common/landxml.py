"""landxml.py — LandXML TIN surface/CgPoints parsing and writing, stdlib only.

Parses a ``<Surfaces><Surface><Definition>`` TIN block into points and
triangle faces, for rasterizing/diffing against a drone DEM
(:mod:`autogis.core.envmon.compare_drone_surfaces`). Also writes point-only
``<CgPoints>`` LandXML (control/survey points, no surface or alignment data)
shared by ``export_survey_cad.py`` (RTK points, issue #164) and
``civil3d_points.py`` (PNEZD points and TIN surfaces, issue #166).

LandXML point order is (northing, easting, elevation) per the LandXML 1.2
spec's default ``P`` element convention. Namespace-agnostic (``{*}tag``
wildcard) since LandXML files commonly declare a default namespace.

Known limitation: point order is assumed, not read from the file's own
``<CgPoints>``/units declarations. An exporter emitting easting-first ``P``
values would silently swap the axes here — no validation catches it.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, NamedTuple, Optional


class CgPoint(NamedTuple):
    name: str
    northing: float
    easting: float
    elevation: float
    code: str = ""
    description: str = ""


_LANDXML_NS = "http://www.landxml.org/schema/LandXML-1.2"

_EPSG_RE = re.compile(r"^\s*(?:EPSG\s*:\s*)?(\d{4,6})\s*$", re.IGNORECASE)

# LandXML-1.2.xsd impLinear / metLinear enums (only the survey-relevant ones);
# the remaining required Units attributes are fixed to the conventional values
# for each system — point files carry no area/volume/temperature data.
_IMPERIAL_UNITS = {
    "areaUnit": "squareFoot", "volumeUnit": "cubicFeet",
    "temperatureUnit": "fahrenheit", "pressureUnit": "inHG",
    "elevationUnit": "feet",
}
_METRIC_UNITS = {
    "areaUnit": "squareMeter", "volumeUnit": "cubicMeter",
    "temperatureUnit": "celsius", "pressureUnit": "milliBars",
    "elevationUnit": "meter",
}
_IMPERIAL_LINEAR = ("foot", "USSurveyFoot")
_METRIC_LINEAR = ("meter",)
SUPPORTED_LINEAR_UNITS = _IMPERIAL_LINEAR + _METRIC_LINEAR
METERS_PER_LANDXML_UNIT = {
    "meter": 1.0,
    "foot": 0.3048,
    "USSurveyFoot": 1200.0 / 3937.0,
}


def parse_epsg(crs: Optional[str]) -> Optional[int]:
    """``"EPSG:2256"`` / ``"2256"`` -> 2256; anything else -> None."""
    m = _EPSG_RE.match(crs or "")
    return int(m.group(1)) if m else None


def linear_unit_scale(source_unit: str, target_unit: str) -> float:
    """Exact multiplier for any supported LandXML linear-unit pair."""
    try:
        source = METERS_PER_LANDXML_UNIT[source_unit]
        target = METERS_PER_LANDXML_UNIT[target_unit]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported LandXML linear unit {exc.args[0]!r}; expected one "
            f"of {', '.join(SUPPORTED_LINEAR_UNITS)}.") from None
    return source / target


_AUTHORITY_CRS_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(\d+)\s*$")


def authority_crs(value: Optional[str]) -> Optional[str]:
    """Return a normalized authority code, treating bare numbers as EPSG."""
    if parse_epsg(value) is not None:
        return f"EPSG:{parse_epsg(value)}"
    match = _AUTHORITY_CRS_RE.match(value or "")
    if match is None:
        return None
    return f"{match.group(1).upper()}:{match.group(2)}"


class SourceMetadata(NamedTuple):
    """Metadata a LandXML file explicitly declares (never inferred)."""
    crs: tuple            # authority codes in declaration order
    linear_unit: Optional[str]     # Units linearUnit attribute, verbatim
    elevation_unit: Optional[str]  # Units elevationUnit attribute, verbatim
    surface_names: tuple


def read_source_metadata(path: Path) -> SourceMetadata:
    """Read the CRS, units, and surface names a LandXML file declares.

    Promoted from landxml_transform._source_metadata (ADR-0128) so the
    transform and handoff-packaging paths share one extraction.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Malformed LandXML {path}: {exc}") from None
    coordinate_system = root.find(".//{*}CoordinateSystem")
    declared_crs = []
    if coordinate_system is not None:
        epsg = parse_epsg(coordinate_system.get("epsgCode"))
        if epsg is not None:
            declared_crs.append(f"EPSG:{epsg}")
        named = authority_crs(coordinate_system.get("name"))
        if named is not None and named not in declared_crs:
            declared_crs.append(named)

    unit_elements = [
        element for element in (
            root.find(".//{*}Units/{*}Metric"),
            root.find(".//{*}Units/{*}Imperial"),
        )
        if element is not None
    ]
    if len(unit_elements) > 1:
        raise ValueError(
            f"{path} declares both Metric and Imperial LandXML units.")
    declared_unit = (
        unit_elements[0].get("linearUnit") if unit_elements else None
    )
    elevation_unit = (
        unit_elements[0].get("elevationUnit") if unit_elements else None
    )
    surface_names = tuple(
        surface.get("name", "")
        for surface in root.findall(".//{*}Surfaces/{*}Surface")
    )
    return SourceMetadata(
        tuple(declared_crs), declared_unit, elevation_unit, surface_names)


def _landxml_root(*, crs: Optional[str], linear_unit: Optional[str]) -> ET.Element:
    """Build the shared, coordinate-aware LandXML 1.2 document root."""
    if crs and parse_epsg(crs) is None:
        raise ValueError(
            f"CRS {crs!r} carries no EPSG code (e.g. 'EPSG:2256'); a "
            "<CoordinateSystem> without epsgCode is not machine-readable "
            "on import.")
    now = datetime.now()
    root = ET.Element("LandXML", {
        "xmlns": _LANDXML_NS, "version": "1.2",
        # date/time are required LandXML root attributes (LandXML-1.2.xsd)
        "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"),
    })
    if linear_unit is not None:
        units = ET.SubElement(root, "Units")
        if linear_unit in _IMPERIAL_LINEAR:
            ET.SubElement(units, "Imperial",
                          {"linearUnit": linear_unit, **_IMPERIAL_UNITS})
        elif linear_unit in _METRIC_LINEAR:
            ET.SubElement(units, "Metric",
                          {"linearUnit": linear_unit, **_METRIC_UNITS})
        else:
            raise ValueError(
                f"Unsupported LandXML linear unit {linear_unit!r}; expected "
                f"one of {', '.join(SUPPORTED_LINEAR_UNITS)}.")
    if crs:
        ET.SubElement(root, "CoordinateSystem",
                      {"name": crs, "epsgCode": str(parse_epsg(crs))})
    return root


def _write_tree(root: ET.Element, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path


def write_cgpoints(points: Iterable[CgPoint], output_path: Path, *,
                   crs: Optional[str] = None,
                   linear_unit: Optional[str] = None) -> Path:
    """Write a LandXML 1.2 ``<CgPoints>`` file: point-only export (control/
    survey points), no surface or alignment data. Point text is "northing
    easting elevation", the LandXML default convention.

    *linear_unit* ("foot" / "USSurveyFoot" / "meter", per the LandXML-1.2
    ``impLinear``/``metLinear`` enums) emits a ``<Units>`` block; *crs*
    (e.g. ``"EPSG:2256"``) emits ``<CoordinateSystem>`` with ``epsgCode``.
    A *crs* that carries no EPSG number raises ValueError — a name-only
    ``<CoordinateSystem>`` is not machine-readable, so consumers would fall
    back to the drawing's CRS while the file *looks* georeferenced (issue
    #238). Civil 3D reads both blocks on import — without them it assumes
    the drawing's units and can shift/scale the points. Omitting both keeps
    the bare legacy output.
    """
    root = _landxml_root(crs=crs, linear_unit=linear_unit)
    cg_points = ET.SubElement(root, "CgPoints")
    for pt in points:
        attrs = {"name": pt.name}
        if pt.code:
            attrs["code"] = pt.code
        if pt.description:
            attrs["desc"] = pt.description
        el = ET.SubElement(cg_points, "CgPoint", attrs)
        el.text = f"{pt.northing} {pt.easting} {pt.elevation}"
    return _write_tree(root, output_path)


@dataclass
class LandXMLSurface:
    name: str
    points: dict          # point id -> (northing, easting, elevation)
    faces: list            # triples of point ids
    _grid: Optional[tuple] = field(default=None, init=False, repr=False,
                                   compare=False)


def write_landxml_surface(surface: LandXMLSurface, output_path: Path, *,
                          crs: str, linear_unit: str) -> Path:
    """Write one triangulated ``<Surface>`` with explicit units and CRS.

    ``surface.points`` values use this module's canonical
    ``(northing, easting, elevation)`` order and each face references three
    point ids. A named surface with at least one valid face is required so
    Civil 3D exposes it in the LandXML import dialog.
    """
    if not surface.name.strip():
        raise ValueError("LandXML surface name must not be blank.")
    if not surface.points:
        raise ValueError(f"LandXML surface {surface.name!r} has no points.")
    if not surface.faces:
        raise ValueError(f"LandXML surface {surface.name!r} has no faces.")
    for point_id, coordinates in surface.points.items():
        if len(coordinates) != 3 or not all(
                math.isfinite(float(value)) for value in coordinates):
            raise ValueError(
                f"LandXML point {point_id!r} must have 3 finite coordinates.")
    for face in surface.faces:
        if len(face) != 3:
            raise ValueError(f"LandXML TIN face must have 3 point ids: {face!r}.")
        if len(set(face)) != 3:
            raise ValueError(
                f"LandXML TIN face must reference 3 distinct points: {face!r}.")
        missing = [pid for pid in face if pid not in surface.points]
        if missing:
            raise ValueError(
                f"Face {face} references unknown point id(s) {missing} — "
                f"malformed LandXML surface {surface.name!r}.")

    root = _landxml_root(crs=crs, linear_unit=linear_unit)
    surfaces = ET.SubElement(root, "Surfaces")
    surface_el = ET.SubElement(surfaces, "Surface", {"name": surface.name})
    definition = ET.SubElement(surface_el, "Definition", {"surfType": "TIN"})
    points_el = ET.SubElement(definition, "Pnts")
    for point_id, (northing, easting, elevation) in sorted(surface.points.items()):
        point_el = ET.SubElement(points_el, "P", {"id": str(point_id)})
        point_el.text = f"{northing} {easting} {elevation}"
    faces_el = ET.SubElement(definition, "Faces")
    for face in surface.faces:
        ET.SubElement(faces_el, "F").text = " ".join(str(pid) for pid in face)
    return _write_tree(root, output_path)


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
        try:
            pid = int(p.get("id"))
        except (TypeError, ValueError):
            raise ValueError(
                f"LandXML surface {surface.get('name', '')!r} has a point "
                "without an integer id.") from None
        if pid in points:
            raise ValueError(
                f"LandXML surface {surface.get('name', '')!r} repeats point "
                f"id {pid}.")
        values = (p.text or "").split()
        if len(values) != 3:
            raise ValueError(
                f"LandXML point {pid} must have 3 coordinates, not "
                f"{len(values)}.")
        n, e, z = (float(v) for v in values)
        if not all(math.isfinite(value) for value in (n, e, z)):
            raise ValueError(
                f"LandXML point {pid} must have 3 finite coordinates.")
        points[pid] = (n, e, z)

    faces: list = []
    for f in surface.findall(".//{*}Faces/{*}F"):
        ids = tuple(int(x) for x in (f.text or "").split())
        if len(ids) != 3:
            raise ValueError(
                f"LandXML TIN face must have 3 point ids: {ids!r}.")
        if len(set(ids)) != 3:
            raise ValueError(
                f"LandXML TIN face must reference 3 distinct points: "
                f"{ids!r}.")
        missing = [pid for pid in ids if pid not in points]
        if missing:
            raise ValueError(
                f"Face {ids} references unknown point id(s) {missing} — "
                f"malformed LandXML surface {surface.get('name', '')!r}.")
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
