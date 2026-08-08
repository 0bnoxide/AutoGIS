"""Pure (arcpy-free) marshalling helpers for the .pyt GUI adapter.

The Esri ``.pyt`` toolbox imports ``arcpy`` at module top level, so the
param-marshalling + core-wiring logic lives here instead — importable and
unit-testable with neither ``arcgis`` nor ``arcpy`` present. Both the GUI
(`toolbox.pyt`) and the test suite go through this single seam.

Single validation source (MERGE_PLAN §2): construct AND validate the same
``HarvestConfig`` dataclass the CLI uses, including the url-XOR-item_id
invariant — enforced here at build time, not deferred to ``layer_ref()``.

Today this module covers only the harvester (``build_harvest_config`` /
``run_harvest``); the ten envmon ``.pyt`` tools still marshal parameters
inline in their own ``execute()`` bodies, which is fine while that logic
stays a thin pass-through to a core function. When an envmon tool's
``execute()`` grows beyond a pass-through (branching, multi-step
orchestration, error handling that isn't just "call core, print QA") --
e.g. ``FullPipeline``, ``toolbox.pyt`` -- move its marshalling into this
module per the harvester's pattern, so it becomes unit-testable outside
Pro instead of only discoverable by running the tool inside ArcGIS Pro.
See issue #108 / the fable-architecture-review finding M2.
"""
import json
import math
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path

from autogis.core.harvest.models import HarvestConfig, AttachmentResult


ELEVATION_CONVERSIONS = {
    "Meters to international feet": (1.0 / 0.3048, "m_to_intft"),
    "Meters to US survey feet": (3937.0 / 1200.0, "m_to_usft"),
    "International feet to meters": (0.3048, "intft_to_m"),
    "US survey feet to meters": (1200.0 / 3937.0, "usft_to_m"),
}


def elevation_conversion_spec(conversion: str) -> tuple[float, str]:
    """Return the exact cell-value multiplier and output-name suffix."""
    try:
        return ELEVATION_CONVERSIONS[conversion]
    except KeyError:
        raise ValueError(
            f"Unknown elevation conversion {conversion!r}; expected one of "
            f"{', '.join(ELEVATION_CONVERSIONS)}.") from None


def convert_raster_elevation_units(
        arcpy_module, input_path: Path, conversion: str) -> Path:
    """Multiply raster cells by an exact unit factor using ArcGIS Times."""
    factor, suffix = elevation_conversion_spec(conversion)
    source = Path(input_path)
    output = source.with_name(f"{source.stem}_{suffix}.tif")

    extension = next(
        (name for name in ("Spatial", "ImageAnalyst", "3D")
         if arcpy_module.CheckExtension(name) == "Available"), None)
    if extension is None:
        raise ValueError(
            "Raster elevation conversion license is unavailable; enable "
            "Spatial Analyst, Image Analyst, or 3D Analyst, or turn off "
            "elevation conversion.")

    acquired = False
    try:
        checkout_status = arcpy_module.CheckOutExtension(extension)
        if checkout_status != "CheckedOut":
            raise ValueError(
                f"{extension} license checkout failed ({checkout_status}); "
                "elevation conversion was not started.")
        acquired = True
        arcpy_module.sa.Times(str(source), factor).save(str(output))
        return output
    finally:
        if acquired:
            arcpy_module.CheckInExtension(extension)


