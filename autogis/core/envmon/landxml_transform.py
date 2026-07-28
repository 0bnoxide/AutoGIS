"""Projected-CRS and linear-unit transformation for LandXML TIN surfaces."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from autogis.core.common.landxml import (
    LandXMLSurface,
    METERS_PER_LANDXML_UNIT,
    linear_unit_scale,
    parse_epsg,
    parse_landxml_surface,
    write_landxml_surface,
)


@dataclass(frozen=True)
class LandXMLTransformResult:
    output_path: Path
    surface_name: str
    point_count: int
    face_count: int
    source_crs: str
    target_crs: str
    source_unit: str
    source_z_unit: str
    target_unit: str


def _source_metadata(path: Path) -> tuple[str | None, str | None, tuple[str, ...]]:
    root = ET.parse(path).getroot()
    coordinate_system = root.find(".//{*}CoordinateSystem")
    declared_crs = None
    if coordinate_system is not None:
        epsg = parse_epsg(coordinate_system.get("epsgCode"))
        if epsg is None:
            epsg = parse_epsg(coordinate_system.get("name"))
        if epsg is not None:
            declared_crs = f"EPSG:{epsg}"

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
    surface_names = tuple(
        surface.get("name", "")
        for surface in root.findall(".//{*}Surfaces/{*}Surface")
    )
    return declared_crs, declared_unit, surface_names


def _projected_crs(crs_text: str, linear_unit: str):
    try:
        from pyproj import CRS
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    epsg = parse_epsg(crs_text)
    if epsg is None:
        raise ValueError(
            f"CRS {crs_text!r} is not an EPSG code (e.g. EPSG:26913).")
    if linear_unit not in METERS_PER_LANDXML_UNIT:
        raise ValueError(
            f"Unsupported LandXML linear unit {linear_unit!r}; expected one "
            f"of {', '.join(METERS_PER_LANDXML_UNIT)}.")
    try:
        crs = CRS.from_epsg(epsg)
    except Exception as exc:
        raise ValueError(f"Unknown or invalid EPSG:{epsg}: {exc}") from None
    if not crs.is_projected:
        raise ValueError(
            f"EPSG:{epsg} must be a projected CRS; geographic degree "
            "coordinates cannot be written as LandXML feet/meters.")

    axis_factors = [axis.unit_conversion_factor for axis in crs.axis_info[:2]]
    if len(axis_factors) != 2 or not math.isclose(
            axis_factors[0], axis_factors[1], rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError(
            f"EPSG:{epsg} does not have two matching horizontal linear axes.")
    expected = METERS_PER_LANDXML_UNIT[linear_unit]
    if not math.isclose(
            axis_factors[0], expected, rel_tol=1e-9, abs_tol=1e-12):
        actual = next(
            (unit for unit, factor in METERS_PER_LANDXML_UNIT.items()
             if math.isclose(
                 axis_factors[0], factor, rel_tol=1e-9, abs_tol=1e-12)),
            None,
        )
        label = {
            "foot": "international foot",
            "USSurveyFoot": "US survey foot",
            "meter": "meter",
        }.get(actual)
        if label is None:
            label = (
                f"{crs.axis_info[0].unit_name or 'unknown units'} "
                f"({axis_factors[0]!r} metres per unit)"
            )
        raise ValueError(
            f"EPSG:{epsg} uses {label}, not requested LandXML unit "
            f"{linear_unit!r}. Select the CRS's real unit so coordinates "
            "and <Units> metadata cannot disagree.")
    return crs, epsg


def transform_landxml_surface(
        input_path: Path,
        output_path: Path,
        *,
        source_crs: str,
        target_crs: str,
        source_unit: str,
        target_unit: str,
        source_z_unit: str | None = None,
        surface_name: str = "",
        output_surface_name: str = "",
        override_source_metadata: bool = False,
        overwrite: bool = False,
) -> LandXMLTransformResult:
    """Transform one LandXML TIN surface while preserving its face topology."""
    source_path = Path(input_path)
    destination = Path(output_path)
    if source_path.resolve() == destination.resolve():
        raise ValueError("Input and output LandXML paths must be different.")
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"{destination} already exists; pass overwrite=True to replace it.")

    declared_crs, declared_unit, surface_names = _source_metadata(source_path)
    source_epsg = parse_epsg(source_crs)
    if (declared_crs and source_epsg != parse_epsg(declared_crs)
            and not override_source_metadata):
        raise ValueError(
            f"{source_path} declares {declared_crs}, not {source_crs}; "
            "set override_source_metadata=True only after verifying the "
            "source coordinates.")
    if (declared_unit and declared_unit != source_unit
            and not override_source_metadata):
        raise ValueError(
            f"{source_path} declares linear unit {declared_unit!r}, not "
            f"{source_unit!r}; set override_source_metadata=True only after "
            "verifying the source coordinates.")

    if surface_name:
        if surface_names.count(surface_name) != 1:
            available = ", ".join(repr(name) for name in surface_names) or "none"
            raise ValueError(
                f"Surface {surface_name!r} must match exactly once; "
                f"available surfaces: {available}.")
        selected_name = surface_name
    elif len(surface_names) == 1:
        selected_name = surface_names[0]
    elif len(surface_names) > 1:
        raise ValueError(
            "Input contains multiple surfaces; select one by name: "
            + ", ".join(repr(name) for name in surface_names))
    else:
        raise ValueError(f"No <Surface> found in {source_path}.")

    source, source_epsg = _projected_crs(source_crs, source_unit)
    target, target_epsg = _projected_crs(target_crs, target_unit)
    source_z_unit = source_z_unit or source_unit
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs(
            source, target, always_xy=True, allow_ballpark=False)
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    surface = parse_landxml_surface(source_path, surface_name=selected_name)
    z_scale = linear_unit_scale(source_z_unit, target_unit)
    points = {}
    for point_id, (northing, easting, elevation) in surface.points.items():
        target_easting, target_northing = transformer.transform(
            easting, northing, errcheck=True)
        transformed = (
            float(target_northing),
            float(target_easting),
            float(elevation) * z_scale,
        )
        if not all(math.isfinite(value) for value in transformed):
            raise ValueError(
                f"CRS transformation produced a non-finite coordinate for "
                f"LandXML point {point_id}.")
        points[point_id] = transformed

    transformed_surface = LandXMLSurface(
        name=output_surface_name.strip() or surface.name,
        points=points,
        faces=list(surface.faces),
    )
    written = write_landxml_surface(
        transformed_surface,
        destination,
        crs=f"EPSG:{target_epsg}",
        linear_unit=target_unit,
    )
    return LandXMLTransformResult(
        output_path=written,
        surface_name=transformed_surface.name,
        point_count=len(transformed_surface.points),
        face_count=len(transformed_surface.faces),
        source_crs=f"EPSG:{source_epsg}",
        target_crs=f"EPSG:{target_epsg}",
        source_unit=source_unit,
        source_z_unit=source_z_unit,
        target_unit=target_unit,
    )
