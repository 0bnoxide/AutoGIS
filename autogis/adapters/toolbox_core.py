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

# MSL-specific native adapter. New calls verified against Pro >=3.5 docs;
# references and native acceptance results are recorded in docs/qa/msl-dem.md.
def _msl_project_geometry(arcpy_module, geometry, target):
    source=geometry.spatialReference
    if not source or source.name=='Unknown':
        raise ValueError('AOI has an unknown spatial reference')
    if source.factoryCode and source.factoryCode==target.factoryCode:
        return geometry,None
    transformations=arcpy_module.ListTransformations(source,target,geometry.extent,False,True)
    transformation=transformations[0] if transformations else None
    if not transformation and source.GCS.datumName!=target.GCS.datumName:
        raise ValueError(f'No available horizontal transformation from {source.name} to {target.name}')
    return (geometry.projectAs(target,transformation) if transformation else geometry.projectAs(target)),transformation


def _msl_esri_to_geojson(rings):
    from autogis.core.envmon.msl_lidar import _ring_area
    outers=[ring for ring in rings if _ring_area(ring)<0]
    holes=[ring for ring in rings if _ring_area(ring)>0]
    polygons=[[outer] for outer in outers]
    def inside(point,ring):
        x,y=point;result=False
        for (ax,ay),(bx,by) in zip(ring,ring[1:]):
            if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:result=not result
        return result
    for hole in holes:
        candidates=[p for p in polygons if inside(hole[0],p[0])]
        if not candidates:raise ValueError('AOI hole has no enclosing exterior ring')
        min(candidates,key=lambda p:abs(_ring_area(p[0]))).append(hole)
    if not polygons:raise ValueError('AOI contains no polygon exterior rings')
    return {'type':'MultiPolygon','coordinates':polygons}


def resolve_msl_arcpy_aoi(arcpy_module,source,*,layer=None,bbox=None):
    """Retain selected features, multipart geometry and holes through discovery."""
    from autogis.core.envmon.msl_lidar import resolve_msl_aoi
    if source=='Manual bbox':
        return resolve_msl_aoi(bbox=tuple(float(x) for x in str(bbox or '').split()))
    target=arcpy_module.SpatialReference(4326)
    if source.startswith('Feature layer'):
        if layer is None:raise ValueError('Choose an AOI polygon feature layer')
        polygons=[]
        with arcpy_module.da.SearchCursor(layer,['SHAPE@']) as cursor:
            for (shape,) in cursor:
                if shape is None:continue
                projected,_=_msl_project_geometry(arcpy_module,shape,target)
                geometry=json.loads(projected.JSON)
                if 'rings' not in geometry:raise ValueError('AOI must be polygon features with linear rings; densify true curves before downloading')
                polygons.extend(_msl_esri_to_geojson(geometry['rings'])['coordinates'])
        if not polygons:raise ValueError('AOI layer has no selected/visible features')
        return resolve_msl_aoi(geometry={'type':'MultiPolygon','coordinates':polygons})
    view=arcpy_module.mp.ArcGISProject('CURRENT').activeView
    if view is None or not hasattr(view,'getLayerExtent') or not hasattr(view,'camera'):
        raise ValueError('No active map view; open a map or choose another AOI source')
    extent=view.camera.getExtent()
    sr=extent.spatialReference
    if not sr or sr.name=='Unknown':raise ValueError('Active map extent has unknown spatial reference')
    shape=arcpy_module.AsShape({'rings':[[[extent.XMin,extent.YMin],[extent.XMin,extent.YMax],
        [extent.XMax,extent.YMax],[extent.XMax,extent.YMin],[extent.XMin,extent.YMin]]],
        'spatialReference':{'wkt':sr.exportToString()}},True)
    projected,_=_msl_project_geometry(arcpy_module,shape,target)
    return resolve_msl_aoi(geometry=_msl_esri_to_geojson(json.loads(projected.JSON)['rings']))


def msl_polygon_center_mask(rings,left,top,dx,dy,width,height):
    """Even-odd mask for linear Esri rings, including holes, bounded to a block."""
    import numpy as np
    xs=left+(np.arange(width)+.5)*dx
    ys=top-(np.arange(height)+.5)*dy
    x,y=np.meshgrid(xs,ys);mask=np.zeros((height,width),dtype=bool)
    for ring in rings:
        part=np.zeros_like(mask)
        for (ax,ay),(bx,by) in zip(ring,ring[1:]):
            if by==ay:continue
            part^=((ay>y)!=(by>y)) & (x<(bx-ax)*(y-ay)/(by-ay)+ax)
        mask^=part
    return mask


def _msl_horizontal_sr(arcpy_module,sr):
    if not sr or sr.name=='Unknown':raise ValueError('Raster has unknown horizontal CRS')
    if sr.factoryCode:
        return arcpy_module.SpatialReference(sr.factoryCode)
    if getattr(sr,'VCS',None):
        raise ValueError('Custom compound CRS requires a verified horizontal CRS before processing')
    return sr