@contextmanager
def staged_cad_layers(arcpy_module, layer_paths, mappings):
    """Yield scratch copies carrying mapped CAD layer properties.

    ``AddCADFields`` changes its input table. Copying selected features into
    ``scratchGDB`` first keeps the source GIS layers untouched while giving
    Export To CAD the reserved ``LyrName``/``LyrColor``/``LyrLnType`` values
    it consumes. ``AddCADFields(..., ADD_LAYER_PROPERTIES, ...)`` in ArcGIS
    Pro 3.6.1 names the layer field ``LyrName`` (verified live; there is no
    ``Layer`` field), so the update cursor must address ``LyrName`` — a
    cursor over ``Layer`` raises ``Cannot find field 'Layer'`` and aborts
    every export. Docs: doc.esri.com .../conversion/add-cad-fields.html;
    .../conversion/export-to-cad.html (reserved CAD fields).
    """
    if len(layer_paths) != len(mappings):
        raise ValueError("CAD layer paths and mappings must have the same length.")

    staged = []
    try:
        for index, (layer_path, mapping) in enumerate(zip(layer_paths, mappings)):
            temp_path = str(
                Path(arcpy_module.env.scratchGDB)
                / f"autogis_cad_{index}_{uuid.uuid4().hex[:8]}"
            )
            staged.append(temp_path)
            arcpy_module.management.CopyFeatures(layer_path, temp_path)
            arcpy_module.conversion.AddCADFields(
                temp_path,
                "NO_ENTITY_PROPERTIES",
                "ADD_LAYER_PROPERTIES",
                "NO_TEXT_PROPERTIES",
                "NO_DOCUMENT_PROPERTIES",
                "NO_XDATA_PROPERTIES",
            )
            with arcpy_module.da.UpdateCursor(
                    temp_path, ["LyrName", "LyrColor", "LyrLnType"]) as cursor:
                for row in cursor:
                    row[0] = mapping.cad_layer
                    row[1] = mapping.color
                    row[2] = mapping.linetype
                    cursor.updateRow(row)
        yield staged
    finally:
        for temp_path in staged:
            try:
                arcpy_module.management.Delete(temp_path)
            except Exception:
                pass  # scratch cleanup must not hide the export result/error


def surface_from_triangle_json(geometry_rows, surface_name: str,
                               z_scale: float = 1.0):
    """Build a LandXML TIN from Esri JSON triangle polygons.

    Esri JSON vertices are ``x, y, z`` (easting, northing, elevation); the
    shared LandXML model stores ``northing, easting, elevation``. Shared TIN
    vertices are deduplicated so adjacent faces reference the same point id.
    ``z_scale`` multiplies each elevation by an exact unit factor (PR #257's
    elevation-conversion pattern applied to TIN vertices; 1.0 = no-op).
    """
    from autogis.core.common.landxml import LandXMLSurface

    points = {}
    point_ids = {}
    faces = []
    for raw_geometry in geometry_rows:
        geometry = (json.loads(raw_geometry)
                    if isinstance(raw_geometry, str) else raw_geometry)
        rings = geometry.get("rings") or []
        if len(rings) != 1:
            raise ValueError("Each TIN triangle must contain exactly one polygon ring.")
        vertices = []
        for coordinate in rings[0]:
            if len(coordinate) < 3 or coordinate[2] is None:
                raise ValueError("TIN triangle geometry is missing vertex elevations.")
            vertex = (
                float(coordinate[1]), float(coordinate[0]),
                float(coordinate[2]) * z_scale)
            if not all(math.isfinite(value) for value in vertex):
                raise ValueError("TIN triangle geometry contains a non-finite coordinate.")
            vertices.append(vertex)
        if len(vertices) > 1 and vertices[0] == vertices[-1]:
            vertices.pop()
        if len(vertices) != 3 or len(set(vertices)) != 3:
            raise ValueError(
                f"TIN triangle must have exactly 3 distinct vertices; got {len(vertices)}.")

        face = []
        for vertex in vertices:
            point_id = point_ids.get(vertex)
            if point_id is None:
                point_id = len(point_ids) + 1
                point_ids[vertex] = point_id
                points[point_id] = vertex
            face.append(point_id)
        faces.append(tuple(face))

    if not faces:
        raise ValueError("Input TIN contains no triangle faces.")
    return LandXMLSurface(name=surface_name, points=points, faces=faces)


