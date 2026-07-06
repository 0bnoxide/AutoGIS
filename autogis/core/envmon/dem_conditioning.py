"""dem_conditioning.py — DEMConditioningPipeline (LOCAL, arcpy).

``DEMConditioningConfig``, ``build_config``, ``products_to_generate`` and
``validate_config`` are arcpy-free and fully unit-testable. ``condition_dem``
requires arcpy (ArcGIS Pro) and is marked ``# pragma: no cover`` — mirrors the
``load_flight_yaml``-is-not / ``write_drone_flight``-is-arcpy split in
``register_drone_flight.py``. Registers its outputs via
``import_drone_products.write_product_registry`` — no parallel GDB writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR

# ponytail: "gaussian" dropped -- arcpy.sa has no true Gaussian-blur stat
# (FocalStatistics only offers MEAN/MEDIAN/etc.), and hand-rolling one via
# NbrWeight requires an unverified kernel-file format with zero test
# coverage possible here. If a site needs it, the safe path is repeated
# NbrCircle+MEAN passes (2-3x converges toward Gaussian) using primitives
# already proven in this file -- not a blind new API call.
SMOOTH_METHODS: frozenset[str] = frozenset({"median"})


@dataclass
class DEMConditioningConfig:
    fill_voids: bool = False
    fill_voids_max_pixels: int = 9
    smooth: Optional[str] = None
    with_slope: bool = False
    with_contours: bool = False


def build_config(
    *,
    fill_voids: Optional[int] = None,
    smooth: Optional[str] = None,
    with_slope: bool = False,
    with_contours: bool = False,
) -> DEMConditioningConfig:
    """Build a config from raw CLI/.pyt param values.

    ``fill_voids`` is None when the flag is absent, an int otherwise (9 when
    the flag is bare, matching click's ``flag_value`` behavior).
    """
    return DEMConditioningConfig(
        fill_voids=fill_voids is not None,
        fill_voids_max_pixels=fill_voids if fill_voids is not None else 9,
        smooth=smooth,
        with_slope=with_slope,
        with_contours=with_contours,
    )


def validate_config(config: DEMConditioningConfig, qa: QACollector) -> None:
    """Validate a :class:`DEMConditioningConfig`, writing issues to *qa*."""
    if config.fill_voids_max_pixels <= 0:
        qa.add(SEV_ERROR, "invalid_fill_voids_max_pixels",
               f"--fill-voids max pixels must be positive, got "
               f"{config.fill_voids_max_pixels}.")
    if config.smooth is not None and config.smooth not in SMOOTH_METHODS:
        qa.add(SEV_ERROR, "invalid_smooth_method",
               f"--smooth must be one of {sorted(SMOOTH_METHODS)}, got "
               f"{config.smooth!r}.")


def products_to_generate(config: DEMConditioningConfig) -> list[str]:
    """Product types this run will generate, in output order. DEM + hillshade
    are always produced; slope/contours are opt-in."""
    products = ["conditioned_dem", "hillshade"]
    if config.with_slope:
        products.append("slope")
    if config.with_contours:
        products.append("contours")
    return products


# ---------------------------------------------------------------------------
# arcpy seam — requires ArcGIS Pro; # pragma: no cover
# ---------------------------------------------------------------------------

def condition_dem(  # pragma: no cover
    gdb_path: str,
    flight_id: str,
    out_dir: str,
    config: DEMConditioningConfig,
) -> list:
    """Void-fill/smooth the flight's DEM and derive the requested products.

    Reads ``DroneFlight.dem_path`` for *flight_id* from *gdb_path*, runs the
    requested Spatial Analyst operations, writes each output raster under
    *out_dir*, and registers every output as a ``DroneProductRecord`` (via
    ``import_drone_products.write_product_registry``). Returns the records
    written.
    """
    import uuid
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    from ..common.schema.drone import DroneProductRecord
    from .import_drone_products import write_product_registry

    _ax = _arcpy()
    flights_table = str(_P(gdb_path) / "DroneFlights")
    dem_path = None
    with _ax.da.SearchCursor(flights_table, ["FlightID", "DEMPath"]) as cur:
        for fid, path in cur:
            if fid == flight_id:
                dem_path = path
                break
    if not dem_path:
        raise ValueError(
            f"Flight {flight_id!r} not found in {gdb_path}'s DroneFlights table.")

    out = _P(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dem = _ax.Raster(dem_path)

    if config.fill_voids:
        fill_kernel = _ax.sa.NbrCircle(config.fill_voids_max_pixels, "CELL")
        dem = _ax.sa.Con(_ax.sa.IsNull(dem),
                         _ax.sa.FocalStatistics(dem, fill_kernel, "MEAN"), dem)
    if config.smooth:
        dem = _ax.sa.FocalStatistics(dem, _ax.sa.NbrCircle(3, "CELL"), "MEDIAN")

    conditioned_path = str(out / f"{flight_id}_conditioned_dem.tif")
    dem.save(conditioned_path)
    outputs = {"conditioned_dem": conditioned_path}

    hillshade_path = str(out / f"{flight_id}_hillshade.tif")
    _ax.sa.Hillshade(dem).save(hillshade_path)
    outputs["hillshade"] = hillshade_path

    if config.with_slope:
        slope_path = str(out / f"{flight_id}_slope.tif")
        _ax.sa.Slope(dem).save(slope_path)
        outputs["slope"] = slope_path

    if config.with_contours:
        contours_path = str(out / f"{flight_id}_contours.shp")
        # ponytail: contour interval fixed at 1 (vertical unit); not in the
        # approved design's CLI flags. Add a --contour-interval flag if a
        # site needs a different spacing.
        _ax.sa.Contour(dem, contours_path, 1)
        outputs["contours"] = contours_path

    records = [
        DroneProductRecord(product_id=str(uuid.uuid4()), flight_id=flight_id,
                            product_type=product_type, path=path,
                            qa_status="pending")
        for product_type, path in outputs.items()
    ]
    write_product_registry(gdb_path, records)
    return records
