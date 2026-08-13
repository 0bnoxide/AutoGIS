"""ArcGIS Project-style horizontal transformation for LandXML TIN surfaces."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from autogis.core.common.landxml import (
    LandXMLSurface,
    METERS_PER_LANDXML_UNIT,
    authority_crs,
    linear_unit_scale,
    parse_epsg,
    parse_landxml_surface,
    read_source_metadata,
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
    source_z_unit: str | None
    target_unit: str
    operation_name: str
    operation_authority: str | None
    operation_code: str | None
    operation_accuracy: float | None
    z_scale: float
    z_scale_mode: str


def _load_crs(crs_text: str, *, target: bool = False):
    try:
        from pyproj import CRS
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    authority_code = authority_crs(crs_text)
    if authority_code is None:
        raise ValueError(
            f"CRS {crs_text!r} must be an authority code such as EPSG:4326 "
            "or ESRI:102700.")
    if target and not authority_code.startswith("EPSG:"):
        raise ValueError(
            f"Target CRS {crs_text!r} must be an EPSG code so output "
            "LandXML metadata remains machine-readable.")
    try:
        crs = CRS.from_user_input(authority_code)
    except Exception as exc:
        raise ValueError(
            f"Unknown or invalid CRS {authority_code}: {exc}") from None
    if target and not crs.is_projected:
        raise ValueError(
            f"Target CRS {authority_code} must be projected; geographic "
            "degree coordinates cannot be written as LandXML feet/meters.")
    if not target and not (crs.is_projected or crs.is_geographic):
        raise ValueError(
            f"Source CRS {authority_code} must be geographic or projected.")
    return crs, authority_code


def _linear_unit(crs, crs_text: str) -> str:
    axis_factors = [axis.unit_conversion_factor for axis in crs.axis_info[:2]]
    if len(axis_factors) != 2 or not math.isclose(
            axis_factors[0], axis_factors[1],
            rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError(
            f"{crs_text} does not have two matching horizontal linear axes.")
    for unit, factor in METERS_PER_LANDXML_UNIT.items():
        if math.isclose(
                axis_factors[0], factor, rel_tol=1e-9, abs_tol=1e-12):
            return unit
    raise ValueError(
        f"{crs_text} uses unsupported horizontal unit "
        f"{crs.axis_info[0].unit_name or 'unknown'} "
        f"({axis_factors[0]!r} metres per unit); LandXML output supports "
        f"{', '.join(METERS_PER_LANDXML_UNIT)}.")


def _unit_label(unit: str) -> str:
    return {
        "foot": "international foot",
        "USSurveyFoot": "US survey foot",
        "meter": "meter",
    }[unit]


def _canonical_crs(crs, fallback: str) -> str:
    authority = crs.to_authority()
    return (
        f"{authority[0]}:{authority[1]}"
        if authority is not None else fallback
    )


def _area_of_interest(surface: LandXMLSurface, source_crs):
    try:
        from pyproj import CRS, Transformer
        from pyproj.aoi import AreaOfInterest
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    if source_crs.is_geographic:
        lon_lat = [
            (easting, northing)
            for northing, easting, _ in surface.points.values()
        ]
    else:
        try:
            to_wgs84 = Transformer.from_crs(
                source_crs, CRS.from_epsg(4326),
                always_xy=True, allow_ballpark=False)
            lon_lat = [
                to_wgs84.transform(easting, northing, errcheck=True)
                for northing, easting, _ in surface.points.values()
            ]
        except Exception as exc:
            raise ValueError(
                "LandXML surface extent could not be resolved to WGS84; "
                f"verify the source CRS: {exc}") from None

    if not lon_lat or not all(
            math.isfinite(value) for pair in lon_lat for value in pair):
        raise ValueError(
            "LandXML surface extent could not be resolved to finite "
            "longitude/latitude coordinates.")
    west = min(pair[0] for pair in lon_lat)
    east = max(pair[0] for pair in lon_lat)
    south = min(pair[1] for pair in lon_lat)
    north = max(pair[1] for pair in lon_lat)
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise ValueError(
            "LandXML surface extent is outside valid longitude/latitude "
            "bounds; verify the source CRS and LandXML coordinate order.")
    # PROJ accepts a point AOI poorly; a tiny envelope preserves ranking.
    if west == east:
        west, east = west - 1e-9, east + 1e-9
    if south == north:
        south, north = south - 1e-9, north + 1e-9
    return AreaOfInterest(west, south, east, north)


def _operation_parts(operation) -> tuple:
    parts = tuple(getattr(operation, "operations", ()) or ())
    return parts or (operation,)


def _operation_id(operation) -> tuple[str | None, str | None]:
    identifier = operation.to_json_dict().get("id") or {}
    authority = identifier.get("authority")
    code = identifier.get("code")
    return (
        str(authority) if authority is not None else None,
        str(code) if code is not None else None,
    )


def _matches_operation(operation, requested: str) -> bool:
    if operation.name == requested:
        return True
    authority, code = _operation_id(operation)
    return (
        authority is not None
        and f"{authority}:{code}".upper() == requested.upper()
    )


def _missing_grid_message(operations) -> str:
    grids = sorted({
        grid.short_name
        for operation in operations
        for part in _operation_parts(operation)
        for grid in getattr(part, "grids", ())
        if not grid.available
    })
    return (
        f" Missing required PROJ grid(s): {', '.join(grids)}."
        if grids else ""
    )


def _select_transformer(
        source_crs,
        target_crs,
        area_of_interest,
        requested: str | None,
):
    try:
        from pyproj.transformer import TransformerGroup
    except ImportError:
        raise RuntimeError(
            "LandXML CRS transformation needs pyproj; install it with "
            "`pip install autogis[landxml]`.") from None

    try:
        group = TransformerGroup(
            source_crs,
            target_crs,
            always_xy=True,
            area_of_interest=area_of_interest,
            authority="any",
            allow_ballpark=False,
        )
    except Exception as exc:
        raise ValueError(
            f"Could not resolve coordinate operations for the LandXML "
            f"extent: {exc}") from None
    if not group.best_available:
        raise ValueError(
            "The best coordinate operation for this LandXML extent is "
            "unavailable; grid downloads are disabled."
            + _missing_grid_message(group.unavailable_operations))
    if not group.transformers:
        raise ValueError(
            "No non-ballpark coordinate operation is available for the "
            "source CRS, target CRS, and LandXML extent.")

    transformer = group.transformers[0]
    matched_operation = None
    if requested:
        requested = requested.strip()
        for candidate in group.transformers:
            match = next(
                (part for part in _operation_parts(candidate)
                 if _matches_operation(part, requested)),
                None,
            )
            if match is not None:
                transformer = candidate
                matched_operation = match
                break
        if matched_operation is None:
            unavailable_match = next(
                (part
                 for operation in group.unavailable_operations
                 for part in _operation_parts(operation)
                 if _matches_operation(part, requested)),
                None,
            )
            if unavailable_match is not None:
                raise ValueError(
                    f"Geographic transformation {requested!r} is unavailable "
                    "for this LandXML extent; grid downloads are disabled."
                    + _missing_grid_message(group.unavailable_operations))
            raise ValueError(
                f"Geographic transformation {requested!r} is not available "
                "for this LandXML extent.")

    report_operation = matched_operation
    if report_operation is None:
        report_operation = next(
            (part for part in _operation_parts(transformer)
             if part.to_json_dict().get("type") == "Transformation"),
            None,
        )
    if report_operation is None:
        operation_name = transformer.description
        operation_authority = operation_code = None
    else:
        operation_name = report_operation.name
        operation_authority, operation_code = _operation_id(report_operation)
    accuracy = transformer.accuracy
    if accuracy is None or accuracy < 0:
        accuracy = None
    return (
        transformer,
        operation_name,
        operation_authority,
        operation_code,
        accuracy,
    )


def _select_surface(path: Path, surface_names: tuple[str, ...],
                    surface_name: str) -> LandXMLSurface:
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
        raise ValueError(f"No <Surface> found in {path}.")
    return parse_landxml_surface(path, surface_name=selected_name)


def transform_landxml_surface(
        input_path: Path,
        output_path: Path,
        *,
        source_crs: str,
        target_crs: str,
        source_unit: str | None = None,
        target_unit: str | None = None,
        source_z_unit: str | None = None,
        geographic_transformation: str | None = None,
        z_scale: float | None = None,
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
    if source_z_unit is not None and z_scale is not None:
        raise ValueError(
            "source_z_unit and z_scale are mutually exclusive; an explicit "
            "Z multiplier replaces automatic unit conversion.")
    if z_scale is not None:
        try:
            z_scale = float(z_scale)
        except (TypeError, ValueError):
            raise ValueError("z_scale must be a positive finite number.") from None
        if not math.isfinite(z_scale) or z_scale <= 0:
            raise ValueError("z_scale must be a positive finite number.")

    declared_crs, declared_unit, _, surface_names = read_source_metadata(
        source_path)
    surface = _select_surface(source_path, surface_names, surface_name)
    source, source_authority = _load_crs(source_crs)
    target, target_authority = _load_crs(target_crs, target=True)

    for declared in declared_crs:
        try:
            declared_object, _ = _load_crs(declared)
            matches = source.equals(
                declared_object, ignore_axis_order=True)
        except ValueError:
            matches = False
        if not matches and not override_source_metadata:
            raise ValueError(
                f"{source_path} declares {declared}, not {source_authority}; "
                "set override_source_metadata=True only after verifying the "
                "source coordinates.")

    inferred_source_unit = (
        _linear_unit(source, source_authority)
        if source.is_projected else "degree"
    )
    inferred_target_unit = _linear_unit(target, target_authority)
    if (
        source.is_projected
        and declared_unit
        and declared_unit != inferred_source_unit
        and not override_source_metadata
    ):
        raise ValueError(
            f"{source_path} declares linear unit {declared_unit!r}, but "
            f"{source_authority} uses {_unit_label(inferred_source_unit)}; "
            "set override_source_metadata=True only after verifying the "
            "source coordinates.")
    if source_unit:
        expected_source_unit = (
            inferred_source_unit if source.is_projected else declared_unit
        )
        if expected_source_unit and source_unit != expected_source_unit:
            raise ValueError(
                f"Deprecated source-unit assertion {source_unit!r} disagrees "
                f"with {_unit_label(expected_source_unit)}.")
    if target_unit and target_unit != inferred_target_unit:
        raise ValueError(
            f"Deprecated target-unit assertion {target_unit!r} disagrees "
            f"with {_unit_label(inferred_target_unit)} used by "
            f"{target_authority}.")

    if z_scale is not None:
        effective_source_z_unit = (
            inferred_source_unit
            if source.is_projected else declared_unit or source_unit
        )
        effective_z_scale = z_scale
        z_scale_mode = "explicit"
    else:
        effective_source_z_unit = source_z_unit
        if effective_source_z_unit is None:
            if source.is_geographic:
                effective_source_z_unit = declared_unit or source_unit
                if effective_source_z_unit is None:
                    raise ValueError(
                        "A geographic LandXML source needs declared <Units>, "
                        "source_z_unit, or the deprecated source_unit assertion "
                        "so elevations can be converted safely.")
            else:
                effective_source_z_unit = inferred_source_unit
        effective_z_scale = linear_unit_scale(
            effective_source_z_unit, inferred_target_unit)
        z_scale_mode = "automatic"

    from pyproj import network
    network_was_enabled = network.is_network_enabled()
    if network_was_enabled:
        network.set_network_enabled(False)
    try:
        area = _area_of_interest(surface, source)
        (
            transformer,
            operation_name,
            operation_authority,
            operation_code,
            operation_accuracy,
        ) = _select_transformer(
            source, target, area, geographic_transformation)

        points = {}
        for point_id, (northing, easting, elevation) in surface.points.items():
            try:
                target_easting, target_northing = transformer.transform(
                    easting, northing, errcheck=True)
            except Exception as exc:
                raise ValueError(
                    f"Coordinate operation failed for LandXML point "
                    f"{point_id}: {exc}") from None
            transformed = (
                float(target_northing),
                float(target_easting),
                float(elevation) * effective_z_scale,
            )
            if not all(math.isfinite(value) for value in transformed):
                raise ValueError(
                    f"CRS transformation produced a non-finite coordinate for "
                    f"LandXML point {point_id}.")
            points[point_id] = transformed
    finally:
        if network_was_enabled:
            network.set_network_enabled(True)

    transformed_surface = LandXMLSurface(
        name=output_surface_name.strip() or surface.name,
        points=points,
        faces=list(surface.faces),
    )
    target_epsg = parse_epsg(target_authority)
    written = write_landxml_surface(
        transformed_surface,
        destination,
        crs=f"EPSG:{target_epsg}",
        linear_unit=inferred_target_unit,
    )
    return LandXMLTransformResult(
        output_path=written,
        surface_name=transformed_surface.name,
        point_count=len(transformed_surface.points),
        face_count=len(transformed_surface.faces),
        source_crs=_canonical_crs(source, source_authority),
        target_crs=f"EPSG:{target_epsg}",
        source_unit=inferred_source_unit,
        source_z_unit=effective_source_z_unit,
        target_unit=inferred_target_unit,
        operation_name=operation_name,
        operation_authority=operation_authority,
        operation_code=operation_code,
        operation_accuracy=operation_accuracy,
        z_scale=effective_z_scale,
        z_scale_mode=z_scale_mode,
    )
