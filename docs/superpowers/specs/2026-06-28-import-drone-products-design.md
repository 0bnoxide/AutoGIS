# ImportDroneProducts Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ImportDroneProducts (Phase 4 / Tool 8.8)
**Priority:** HIGH — completes the drone pipeline; prerequisite for raster use in figures

---

## Problem

After `RegisterDroneFlight` logs a flight and `DroneGCPCheckpointQA` validates
accuracy, the drone products (orthomosaic, DSM, DEM, point cloud) need to be
catalogued so map-production tools can locate them. Currently there is no
systematic inventory — file paths are tracked in comments or spreadsheets and
regularly break when files are moved.

---

## Approach

**Chosen:** File-inventory + metadata extraction into a flat CSV product catalog
(`Env_DroneProducts.csv`). For each product path, records: flight_id, product
type (orthomosaic/DSM/DEM/point_cloud/report), file path, file size, SHA-256
hash, coordinate system (read from `.prj` sidecar or GeoTIFF header via
`struct`/stdlib), resolution (from filename pattern or metadata file), and
import timestamp. No arcpy; raster metadata extracted from GeoTIFF headers
with stdlib `struct` (minimal IFD read for pixel size and CRS).

**Rejected: GDAL/rasterio.** Not a core dependency. For the metadata we need
(pixel size, EPSG code), a minimal GeoTIFF IFD reader is 30 lines of stdlib
code and avoids a heavy optional dependency.

**Rejected: Absorbing into `RegisterDroneFlight`.** Flight registration is
metadata about the flight event. Product import is about the output files —
different lifecycle, different schema table.

---

## Architecture

```
autogis/
  core/envmon/
    drone_product_importer.py   ← NEW
  adapters/
    cli.py                      ← add import-drone-products command (headless)
tests/envmon/
  test_drone_product_importer.py ← NEW
```

---

## Public API (`drone_product_importer.py`)

```python
PRODUCT_TYPES = {
    "orthomosaic": [".tif", ".tiff", ".jpg"],
    "dsm": [".tif", ".tiff"],
    "dem": [".tif", ".tiff"],
    "point_cloud": [".las", ".laz", ".ply"],
    "report": [".pdf"],
    "other": [],
}

@dataclass
class DroneProductRecord:
    table_name: ClassVar[str] = "Env_DroneProducts"
    product_id: str              # UUID
    flight_id: str               # links to RegisterDroneFlight record
    product_type: str            # orthomosaic | dsm | dem | point_cloud | report | other
    file_path: str               # absolute path at import time
    file_name: str
    file_size_bytes: int
    sha256: str
    pixel_size_m: float | None   # GeoTIFF only
    epsg_code: int | None        # GeoTIFF .prj sidecar or embedded CRS
    coordinate_system: str
    imported_at: str             # ISO datetime
    flight_date: str
    notes: str = ""

def infer_product_type(path: Path) -> str:
    """Infer product type from filename keywords and extension."""

def read_geotiff_metadata(path: Path) -> dict:
    """
    Read pixel size and CRS from GeoTIFF IFD (minimal stdlib struct reader).
    Returns {pixel_size_m, epsg_code, coordinate_system} or empty dict on failure.
    """

def import_drone_products(
    flight_id: str,
    product_paths: list[Path],
    flight_date: str,
    catalog_csv: Path,
    *,
    notes: str = "",
    allow_update: bool = False,
    qa: QACollector | None = None,
) -> list[DroneProductRecord]:
    """
    For each path: infer type, compute hash, extract GeoTIFF metadata,
    check catalog for duplicates (same SHA-256 = skip), write new records.
    """

def load_product_catalog(catalog_csv: Path) -> list[DroneProductRecord]:
    """Read existing catalog CSV. Returns [] if not found."""

def write_product_catalog(records: list[DroneProductRecord],
                          catalog_csv: Path) -> None:
    """Append new records to catalog CSV."""
```

---

## Product Type Inference

| Filename keyword | Type |
|---|---|
| `ortho`, `rgb`, `rgb_camera` | `orthomosaic` |
| `dsm`, `surface` | `dsm` |
| `dem`, `dtm`, `terrain` | `dem` |
| `pointcloud`, `point_cloud`, `.las`, `.laz` | `point_cloud` |
| `.pdf` | `report` |
| anything else | `other` |

Case-insensitive match on filename stem.

---

## CLI Command

```
autogis envmon import-drone-products \
  --flight-id <flight_id> \
  --products <file_or_glob>  \  # repeatable; globs supported
  --flight-date YYYY-MM-DD \
  --catalog <drone_products.csv> \
  [--notes "Pix4D output 2026-06-15"] \
  [--allow-update] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_drone_product_importer.py` — arcpy-free:

1. `infer_product_type(Path("H281_ortho_2026.tif"))` → `"orthomosaic"`
2. `infer_product_type(Path("DSM_20260615.tif"))` → `"dsm"`
3. `infer_product_type(Path("report.pdf"))` → `"report"`
4. `import_drone_products` with 3 files → 3 records in catalog
5. Same SHA-256 → skipped, INFO in QA
6. `allow_update=True` with changed file → new record added
7. `load_product_catalog` / `write_product_catalog` round-trip preserves fields
8. `read_geotiff_metadata` on non-TIFF → returns empty dict (no error)