def export_tin_landxml(arcpy_module, input_tin: str, output_path: Path, *,
                       surface_name: str, crs: str, linear_unit: str,
                       z_unit: str | None = None) -> Path:
    """Extract an ArcGIS Pro TIN and write a Civil 3D-ready LandXML surface.

    ``z_unit`` declares the TIN's actual vertical unit when it differs from
    the horizontal/LandXML unit (default: same as ``linear_unit``, no
    conversion). Elevations are then multiplied by the exact unit ratio —
    PR #257's optional elevation-conversion pattern, applied to extracted
    TIN vertices in pure Python (no raster tool or extra license needed).
    When the TIN defines a VCS, the declaration is validated against it;
    with an undefined VCS the declaration is trusted (the caller must know
    the data, e.g. a meters-elevation TIN on a State Plane feet CRS).
    """
    from autogis.core.common.landxml import (
        METERS_PER_LANDXML_UNIT, parse_epsg, write_landxml_surface)

    if not surface_name or not surface_name.strip():
        raise ValueError("Civil 3D surface name must not be blank.")
    expected_epsg = parse_epsg(crs)
    if expected_epsg is None:
        raise ValueError(f"CRS {crs!r} is not an EPSG code (e.g. EPSG:2256).")
    expected_units = METERS_PER_LANDXML_UNIT
    if linear_unit not in expected_units:
        raise ValueError(
            f"Unsupported LandXML linear unit {linear_unit!r}; expected one "
            f"of {', '.join(expected_units)}.")
    z_unit = z_unit or linear_unit
    if z_unit not in expected_units:
        raise ValueError(
            f"Unsupported TIN vertical unit {z_unit!r}; expected one "
            f"of {', '.join(expected_units)}.")

    spatial_reference = arcpy_module.Describe(input_tin).spatialReference
    actual_epsg = getattr(spatial_reference, "factoryCode", 0) or 0
    if actual_epsg != expected_epsg:
        raise ValueError(
            f"Input TIN is EPSG:{actual_epsg or 'unknown'}, not EPSG:{expected_epsg}.")
    if getattr(spatial_reference, "type", "") != "Projected":
        raise ValueError(
            "Input TIN must use a projected coordinate system with linear "
            "units; geographic degree coordinates cannot be labeled as LandXML feet/meters.")

    expected_meters_per_unit = expected_units[linear_unit]
    actual_meters_per_unit = float(spatial_reference.metersPerUnit)
    if not math.isclose(actual_meters_per_unit, expected_meters_per_unit,
                        rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(
            f"Input TIN uses {actual_meters_per_unit:g} meters per unit, "
            f"which does not match LandXML unit {linear_unit!r}.")

    vertical_reference = getattr(spatial_reference, "VCS", None)
    if vertical_reference is not None:
        vertical_meters_per_unit = float(vertical_reference.metersPerUnit)
        if not math.isclose(vertical_meters_per_unit, expected_units[z_unit],
                            rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"Input TIN vertical coordinates use {vertical_meters_per_unit:g} "
                f"meters per unit, which does not match the TIN vertical unit "
                f"{z_unit!r}; declare the TIN's actual vertical unit to "
                f"convert elevations.")
        if getattr(vertical_reference, "direction", 1) != 1:
            raise ValueError(
                "Input TIN vertical coordinate system is positive downward; "
                "LandXML surface elevations must be positive upward.")

    license_status = arcpy_module.CheckExtension("3D")
    if license_status != "Available":
        raise ValueError(
            f"3D Analyst license is unavailable ({license_status}); "
            "TIN LandXML export was not started.")

    triangles = str(
        Path(arcpy_module.env.scratchGDB)
        / f"autogis_tin_triangles_{uuid.uuid4().hex[:8]}"
    )
    acquired_3d = False
    try:
        checkout_status = arcpy_module.CheckOutExtension("3D")
        if checkout_status != "CheckedOut":
            raise ValueError(
                f"3D Analyst license checkout failed ({checkout_status}); "
                "TIN LandXML export was not started.")
        acquired_3d = True
        # Let TinTriangle use its documented z-factor default. Passing an
        # explicit z-factor is unavailable when the TIN defines a VCS.
        arcpy_module.ddd.TinTriangle(input_tin, triangles, "PERCENT")
        # Exact unit ratio (1.0 when z_unit == linear_unit): e.g. a
        # meters-elevation TIN exported as feet scales z by 1/0.3048.
        z_scale = expected_units[z_unit] / expected_units[linear_unit]
        with arcpy_module.da.SearchCursor(triangles, ["SHAPE@JSON"]) as cursor:
            surface = surface_from_triangle_json(
                (row[0] for row in cursor), surface_name, z_scale=z_scale)
        return write_landxml_surface(
            surface, output_path, crs=crs, linear_unit=linear_unit)
    finally:
        try:
            arcpy_module.management.Delete(triangles)
        except Exception:
            pass  # scratch cleanup must not hide the extraction result/error
        if acquired_3d:
            arcpy_module.CheckInExtension("3D")


def build_harvest_config(
    *,
    directory: str,
    group_template: str,
    filename_template: str,
    item_id: str | None = None,
    url: str | None = None,
    where: str = "1=1",
    incremental: bool = False,
    skip_existing: bool = True,
    retries: int = 3,
    backoff_seconds: float = 2,
) -> HarvestConfig:
    """Build + validate a HarvestConfig from marshalled GUI params.

    Enforces the (item_id XOR url) invariant up front (single validation
    source on the dataclass) rather than leaving it to ``layer_ref()``.
    """
    if bool(item_id) == bool(url):
        raise ValueError(
            "HarvestConfig requires exactly one of 'url' or 'item_id'.")
    config = HarvestConfig(
        directory=directory,
        group_template=group_template,
        filename_template=filename_template,
        item_id=item_id,
        url=url,
        where=where if where is not None else "1=1",
        incremental=incremental,
        skip_existing=skip_existing,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    # Trip the dataclass's own validation now so a bad config fails at build
    # time, in either adapter, before any session work.
    config.layer_ref()
    return config


def run_harvest(config: HarvestConfig, session, qa=None) -> list[AttachmentResult]:
    """Run the core harvester for ``config`` against an active GIS ``session``.

    Thin pass-through to ``core.harvest.harvest``; kept here so the .pyt's
    ``execute()`` stays pure marshalling. When ``qa`` is supplied, per-
    attachment failures are recorded on it — ``harvest()`` deliberately never
    kills a run over one bad attachment, so without this the .pyt reported
    "N attachment(s) processed" with no hint that some of them failed (#431).
    """
    from autogis.core.harvest.harvester import harvest

    summary = harvest(session, config)
    results = list(summary.results)
    if qa is not None:
        from autogis.core.common.qa import SEV_ERROR, SEV_INFO
        failed = [r for r in results if (r.disposition or r.status) == "failed"]
        for r in failed:
            qa.add(SEV_ERROR, "attachment_download_failed",
                   f"{r.original_name or '?'} "
                   f"(OBJECTID {r.objectid}, attachment {r.attachment_id}) "
                   f"was not downloaded: {r.error or 'unknown error'}",
                   recommended_action="Re-run; `skip_existing` keeps the "
                                      "attachments that did land.")
        qa.add(SEV_ERROR if failed else SEV_INFO, "harvest_summary",
               f"{summary.downloaded} downloaded, {summary.skipped} skipped, "
               f"{summary.failed} failed.")
    return results


def spec_contour_kwargs(figure_spec) -> dict:
    """Map a figure spec's ``contours:`` block to ``build_groundwater_contours``
    keyword arguments (#443).

    Only keys the spec actually supplies are returned, so the core function's
    own defaults stay the single source of truth. An unusable value is a
    ``ValueError`` rather than a silent fallback: the whole point of the block
    is that editing it changes the output.
    """
    from autogis.core.envmon.groundwater_contours import METHODS

    block = figure_spec.get("contours") or {}
    if not isinstance(block, dict):
        raise ValueError(
            f"figure spec 'contours' must be a mapping, got {type(block).__name__}")
    kwargs: dict = {}
    if (method := block.get("method")) is not None:
        if method not in METHODS:
            raise ValueError(
                f"figure spec contours.method {method!r} is not one of {METHODS}")
        kwargs["method"] = method
    for spec_key, arg, cast in (("interval_ft", "contour_interval", float),
                                ("min_valid_points", "min_valid_points", int)):
        if (value := block.get(spec_key)) is not None:
            try:
                kwargs[arg] = cast(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"figure spec contours.{spec_key} must be numeric, "
                    f"got {value!r}") from None
    return kwargs


def _pyt_run_history_path(dest_hint: Path | None) -> Path | None:
    """Resolve the Pro-safe run-history destination (ADR-0068)."""
    dest = os.environ.get("AUTOGIS_RUN_HISTORY", "")
    if dest.lower() == "off":
        return None
    if dest:
        return Path(dest)
    if dest_hint:
        return Path(dest_hint) / "run_history.csv"
    return Path.cwd() / "run_history.csv"


def _site_id_from_config(path: str | None) -> str:
    if not path:
        return ""
    try:
        from autogis.core.common.config import load_config
        return str(load_config(Path(path)).get("site_id") or "")
    except Exception:
        return ""


class _CountingMessages:
    """Forward Pro messages while retaining their severity for run history."""
    def __init__(self, messages):
        self._messages = messages
        self.counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}

    def addErrorMessage(self, *args, **kwargs):
        self.counts["ERROR"] += 1
        return self._messages.addErrorMessage(*args, **kwargs)

    def addWarningMessage(self, *args, **kwargs):
        self.counts["WARNING"] += 1
        return self._messages.addWarningMessage(*args, **kwargs)

    def addMessage(self, *args, **kwargs):
        self.counts["INFO"] += 1
        return self._messages.addMessage(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._messages, name)


@contextmanager
def recording_pyt_run(tool_name: str, *, inputs: dict, dest_hint: Path | None,
                      site_id: str = "", event_id: str | None = None,
                      qa_counts: dict | None = None):
    """Best-effort run-history recording around one `.pyt` execution."""
    started = datetime.now()
    exc = None
    try:
        yield
    except BaseException as err:
        exc = err
        raise
    finally:
        try:
            path = _pyt_run_history_path(dest_hint)
            if path is not None:
                from autogis.core.common.run_history import RunHistory, RunRecord
                counts = qa_counts or {}
                status = "cancelled" if isinstance(exc, KeyboardInterrupt) else (
                    "error" if exc is not None or counts.get("ERROR", 0)
                    else "success")
                message = ("" if exc is None
                           else f"{type(exc).__name__}: {exc}")
                if not message and counts.get("ERROR", 0):
                    message = f"{counts['ERROR']} error QA message(s)"
                RunHistory(path).write(RunRecord(
                    run_id=str(uuid.uuid4()), tool_name=tool_name, site_id=site_id,
                    event_id=event_id, started_at=started, finished_at=datetime.now(),
                    status=status, inputs=json.loads(json.dumps(inputs, default=str)),
                    outputs={}, qa_count_error=counts.get("ERROR", 0),
                    qa_count_warning=counts.get("WARNING", 0),
                    qa_count_info=counts.get("INFO", 0), message=message,
                ))
        except Exception:
            pass  # observability must not change a Pro tool's outcome


def record_pyt_run(tool_name: str, *, gdb_param: str = "gdb",
                   site_config_param: str | None = "site_config",
                   event_param: str = "event_date"):
    """Decorate a thin `.pyt` execute method with the shared recorder."""
    def decorator(execute):
        @wraps(execute)
        def wrapped(self, parameters, messages):
            inputs = {p.name: p.valueAsText for p in parameters}
            gdb = inputs.get(gdb_param)
            recording_messages = _CountingMessages(messages)
            with recording_pyt_run(
                tool_name, inputs=inputs,
                dest_hint=Path(gdb).parent if gdb else None,
                site_id=_site_id_from_config(inputs.get(site_config_param)),
                event_id=inputs.get(event_param) or None,
                qa_counts=recording_messages.counts,
            ):
                return execute(self, parameters, recording_messages)
        return wrapped
    return decorator
