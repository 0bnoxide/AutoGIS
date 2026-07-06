"""compare_drone_surfaces.py — CompareDroneSurfaces (LOCAL, arcpy).

LOD-threshold diff classification is arcpy-free and fully unit-testable.
``compare_surfaces`` reads the drone rasters (or a raster + a LandXML design
surface) via arcpy and is marked ``# pragma: no cover`` — mirrors the
``register_drone_flight.py`` split. Baseline is loosely coupled to
``dem_conditioning``: any DroneProductRecord (raw or conditioned) works, no
dependency on that module's internals.
"""
from __future__ import annotations

from dataclasses import dataclass

CHANGE = "change"
NO_CHANGE = "no_change"


def validate_baseline_args(baseline_product_id, baseline_landxml) -> None:
    """Exactly one baseline mode: a second DroneProductRecord (by product ID)
    or a LandXML design-surface file."""
    if bool(baseline_product_id) == bool(baseline_landxml):
        raise ValueError(
            "Specify exactly one baseline: --baseline-product-id or "
            "--baseline-landxml.")


def classify_diff(diff_ft: float, lod_threshold_ft: float) -> str:
    """Classify one elevation diff against the limit of detection."""
    return CHANGE if abs(diff_ft) > lod_threshold_ft else NO_CHANGE


@dataclass
class DiffSummary:
    count: int
    change_count: int
    no_change_count: int
    max_diff_ft: float
    mean_diff_ft: float


def summarize_diffs(diffs_ft: list, lod_threshold_ft: float) -> DiffSummary:
    """Summarize per-cell elevation diffs against the LOD threshold."""
    if not diffs_ft:
        return DiffSummary(count=0, change_count=0, no_change_count=0,
                           max_diff_ft=0.0, mean_diff_ft=0.0)
    classes = [classify_diff(d, lod_threshold_ft) for d in diffs_ft]
    return DiffSummary(
        count=len(diffs_ft),
        change_count=classes.count(CHANGE),
        no_change_count=classes.count(NO_CHANGE),
        max_diff_ft=max(abs(d) for d in diffs_ft),
        mean_diff_ft=sum(diffs_ft) / len(diffs_ft),
    )


# ---------------------------------------------------------------------------
# arcpy seam — requires ArcGIS Pro; # pragma: no cover
# ---------------------------------------------------------------------------

def _product_path(gdb_path: str, product_id: str):  # pragma: no cover
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "DroneProductRegistry")
    with _ax.da.SearchCursor(table, ["ProductID", "ProductPath"]) as cur:
        for pid, path in cur:
            if pid == product_id:
                return path
    return None


def compare_surfaces(  # pragma: no cover
    gdb_path: str,
    primary_product_id: str,
    *,
    baseline_product_id: str = "",
    baseline_landxml_path: str = "",
    lod_threshold_ft: float = 0.2,
) -> DiffSummary:
    """Diff the *primary_product_id* DEM against a baseline: either a second
    DroneProductRecord (raw or conditioned DEM) or a LandXML design surface.

    Exactly one of *baseline_product_id* / *baseline_landxml_path* must be
    set (validated by the caller via :func:`validate_baseline_args`). Both
    product IDs are looked up in *gdb_path*'s ``DroneProductRegistry``.
    """
    import numpy as np

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()

    primary_path = _product_path(gdb_path, primary_product_id)
    if not primary_path:
        return summarize_diffs([], lod_threshold_ft)
    primary = _ax.Raster(primary_path)
    primary_arr = _ax.RasterToNumPyArray(primary, nodata_to_value=np.nan)

    if baseline_product_id:
        baseline_path = _product_path(gdb_path, baseline_product_id)
        if not baseline_path:
            return summarize_diffs([], lod_threshold_ft)
        baseline = _ax.Raster(baseline_path)
        # Two independently-read rasters need not share an origin, cell size,
        # or extent even when their row/col counts happen to match -- a raw
        # numpy subtraction of two separately-converted arrays would silently
        # diff geographically unrelated cells. Run the subtraction through
        # arcpy's own Spatial Analyst raster algebra instead, which resamples
        # *baseline* onto *primary*'s grid per the analysis environment, and
        # only convert the (already-aligned) result to numpy.
        with _ax.EnvManager(snapRaster=primary, extent="INTERSECTION",
                            cellSize=primary):
            diff_raster = _ax.sa.Minus(primary, baseline)
        diff_arr = _ax.RasterToNumPyArray(diff_raster, nodata_to_value=np.nan)
        diffs_ft = [float(d) for d in diff_arr.flatten() if not np.isnan(d)]
    else:
        from ..common.landxml import elevation_at, parse_landxml_surface
        surface = parse_landxml_surface(baseline_landxml_path)
        extent = primary.extent
        cell_e, cell_n = primary.meanCellWidth, primary.meanCellHeight
        rows, cols = primary_arr.shape
        diffs_ft = []
        for r in range(rows):
            for c in range(cols):
                value = primary_arr[r, c]
                if np.isnan(value):
                    continue
                easting = extent.XMin + (c + 0.5) * cell_e
                northing = extent.YMax - (r + 0.5) * cell_n
                design_z = elevation_at(surface, northing, easting)
                if design_z is not None:
                    diffs_ft.append(float(value) - design_z)

    return summarize_diffs(diffs_ft, lod_threshold_ft)
