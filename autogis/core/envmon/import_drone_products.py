"""import_drone_products.py — drone product manifest parsing and GDB import (8.8).

``parse_product_manifest``, ``validate_drone_products``, ``classify_records`` and
``parse_gcp_csv`` are arcpy-free and fully unit-testable.

``write_product_registry``, ``add_rasters_to_catalog`` and ``write_gcp_features``
require arcpy (ArcGIS Pro) and are marked ``# pragma: no cover``. GDB column
names follow ``gdb_schema.py`` TABLE_SCHEMAS (DroneProductRegistry.ProductPath;
DroneControlPoints is an attribute table — ResidualH_m/ResidualV_m, no geometry).
"""
from __future__ import annotations

import csv
import uuid
from pathlib import Path

from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from ..common.schema.drone import DroneProductRecord, DroneControlPoint

VALID_PRODUCT_TYPES: frozenset[str] = frozenset(
    {"orthomosaic", "DSM", "DEM", "point_cloud"}
)
RASTER_PRODUCT_TYPES: frozenset[str] = frozenset({"orthomosaic", "DSM", "DEM"})


def parse_product_manifest(path: Path, flight_id: str) -> list[DroneProductRecord]:
    """Parse a product manifest CSV into DroneProductRecord instances.

    Manifest CSV columns (header required):
        product_type, path, crs, vertical_datum, resolution_m

    ``flight_id`` is stamped onto every record from the caller argument — it is
    not read from the CSV. A unique product_id (UUID4) is generated per row.
    """
    out: list[DroneProductRecord] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            res_raw = row.get("resolution_m", "").strip()
            resolution = float(res_raw) if res_raw else None
            out.append(DroneProductRecord(
                product_id=str(uuid.uuid4()),
                flight_id=flight_id,
                product_type=row.get("product_type", "").strip(),
                path=row.get("path", "").strip(),
                crs=row.get("crs", "").strip(),
                vertical_datum=row.get("vertical_datum", "").strip(),
                resolution_m=resolution,
                qa_status="pending",
            ))
    return out


def validate_drone_products(
    records: list[DroneProductRecord],
    qa: QACollector,
    *,
    check_paths: bool = False,
) -> None:
    """Validate a list of DroneProductRecord, writing issues to *qa*.

    Rules: product_type in VALID_PRODUCT_TYPES (ERROR); duplicate product_type
    within the set (WARNING); non-empty path (ERROR); non-empty crs (WARNING);
    if check_paths, each non-empty path must exist (ERROR). An empty manifest
    yields an empty_manifest WARNING; otherwise a manifest_parsed INFO record.
    """
    if not records:
        qa.add(SEV_WARNING, "empty_manifest",
               "Manifest contains no product records.")
        return

    seen_types: set[str] = set()
    for rec in records:
        if not rec.product_type or rec.product_type not in VALID_PRODUCT_TYPES:
            qa.add(SEV_ERROR, "invalid_product_type",
                   f"Product {rec.product_id}: unknown type '{rec.product_type}'. "
                   f"Expected one of {sorted(VALID_PRODUCT_TYPES)}.")
        if rec.product_type in seen_types:
            qa.add(SEV_WARNING, "duplicate_product_type",
                   f"Duplicate product_type '{rec.product_type}' for flight "
                   f"'{rec.flight_id}'. Each flight should have at most one of "
                   f"each product type.")
        # Only track valid types for duplicate detection — an invalid type
        # already raised invalid_product_type and shouldn't also read as a dup.
        if rec.product_type in VALID_PRODUCT_TYPES:
            seen_types.add(rec.product_type)
        if not rec.path:
            qa.add(SEV_ERROR, "empty_path",
                   f"Product {rec.product_id} ({rec.product_type}): path is empty.")
        if not rec.crs:
            qa.add(SEV_WARNING, "empty_crs",
                   f"Product {rec.product_id} ({rec.product_type}): CRS is empty; "
                   f"spatial reference will not be set on the mosaic entry.")
        if check_paths and rec.path and not Path(rec.path).exists():
            qa.add(SEV_ERROR, "path_not_found",
                   f"Product {rec.product_id}: path does not exist on disk: "
                   f"'{rec.path}'")

    qa.add(SEV_INFO, "manifest_parsed",
           f"Parsed {len(records)} product record(s) for flight "
           f"'{records[0].flight_id}'.")