def _msl_native_coverage(arcpy_module,path,geometries):
    import numpy as np
    raster=arcpy_module.Raster(str(path))
    dx,dy=raster.meanCellWidth,raster.meanCellHeight
    extent=raster.extent
    rings=[ring for geometry in geometries for ring in json.loads(geometry.JSON)['rings']]
    points=[point for ring in rings for point in ring]
    left=extent.XMin+math.floor((min(p[0] for p in points)-extent.XMin)/dx+1e-8)*dx
    bottom=extent.YMin+math.floor((min(p[1] for p in points)-extent.YMin)/dy+1e-8)*dy
    right=extent.XMin+math.ceil((max(p[0] for p in points)-extent.XMin)/dx-1e-8)*dx
    top=extent.YMin+math.ceil((max(p[1] for p in points)-extent.YMin)/dy-1e-8)*dy
    width=round((right-left)/dx);height=round((top-bottom)/dy)
    expected=valid=0
    for row in range(0,height,512):
        nrows=min(512,height-row)
        for col in range(0,width,512):
            ncols=min(512,width-col)
            blockleft=left+col*dx;blocktop=top-row*dy
            mask=msl_polygon_center_mask(rings,blockleft,blocktop,dx,dy,ncols,nrows)
            point=arcpy_module.Point(blockleft,blocktop-nrows*dy)
            a=arcpy_module.RasterToNumPyArray(raster,point,ncols,nrows,0)
            b=arcpy_module.RasterToNumPyArray(raster,point,ncols,nrows,1)
            expected+=int(mask.sum());valid+=int((mask & (a==b) & np.isfinite(a)).sum())
    del raster
    if not expected:raise ValueError('AOI contains no output pixel centers')
    if not valid:raise ValueError('No valid HFDEM cells cover AOI')
    return {'aoi_cells':expected,'valid_cells':valid,'fraction':valid/expected,'complete':valid==expected,
        'method':'output pixel centers inside true AOI polygon, including outside raster extent',
        'overlap_cells':None,'max_overlap_difference':None}


def _msl_validate_target_sr(sr):
    import re
    dimensions=re.findall(r'\bCS\s*\[[^,]+,\s*(\d+)\s*\]',sr.exportToString(),re.I)
    if (not sr or sr.name=='Unknown' or sr.type not in ('Projected','Geographic')
            or getattr(sr,'VCS',None) or any(int(n)!=2 for n in dimensions)):
        raise ValueError('Output CRS must be a two-dimensional horizontal geographic/projected CRS')
    return sr


def msl_arcpy_output_sr(arcpy_module,output_crs):
    text=str(output_crs)
    if text.upper().startswith('EPSG:') or text.isdigit():
        target=arcpy_module.SpatialReference(int(text.split(':')[-1]))
    else:
        target=arcpy_module.SpatialReference()
        target.loadFromString(text)
    return _msl_validate_target_sr(target)


