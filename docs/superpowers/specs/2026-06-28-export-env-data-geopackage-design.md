# ExportEnvDataToGeoPackage Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ExportEnvDataToGeoPackage (Phase 3 / Tool 9.1)
**Priority:** MEDIUM — open format export for agencies and data sharing without ArcGIS Pro license

---

## Problem

Regulatory agencies and project reviewers without ArcGIS Pro licenses cannot
open GDB files. CSV exports lose spatial context (coordinates aren't joined to
results). The envmon toolset has no open-format export that bundles spatial
(well locations, survey points) and tabular (results, water levels) data in a
single file. GeoPackage (SQLite-based) is the OGC standard open format
supported by QGIS, Python (via sqlite3), and PostGIS.

---

## Approach

**Chosen:** sqlite3-based GeoPackage writer (arcpy-free). Reads well CSV
(with `LONGITUDE`, `LATITUDE` columns), result CSVs, and water level CSVs.
Writes a minimal GeoPackage:
- `gpkg_contents` metadata table
- `wells` table with geometry (WKB point from lat/lon)
- `analytical_results` table (all result columns, no geometry)
- `water_levels` table (optional)

Uses only stdlib `sqlite3` — no geopandas, no GDAL. WKB encoding for points
is 21 bytes and written manually (ISO WKB point format).

**Rejected: Shapefile output.** DBF column name truncation (10 chars) loses
field names. GeoPackage preserves full names and bundles multiple tables.

**Rejected: GeoJSON.** GeoJSON can't bundle tabular-only tables without embedding
in Feature properties, which inflates file size. GeoPackage is the right choice.

---

## Architecture

```
autogis/
  core/envmon/
    geopackage_exporter.py        ← NEW
  adapters/
    cli.py                        ← add export-geopackage command (headless)
tests/envmon/
  test_geopackage_exporter.py     ← NEW
```

---

## Public API (`geopackage_exporter.py`)

```python
@dataclass
class GeoPackageResult:
    gpkg_path: Path
    layers: list[str]
    well_count: int
    result_count: int
    qa: QACollector

def encode_wkb_point(lon: float, lat: float) -> bytes:
    """
    Encode a 2D point as ISO WKB (little-endian):
    byte order (1) + geometry type (1=point, 4 bytes) + x + y (8 bytes each)
    Total: 21 bytes
    """

def create_geopackage(
    gpkg_path: Path,
    *,
    srs_id: int = 4326,
    overwrite: bool = False,
) -> None:
    """Initialize minimal GeoPackage: gpkg_contents, gpkg_geometry_columns, gpkg_spatial_ref_sys."""

def write_wells_layer(
    conn,                         # sqlite3 connection
    well_rows: list[dict],
    *,
    lat_field: str = "Latitude",
    lon_field: str = "Longitude",
    id_field: str = "LocationID",
) -> int:
    """Create wells table with WKB geometry; return row count."""

def write_tabular_layer(
    conn,
    table_name: str,
    rows: list[dict],
) -> int:
    """Create a non-spatial table; return row count."""

def export_env_data_geopackage(
    well_rows: list[dict],
    result_rows: list[dict],
    gpkg_path: Path,
    *,
    water_level_rows: list[dict] | None = None,
    overwrite: bool = False,
    qa: QACollector | None = None,
) -> GeoPackageResult:
```

---

## CLI Command

```
autogis envmon export-geopackage \
  --wells <env_wells.csv> \
  --results <merged_results.csv> \
  [--water-levels <water_levels.csv>] \
  --out <site_data.gpkg> \
  [--overwrite] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_geopackage_exporter.py` — arcpy-free:

1. `encode_wkb_point(-118.4567, 34.1234)` returns 21-byte bytes object
2. `encode_wkb_point` round-trips: parse WKB back → matching floats
3. `create_geopackage` creates file with `gpkg_contents` table
4. `write_wells_layer` inserts rows; query returns correct count
5. `write_tabular_layer` creates non-spatial table with correct columns
6. `export_env_data_geopackage` produces `.gpkg` at out_path
7. Well with missing lat/lon → WARNING in QA, row skipped
8. `overwrite=False` on existing file → ERROR; `overwrite=True` → succeeds