def classify_records(
    records: list[DroneProductRecord],
) -> tuple[list[DroneProductRecord], list[DroneProductRecord]]:
    """Split records into (raster_records, non_raster_records).

    Raster types (orthomosaic, DSM, DEM) are loaded to a mosaic dataset.
    Non-raster types (point_cloud) are path-registered only (v1). Pure/testable.
    """
    rasters = [r for r in records if r.product_type in RASTER_PRODUCT_TYPES]
    others = [r for r in records if r.product_type not in RASTER_PRODUCT_TYPES]
    return rasters, others


def parse_gcp_csv(path: Path, flight_id: str) -> list[DroneControlPoint]:
    """Parse a GCP CSV into DroneControlPoint instances.

    CSV columns (header required): point_id, northing, easting, elevation,
    point_type. Optional columns: residual_h, residual_v. ``flight_id`` is
    stamped from the caller argument.
    """
    def _opt_float(row: dict, key: str):
        v = row.get(key, "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None

    out: list[DroneControlPoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            n, e, z = (_opt_float(row, "northing"), _opt_float(row, "easting"),
                       _opt_float(row, "elevation"))
            if n is None or e is None or z is None:
                continue  # malformed control point (missing/non-numeric coord) — skip, don't crash
            out.append(DroneControlPoint(
                point_id=row.get("point_id", "").strip(),
                flight_id=flight_id,
                northing=n, easting=e, elevation=z,
                point_type=row.get("point_type", "GCP").strip() or "GCP",
                residual_h=_opt_float(row, "residual_h"),
                residual_v=_opt_float(row, "residual_v"),
            ))
    return out


# ---------------------------------------------------------------------------
# arcpy seam — requires ArcGIS Pro; # pragma: no cover
# ---------------------------------------------------------------------------

def write_product_registry(  # pragma: no cover
    gdb_path: str,
    records: list[DroneProductRecord],
) -> None:
    """Insert DroneProductRecord rows into DroneProductRegistry (ArcGIS Pro)."""
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "DroneProductRegistry")
    if not _ax.Exists(table):
        return
    fields = [
        "ProductID", "FlightID", "ProductType", "ProductPath",
        "CRS", "VerticalDatum", "Resolution_m", "QAStatus",
    ]
    with _ax.da.InsertCursor(table, fields) as cur:
        for r in records:
            cur.insertRow([
                r.product_id, r.flight_id, r.product_type, r.path,
                r.crs, r.vertical_datum, r.resolution_m, r.qa_status,
            ])


def add_rasters_to_catalog(  # pragma: no cover
    gdb_path: str,
    catalog_name: str,
    raster_records: list[DroneProductRecord],
) -> int:
    """Add raster deliverables to a mosaic dataset (ArcGIS Pro).

    Returns the number of rasters added; skips any whose path is absent on disk.
    """
    import arcpy
    from pathlib import Path as _P

    catalog_path = str(_P(gdb_path) / catalog_name)
    if not arcpy.Exists(catalog_path):
        return 0
    added = 0
    for r in raster_records:
        if _P(r.path).exists():
            arcpy.management.AddRastersToMosaicDataset(
                catalog_path, "Raster Dataset", r.path)
            added += 1
    return added


def write_gcp_features(  # pragma: no cover
    gdb_path: str,
    points: list[DroneControlPoint],
) -> None:
    """Insert DroneControlPoint rows into the DroneControlPoints table (ArcGIS Pro).

    DroneControlPoints is an attribute table (gdb_schema.py): coordinates are
    stored as Northing/Easting/Elevation_ft columns, residuals as
    ResidualH_m/ResidualV_m. No geometry column.
    """
    from pathlib import Path as _P

    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    table = str(_P(gdb_path) / "DroneControlPoints")
    if not _ax.Exists(table):
        return
    fields = [
        "PointID", "FlightID", "Northing", "Easting", "Elevation_ft",
        "PointType", "ResidualH_m", "ResidualV_m",
    ]
    with _ax.da.InsertCursor(table, fields) as cur:
        for pt in points:
            cur.insertRow([
                pt.point_id, pt.flight_id, pt.northing, pt.easting,
                pt.elevation, pt.point_type, pt.residual_h, pt.residual_v,
            ])