def process_msl_dem_arcpy(arcpy_module,sources,aoi,out_path,*,output_crs=None,resolution=None,z_units='native'):
    """Native Pro raster backend; no imports of rasterio, pyproj or arcpy itself."""
    from dataclasses import asdict
    from autogis.core.envmon.msl_lidar import _polygons
    from autogis.core.envmon.msl_raster import inspect_vertical_metadata,validate_raster_compatibility
    out=Path(out_path)
    if out.exists():raise FileExistsError(f'Output exists: {out}')
    metadata=[];references=[]
    dtypes={'F32':'float32','F64':'float64','S16':'int16','S32':'int32','U16':'uint16','U32':'uint32'}
    for source in sources:
        desc=arcpy_module.Describe(str(source.path))
        sr=_msl_horizontal_sr(arcpy_module,desc.spatialReference);references.append(sr)
        nodata=getattr(desc,'noDataValue',None)
        try:nodata=float(nodata) if nodata not in (None,'') else None
        except (ValueError,TypeError):raise ValueError(f'Unrecognized source NoData metadata: {nodata}')
        metadata.append({**asdict(source),'path':str(source.path),'horizontal_crs':sr.exportToString(),
            'resolution':[desc.meanCellWidth,desc.meanCellHeight],'resolution_units':sr.linearUnitName if sr.type=='Projected' else sr.angularUnitName,
            'origin':[desc.extent.XMin,desc.extent.YMax],'dtype':dtypes.get(desc.pixelType,desc.pixelType),
            'bands':desc.bandCount,'nodata':nodata if nodata is None or math.isfinite(nodata) else 'NaN',
            **inspect_vertical_metadata(source.path,desc.spatialReference.exportToString())})
    compatibility=validate_raster_compatibility(metadata,output_crs=output_crs,resolution=resolution,z_units=z_units)
    target=msl_arcpy_output_sr(arcpy_module,output_crs) if output_crs else _msl_validate_target_sr(references[0])
    shapes=[];transformations=[]
    for polygon in _polygons(aoi):
        shape=arcpy_module.AsShape({'type':'Polygon','coordinates':polygon},False)
        shape,transform=_msl_project_geometry(arcpy_module,shape,target)
        shapes.append(shape)
        if transform:transformations.append({'purpose':'AOI','name':transform})
    # Union preserves holes but avoids XOR cancellation when selected features overlap.
    union=shapes[0]
    for shape in shapes[1:]:union=union.union(shape)
    shapes=[union]
    work=out.parent/'native-processing';work.mkdir()
    polygon_fc=str(work/'aoi.shp')
    arcpy_module.management.CopyFeatures(shapes,polygon_fc)
    inputs=[]
    dx=resolution or metadata[0]['resolution'][0]
    if resolution is None and not math.isclose(metadata[0]['resolution'][0],metadata[0]['resolution'][1],rel_tol=1e-8):
        raise ValueError('Native ArcPy mosaic requires square cells; select an explicit resolution')
    for index,(source,sr) in enumerate(zip(sources,references)):
        path=source.path
        if output_crs is not None or resolution is not None:
            options=arcpy_module.ListTransformations(sr,target,arcpy_module.Describe(str(path)).extent,False,True)
            transformation=options[0] if options else None
            if not transformation and sr.GCS.datumName!=target.GCS.datumName:
                raise ValueError('No available horizontal raster transformation for requested CRS')
            projected=work/f'projected-{index}.tif'
            arcpy_module.management.ProjectRaster(str(path),str(projected),target,
                resampling_type='BILINEAR',cell_size=dx,geographic_transform=transformation or '',vertical='NO_VERTICAL')
            path=projected
            if transformation:transformations.append({'purpose':source.member,'name':transformation})
        inputs.append(str(path))
    mosaic=work/'mosaic.tif';clipped=work/'clipped.tif'
    pixel_type='64_BIT' if any(m['dtype'] in ('float64','int32','uint32') for m in metadata) else '32_BIT_FLOAT'
    with arcpy_module.EnvManager(snapRaster=inputs[0],outputCoordinateSystem=target,extent=union.extent,cellSize=dx):
        arcpy_module.management.MosaicToNewRaster(inputs,str(work),mosaic.name,
            coordinate_system_for_the_raster=target,pixel_type=pixel_type,cellsize=dx,
            number_of_bands=1,mosaic_method='FIRST',mosaic_colormap_mode='FIRST')
        arcpy_module.management.Clip(str(mosaic),'#',str(clipped),polygon_fc,
            clipping_geometry='ClippingGeometry',maintain_clipping_extent='NO_MAINTAIN_EXTENT')
        factor=compatibility['scale_factors'][0]
        if factor!=1:
            extension=next((x for x in ('Spatial','ImageAnalyst') if arcpy_module.CheckExtension(x)=='Available'),None)
            if extension is None:raise ValueError('Elevation conversion requires Spatial Analyst or Image Analyst; use native units or headless autogis[msl]')
            if arcpy_module.CheckOutExtension(extension)!='CheckedOut':raise ValueError('Elevation conversion license checkout failed')
            try:arcpy_module.sa.Times(str(clipped),float(factor)).save(str(out))
            finally:arcpy_module.CheckInExtension(extension)
        else:
            # CopyRaster is unnecessary: same-volume local file copy preserves pixels.
            import shutil
            shutil.copyfile(clipped,out)
    arcpy_module.management.DefineProjection(str(out),target)
    coverage=_msl_native_coverage(arcpy_module,out,shapes)
    desc=arcpy_module.Describe(str(out))
    warnings=['ArcPy overlap difference statistics are not measured; first explicit project/source wins overlaps']
    if not coverage['complete']:warnings.append(f"Incomplete raster coverage: {coverage['aoi_cells']-coverage['valid_cells']} AOI pixel centers are NoData")
    if compatibility['z_units'] is None or compatibility['vertical_datum'] is None:
        warnings.append('Artifact vertical datum or units unknown; unchanged native values retained')
    return {'sources':metadata,'output':{'horizontal_crs':target.exportToString(),
        'resolution':[desc.meanCellWidth,desc.meanCellHeight],**compatibility},'coverage':coverage,
        'operations':[{'operation':'mosaic','method':'FIRST','priority':[s.project+':'+s.member for s in sources]},
            {'operation':'clip','geometry':aoi,'maintain_clipping_extent':False},
            {'operation':'horizontal_transformations','selected_by':'Esri overlap/accuracy rank','transformations':transformations},
            {'operation':'unit_conversion','scale_factors':compatibility['scale_factors'],'vertical_transformation':False}],
        'warnings':warnings,'backend':'ArcPy'}
