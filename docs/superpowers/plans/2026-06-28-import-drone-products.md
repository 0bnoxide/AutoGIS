# ImportDroneProducts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `ImportDroneProducts` (roadmap 8.8) — parse a drone product manifest CSV into `DroneProductRecord` instances, validate it headlessly, then (in LOCAL/ArcGIS-Pro mode) write rows to `DroneProductRegistry`, load rasters into a mosaic dataset, and optionally insert GCP control points into `DroneControlPoints`.

**Architecture:**
- New: `autogis/core/envmon/import_drone_products.py` — headless manifest parser + QA validator + GCP CSV parser + arcpy-seam write functions (`# pragma: no cover`)
- Modify: `autogis/runtime/capabilities.py` — register both CLI commands
- Modify: `autogis/adapters/cli.py` — add `validate-drone-products` (CLOUD) and `import-drone-products` (LOCAL) commands
- New: `tests/envmon/test_import_drone_products.py` — arcpy-free unit tests
- New: `tests/envmon/test_cli_import_drone_products.py` — CLI help + headless invocation tests

**Tech Stack:** Python 3.x, `csv`, `uuid`, `pathlib`, `dataclasses`; schema dataclasses from `autogis.core.common.schema.drone`; `autogis.core.common.qa.QACollector`; arcpy (`# pragma: no cover` only).

## Global Constraints

- `autogis/core/envmon/import_drone_products.py` MUST import with neither `arcpy` nor `arcgis` present — run `python -c "from autogis.core.envmon.import_drone_products import parse_product_manifest"` in any arcpy-free environment to verify
- All tests in `tests/envmon/test_import_drone_products.py` and `test_cli_import_drone_products.py` are arcpy-free
- Run tests: `python -m pytest -q`
- `DroneProductRecord` and `DroneControlPoint` come from `autogis.core.common.schema.drone` — do **not** redefine them
- Valid product types: `"orthomosaic"`, `"DSM"`, `"DEM"`, `"point_cloud"` (case-sensitive)
- Raster product types (loaded to mosaic dataset): `"orthomosaic"`, `"DSM"`, `"DEM"`; `"point_cloud"` is path-registered only (no LAS dataset creation in v1)
- `write_product_registry()`, `add_rasters_to_catalog()`, `write_gcp_features()` are LOCAL (`# pragma: no cover`); all arcpy imports live inside those functions
- `"import-drone-products"` is `Runtime.LOCAL` in capabilities.py; `_guard("import-drone-products")` is the first call in the CLI command handler — mirrors `import-rtk-survey` exactly
- `"validate-drone-products"` is `Runtime.CLOUD` in capabilities.py — purely headless
- QA API: `qa.add(SEV_ERROR, category_string, message_string)` — the second positional arg is `category` (checked in tests as `r.category`)

## Scope / Non-Goals (inline assumptions)

- **RegisterDroneFlight (8.6) not yet implemented.** `--flight-id` is a caller-supplied argument; the GDB write assumes a matching `DroneFlights` row already exists (created manually or by the future `register-drone-flight` command). No flight-existence check is performed headlessly.
- **Mosaic dataset assumed pre-created.** `add_rasters_to_catalog()` looks up an existing mosaic dataset by name; creating it is the job of `UpgradeEnvMonitoringGDBSchema` (10.3, already shipped).
- **Manifest format is CSV only** (v1). YAML manifests are a future extension.
- **Point clouds are path-registered only** — a row is inserted in `DroneProductRegistry` but no LAS dataset or point cloud layer is created in v1.
- **No spatial reference enforcement.** CRS is stored as a string; projection-matching against the GDB is an arcpy concern left to the `.pyt` toolbox validator.

---

### Task 1: Core headless module — manifest parsing, validation, classification

**Files:**
- Create: `autogis/core/envmon/import_drone_products.py`
- Create: `tests/envmon/test_import_drone_products.py`

**Interfaces:**
- Produces:
  - `parse_product_manifest(path: Path, flight_id: str) -> list[DroneProductRecord]`
  - `validate_drone_products(records: list[DroneProductRecord], qa: QACollector, *, check_paths: bool = False) -> None`
  - `classify_records(records: list[DroneProductRecord]) -> tuple[list[DroneProductRecord], list[DroneProductRecord]]`
  - `parse_gcp_csv(path: Path, flight_id: str) -> list[DroneControlPoint]`
  - `VALID_PRODUCT_TYPES: frozenset[str]`
  - `RASTER_PRODUCT_TYPES: frozenset[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_import_drone_products.py`:

```python
"""Arcpy-free tests for import_drone_products.py."""
import pytest
from pathlib import Path

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.envmon.import_drone_products import (
    parse_product_manifest,
    validate_drone_products,
    classify_records,
    parse_gcp_csv,
    VALID_PRODUCT_TYPES,
    RASTER_PRODUCT_TYPES,
)

_MANIFEST_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
orthomosaic,/data/ortho.tif,EPSG:32612,NAVD88,0.05
DSM,/data/dsm.tif,EPSG:32612,NAVD88,0.05
DEM,/data/dem.tif,EPSG:32612,NAVD88,0.10
point_cloud,/data/cloud.las,EPSG:32612,NAVD88,
"""

_GCP_CSV = """\
point_id,northing,easting,elevation,point_type,residual_h,residual_v
GCP-01,4527893.12,293847.55,512.34,GCP,0.02,0.03
GCP-02,4527750.00,293900.00,509.12,GCP,,
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---- parse_product_manifest --------------------------------------------------

def test_parse_manifest_count(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    assert len(records) == 4


def test_parse_manifest_flight_id_stamped(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    assert all(r.flight_id == "FLT-001" for r in records)


def test_parse_manifest_product_ids_unique(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    ids = [r.product_id for r in records]
    assert len(set(ids)) == 4, "Each row must get a unique UUID product_id"


def test_parse_manifest_qa_status_pending(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    assert all(r.qa_status == "pending" for r in records)


def test_parse_manifest_resolution_none_for_point_cloud(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    pc = next(r for r in records if r.product_type == "point_cloud")
    assert pc.resolution_m is None


def test_parse_manifest_resolution_float_for_raster(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    ortho = next(r for r in records if r.product_type == "orthomosaic")
    assert abs(ortho.resolution_m - 0.05) < 1e-9


def test_parse_manifest_product_types_preserved(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    types = {r.product_type for r in records}
    assert types == {"orthomosaic", "DSM", "DEM", "point_cloud"}


def test_parse_manifest_empty_file_returns_empty(tmp_path):
    p = _write(tmp_path, "empty.csv", "product_type,path,crs,vertical_datum,resolution_m\n")
    records = parse_product_manifest(p, "FLT-002")
    assert records == []


# ---- validate_drone_products ------------------------------------------------

def test_validate_valid_records_no_errors(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    qa = QACollector()
    validate_drone_products(records, qa)
    error_cats = [r.category for r in qa.records if r.severity == SEV_ERROR]
    assert error_cats == [], f"Expected no errors, got: {error_cats}"


def test_validate_invalid_product_type(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\nbadtype,/data/x.tif,EPSG:4326,,\n"
    p = _write(tmp_path, "bad.csv", content)
    records = parse_product_manifest(p, "FLT-002")
    qa = QACollector()
    validate_drone_products(records, qa)
    categories = [r.category for r in qa.records]
    assert "invalid_product_type" in categories


def test_validate_duplicate_product_type(tmp_path):
    content = (
        "product_type,path,crs,vertical_datum,resolution_m\n"
        "orthomosaic,/data/a.tif,EPSG:4326,,\n"
        "orthomosaic,/data/b.tif,EPSG:4326,,\n"
    )
    p = _write(tmp_path, "dup.csv", content)
    records = parse_product_manifest(p, "FLT-003")
    qa = QACollector()
    validate_drone_products(records, qa)
    categories = [r.category for r in qa.records]
    assert "duplicate_product_type" in categories


def test_validate_empty_path_is_error(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,,EPSG:4326,,\n"
    p = _write(tmp_path, "nopath.csv", content)
    records = parse_product_manifest(p, "FLT-004")
    qa = QACollector()
    validate_drone_products(records, qa)
    categories = [r.category for r in qa.records]
    assert "empty_path" in categories


def test_validate_empty_crs_is_warning(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,/data/x.tif,,,\n"
    p = _write(tmp_path, "nocrs.csv", content)
    records = parse_product_manifest(p, "FLT-005")
    qa = QACollector()
    validate_drone_products(records, qa)
    warning_cats = [r.category for r in qa.records if r.severity == SEV_WARNING]
    assert "empty_crs" in warning_cats


def test_validate_check_paths_missing_file_is_error(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\northomosaic,/nonexistent/ortho.tif,EPSG:4326,,\n"
    p = _write(tmp_path, "missing.csv", content)
    records = parse_product_manifest(p, "FLT-006")
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=True)
    categories = [r.category for r in qa.records]
    assert "path_not_found" in categories


def test_validate_check_paths_existing_file_no_error(tmp_path):
    real = tmp_path / "ortho.tif"
    real.write_bytes(b"")
    content = f"product_type,path,crs,vertical_datum,resolution_m\northomosaic,{real},EPSG:4326,,\n"
    p = _write(tmp_path, "real.csv", content)
    records = parse_product_manifest(p, "FLT-007")
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=True)
    assert not any(r.category == "path_not_found" for r in qa.records)


def test_validate_empty_manifest_is_warning(tmp_path):
    p = _write(tmp_path, "empty.csv", "product_type,path,crs,vertical_datum,resolution_m\n")
    records = parse_product_manifest(p, "FLT-008")
    qa = QACollector()
    validate_drone_products(records, qa)
    categories = [r.category for r in qa.records]
    assert "empty_manifest" in categories


def test_validate_produces_info_record_on_success(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    qa = QACollector()
    validate_drone_products(records, qa)
    info_cats = [r.category for r in qa.records if r.severity == SEV_INFO]
    assert "manifest_parsed" in info_cats


# ---- classify_records -------------------------------------------------------

def test_classify_raster_vs_non_raster(tmp_path):
    p = _write(tmp_path, "manifest.csv", _MANIFEST_CSV)
    records = parse_product_manifest(p, "FLT-001")
    rasters, others = classify_records(records)
    assert len(rasters) == 3
    assert len(others) == 1
    assert all(r.product_type in RASTER_PRODUCT_TYPES for r in rasters)
    assert others[0].product_type == "point_cloud"


def test_classify_all_rasters(tmp_path):
    content = (
        "product_type,path,crs,vertical_datum,resolution_m\n"
        "orthomosaic,/data/ortho.tif,EPSG:4326,,\n"
        "DSM,/data/dsm.tif,EPSG:4326,,\n"
    )
    p = _write(tmp_path, "rasters.csv", content)
    records = parse_product_manifest(p, "FLT-009")
    rasters, others = classify_records(records)
    assert len(rasters) == 2
    assert others == []


def test_classify_all_point_clouds(tmp_path):
    content = "product_type,path,crs,vertical_datum,resolution_m\npoint_cloud,/data/cloud.las,EPSG:4326,,\n"
    p = _write(tmp_path, "pc.csv", content)
    records = parse_product_manifest(p, "FLT-010")
    rasters, others = classify_records(records)
    assert rasters == []
    assert len(others) == 1


# ---- parse_gcp_csv ----------------------------------------------------------

def test_parse_gcp_csv_count(tmp_path):
    p = _write(tmp_path, "gcps.csv", _GCP_CSV)
    pts = parse_gcp_csv(p, "FLT-001")
    assert len(pts) == 2


def test_parse_gcp_csv_flight_id_stamped(tmp_path):
    p = _write(tmp_path, "gcps.csv", _GCP_CSV)
    pts = parse_gcp_csv(p, "FLT-011")
    assert all(pt.flight_id == "FLT-011" for pt in pts)


def test_parse_gcp_csv_residuals_optional(tmp_path):
    p = _write(tmp_path, "gcps.csv", _GCP_CSV)
    pts = parse_gcp_csv(p, "FLT-001")
    assert abs(pts[0].residual_h - 0.02) < 1e-9
    assert pts[1].residual_h is None
    assert pts[1].residual_v is None


def test_parse_gcp_csv_coordinates(tmp_path):
    p = _write(tmp_path, "gcps.csv", _GCP_CSV)
    pts = parse_gcp_csv(p, "FLT-001")
    assert abs(pts[0].northing - 4527893.12) < 0.001
    assert abs(pts[0].easting - 293847.55) < 0.001
    assert abs(pts[0].elevation - 512.34) < 0.001


# ---- module-level import safety (no arcpy) ----------------------------------

def test_module_imports_without_arcpy():
    """Verify the module is importable in an arcpy-free environment."""
    import importlib
    mod = importlib.import_module("autogis.core.envmon.import_drone_products")
    assert hasattr(mod, "parse_product_manifest")
    assert hasattr(mod, "validate_drone_products")
    assert hasattr(mod, "classify_records")
    assert hasattr(mod, "parse_gcp_csv")
```

- [ ] **Step 2: Run tests to confirm failure**

```
python -m pytest tests/envmon/test_import_drone_products.py -v
```

Expected: all fail with `ModuleNotFoundError: No module named 'autogis.core.envmon.import_drone_products'`

- [ ] **Step 3: Create `autogis/core/envmon/import_drone_products.py`**

```python
"""import_drone_products.py — drone product manifest parsing and GDB import.

parse_product_manifest(), validate_drone_products(), classify_records(), and
parse_gcp_csv() are arcpy-free and fully unit-testable.

write_product_registry(), add_rasters_to_catalog(), and write_gcp_features()
require arcpy (ArcGIS Pro) and are marked # pragma: no cover.
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


def parse_product_manifest(
    path: Path,
    flight_id: str,
) -> list[DroneProductRecord]:
    """Parse a product manifest CSV into DroneProductRecord instances.

    Manifest CSV columns (header required):
        product_type, path, crs, vertical_datum, resolution_m

    ``flight_id`` is stamped onto every record from the caller argument — it is
    not read from the CSV.  A unique product_id (UUID4) is generated per row.
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

    Rules:
    - product_type must be one of VALID_PRODUCT_TYPES          (ERROR)
    - duplicate product_type within the same set               (WARNING)
    - path must be non-empty                                   (ERROR)
    - crs should be non-empty                                  (WARNING)
    - if check_paths is True, each non-empty path must exist   (ERROR)

    A manifest_parsed INFO record is always added on non-empty input.
    An empty_manifest WARNING is added when records is empty.
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
        if rec.product_type:
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
    Non-raster types (point_cloud) are path-registered only (v1).
    This function is pure and fully testable without arcpy.
    """
    rasters = [r for r in records if r.product_type in RASTER_PRODUCT_TYPES]
    others = [r for r in records if r.product_type not in RASTER_PRODUCT_TYPES]
    return rasters, others


def parse_gcp_csv(
    path: Path,
    flight_id: str,
) -> list[DroneControlPoint]:
    """Parse a GCP CSV into DroneControlPoint instances.

    CSV columns (header required):
        point_id, northing, easting, elevation, point_type
    Optional columns: residual_h, residual_v

    ``flight_id`` is stamped from the caller argument.
    """
    def _opt_float(row: dict, key: str):
        v = row.get(key, "").strip()
        return float(v) if v else None

    out: list[DroneControlPoint] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(DroneControlPoint(
                point_id=row.get("point_id", "").strip(),
                flight_id=flight_id,
                northing=float(row["northing"]),
                easting=float(row["easting"]),
                elevation=float(row["elevation"]),
                point_type=row.get("point_type", "GCP").strip(),
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
    """Insert DroneProductRecord rows into DroneProductRegistry table (ArcGIS Pro).

    Each record is inserted as-is; the table must exist (created by
    UpgradeEnvMonitoringGDBSchema or an existing GDB).
    """
    import arcpy
    from pathlib import Path as _P

    table = str(_P(gdb_path) / "DroneProductRegistry")
    if not arcpy.Exists(table):
        return
    fields = [
        "ProductID", "FlightID", "ProductType", "Path",
        "CRS", "VerticalDatum", "Resolution_m", "QAStatus",
    ]
    with arcpy.da.InsertCursor(table, fields) as cur:
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

    Args:
        gdb_path:      Path to the File GDB.
        catalog_name:  Name of an existing mosaic dataset inside the GDB.
        raster_records: DroneProductRecord instances with product_type in
                        RASTER_PRODUCT_TYPES (orthomosaic, DSM, DEM).

    Returns the number of rasters successfully added.  Skips any whose path
    does not exist on disk.
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
                catalog_path,
                "Raster Dataset",
                r.path,
            )
            added += 1
    return added


def write_gcp_features(  # pragma: no cover
    gdb_path: str,
    points: list[DroneControlPoint],
) -> None:
    """Insert DroneControlPoint rows into the DroneControlPoints feature class.

    Geometry is built from (easting, northing) — the feature class spatial
    reference must already match the survey CRS.
    """
    import arcpy
    from pathlib import Path as _P

    fc = str(_P(gdb_path) / "DroneControlPoints")
    if not arcpy.Exists(fc):
        return
    fields = [
        "SHAPE@", "PointID", "FlightID",
        "Northing", "Easting", "Elevation",
        "PointType", "Residual_H", "Residual_V",
    ]
    with arcpy.da.InsertCursor(fc, fields) as cur:
        for pt in points:
            geom = arcpy.PointGeometry(arcpy.Point(pt.easting, pt.northing))
            cur.insertRow([
                geom, pt.point_id, pt.flight_id,
                pt.northing, pt.easting, pt.elevation,
                pt.point_type, pt.residual_h, pt.residual_v,
            ])
```

- [ ] **Step 4: Run tests — all should pass**

```
python -m pytest tests/envmon/test_import_drone_products.py -v
```

Expected: 27 PASS.

- [ ] **Step 5: Verify module is arcpy-free**

```
python -c "from autogis.core.envmon.import_drone_products import parse_product_manifest; print('OK')"
```

Expected: prints `OK` with no import error.

- [ ] **Step 6: Full suite regression**

```
python -m pytest -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add autogis/core/envmon/import_drone_products.py tests/envmon/test_import_drone_products.py
git commit -m "feat(envmon): import_drone_products — headless manifest parser + GDB write seam"
```

---

### Task 2: Register commands in `capabilities.py`

**Files:**
- Modify: `autogis/runtime/capabilities.py`

**Interfaces:**
- Consumes: `TOOLS` dict in `autogis/runtime/capabilities.py`
- Produces: `"validate-drone-products"` and `"import-drone-products"` registered so `_guard()` and `requires_arcpy()` work without KeyError

**Background:** `requires_arcpy(name)` does `return TOOLS[name] is Runtime.LOCAL`. If the name is absent the dict raises a `KeyError` (the issue-#62 pattern from MEMORY.md). Both new commands must be added before any CLI test can call `_guard()`.

- [ ] **Step 1: Write the failing test**

Add to `tests/envmon/test_cli_import_drone_products.py` (create this file):

```python
"""CLI tests for validate-drone-products and import-drone-products."""
from click.testing import CliRunner
from autogis.adapters.cli import autogis


def test_validate_drone_products_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-drone-products" in result.output, result.output


def test_import_drone_products_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-drone-products" in result.output, result.output
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_cli_import_drone_products.py -v
```

Expected: FAIL — commands not yet registered in the CLI.

- [ ] **Step 3: Add entries to `autogis/runtime/capabilities.py`**

Open `autogis/runtime/capabilities.py`. In the `TOOLS` dict, after the `"drone-checkpoint-qa"` entry (line 43), add:

```python
    "validate-drone-products": Runtime.CLOUD,  # tool 8.8 headless surface
    "import-drone-products": Runtime.LOCAL,    # tool 8.8 LOCAL write
```

The full dict now ends with:

```python
    "drone-checkpoint-qa": Runtime.CLOUD,     # tool 11.1
    "export-geojson": Runtime.CLOUD,          # tool 10.3
    "generate-event-report": Runtime.CLOUD,   # tool 10.5
    "run-history": Runtime.CLOUD,             # tool 10.1b (query CLI)
    "validate-drone-products": Runtime.CLOUD, # tool 8.8 headless surface
    "import-drone-products": Runtime.LOCAL,   # tool 8.8 LOCAL write
}
```

- [ ] **Step 4: Confirm no test regressions yet (commands not in CLI so help tests still fail)**

```
python -m pytest tests/envmon/test_cli_import_drone_products.py -v
```

Expected: still FAIL on "validate-drone-products" in output — the CLI commands haven't been wired yet. That's correct; we're confirming capabilities.py change doesn't break the suite.

```
python -m pytest -q --ignore=tests/envmon/test_cli_import_drone_products.py
```

Expected: all other tests still PASS.

- [ ] **Step 5: Commit the capabilities registration**

```bash
git add autogis/runtime/capabilities.py
git commit -m "feat(capabilities): register validate-drone-products (CLOUD) and import-drone-products (LOCAL)"
```

---

### Task 3: CLI commands + headless integration test

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `tests/envmon/test_cli_import_drone_products.py` (extend)

**Interfaces:**
- Consumes: `parse_product_manifest`, `validate_drone_products`, `classify_records`, `parse_gcp_csv`, `write_product_registry`, `add_rasters_to_catalog`, `write_gcp_features` from `autogis.core.envmon.import_drone_products`
- Produces:
  - `autogis envmon validate-drone-products --manifest MANIFEST --flight-id FLT [--check-paths] [--report REPORT] [--fail-on error|warning]`
  - `autogis envmon import-drone-products --manifest MANIFEST --flight-id FLT --site-id SITE --gdb GDB [--catalog-name NAME] [--gcp-csv GCP] [--report REPORT] [--fail-on error|warning]`

- [ ] **Step 1: Extend `test_cli_import_drone_products.py` with headless CLI test**

Replace the file content with:

```python
"""CLI tests for validate-drone-products and import-drone-products."""
import csv
from pathlib import Path
from click.testing import CliRunner
from autogis.adapters.cli import autogis

_MANIFEST_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
orthomosaic,/data/ortho.tif,EPSG:32612,NAVD88,0.05
DSM,/data/dsm.tif,EPSG:32612,NAVD88,0.05
DEM,/data/dem.tif,EPSG:32612,NAVD88,0.10
point_cloud,/data/cloud.las,EPSG:32612,NAVD88,
"""

_MANIFEST_BAD_CSV = """\
product_type,path,crs,vertical_datum,resolution_m
badtype,,,,
"""


def test_validate_drone_products_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "validate-drone-products" in result.output, result.output


def test_import_drone_products_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-drone-products" in result.output, result.output


def test_validate_drone_products_valid_manifest_exits_zero(tmp_path):
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    result = CliRunner().invoke(
        autogis,
        ["envmon", "validate-drone-products",
         "--manifest", str(p), "--flight-id", "FLT-001"],
    )
    assert result.exit_code == 0, result.output
    assert "Status: PASS" in result.output


def test_validate_drone_products_bad_manifest_exits_nonzero(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text(_MANIFEST_BAD_CSV, encoding="utf-8")
    result = CliRunner().invoke(
        autogis,
        ["envmon", "validate-drone-products",
         "--manifest", str(p), "--flight-id", "FLT-002"],
    )
    assert result.exit_code != 0, result.output
    assert "invalid_product_type" in result.output


def test_validate_drone_products_report_csv(tmp_path):
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    report = tmp_path / "qa.csv"
    result = CliRunner().invoke(
        autogis,
        ["envmon", "validate-drone-products",
         "--manifest", str(p), "--flight-id", "FLT-001",
         "--report", str(report)],
    )
    assert result.exit_code == 0, result.output
    assert report.exists()
    rows = list(csv.DictReader(report.open(encoding="utf-8")))
    # At least the manifest_parsed INFO record should appear
    assert any(r["category"] == "manifest_parsed" for r in rows)


def test_import_drone_products_missing_arcpy_exits_clean(tmp_path):
    """Without arcpy, import-drone-products should print a clean ClickException."""
    p = tmp_path / "manifest.csv"
    p.write_text(_MANIFEST_CSV, encoding="utf-8")
    result = CliRunner().invoke(
        autogis,
        ["envmon", "import-drone-products",
         "--manifest", str(p), "--flight-id", "FLT-001",
         "--site-id", "SITE-001", "--gdb", str(tmp_path / "fake.gdb")],
    )
    # Without arcpy the guard raises a ClickException (clean message, no traceback)
    assert result.exit_code != 0
    assert "arcpy" in result.output.lower() or "ArcGIS Pro" in result.output
```

- [ ] **Step 2: Run extended tests — confirm help tests still fail (commands not yet in CLI)**

```
python -m pytest tests/envmon/test_cli_import_drone_products.py::test_validate_drone_products_in_envmon_help -v
```

Expected: FAIL.

- [ ] **Step 3: Add `validate-drone-products` command to `autogis/adapters/cli.py`**

Place this block after the `drone-checkpoint-qa` command (search for `@envmon.command("drone-checkpoint-qa")`):

```python
@envmon.command("validate-drone-products")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True),
              help="Product manifest CSV (columns: product_type, path, crs, vertical_datum, resolution_m).")
@click.option("--flight-id", required=True,
              help="Drone flight ID to stamp on records.")
@click.option("--check-paths", is_flag=True, default=False,
              help="Verify that each product path exists on disk.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def validate_drone_products_cmd(manifest_path, flight_id, check_paths, report, fail_on):
    """Tool 8.8: validate a drone product manifest CSV (headless)."""
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_drone_products import (
        parse_product_manifest, validate_drone_products,
    )
    records = parse_product_manifest(Path(manifest_path), flight_id)
    qa = QACollector()
    validate_drone_products(records, qa, check_paths=check_paths)
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Add `import-drone-products` command to `autogis/adapters/cli.py`**

Place this block immediately after the `validate-drone-products` command:

```python
@envmon.command("import-drone-products")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True),
              help="Product manifest CSV (columns: product_type, path, crs, vertical_datum, resolution_m).")
@click.option("--flight-id", required=True,
              help="Drone flight ID.  A matching DroneFlights row must already exist in the GDB.")
@click.option("--site-id", required=True, help="Site identifier for logging.")
@click.option("--gdb", "gdb_path", required=True, type=click.Path(),
              help="Path to the File GDB (ArcGIS Pro required).")
@click.option("--catalog-name", default="DroneMosaicDataset", show_default=True,
              help="Name of the existing mosaic dataset inside the GDB.")
@click.option("--gcp-csv", "gcp_csv_path", default=None, type=click.Path(exists=True),
              help="Optional GCP CSV (columns: point_id, northing, easting, elevation, point_type).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def import_drone_products_cmd(manifest_path, flight_id, site_id, gdb_path,
                               catalog_name, gcp_csv_path, report, fail_on):
    """Tool 8.8: import drone deliverables to raster catalog + GCP features (ArcGIS Pro)."""
    _guard("import-drone-products")
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.import_drone_products import (
        parse_product_manifest, validate_drone_products, classify_records,
        parse_gcp_csv,
        write_product_registry, add_rasters_to_catalog, write_gcp_features,
    )
    records = parse_product_manifest(Path(manifest_path), flight_id)
    qa = QACollector()
    validate_drone_products(records, qa)
    if qa.has_blocking(allow_warnings=True, allow_errors=False):
        _render_qa(qa, report, fail_on)
        return

    rasters, others = classify_records(records)

    # Write all records to the registry table (rasters + point clouds)
    write_product_registry(gdb_path, records)
    click.echo(f"Registered {len(records)} product(s) in DroneProductRegistry.")

    # Load raster products into the mosaic dataset
    added = add_rasters_to_catalog(gdb_path, catalog_name, rasters)
    click.echo(f"Added {added} raster(s) to mosaic dataset '{catalog_name}'.")

    if others:
        click.echo(f"Path-registered {len(others)} non-raster product(s) "
                   f"(point cloud — no mosaic load in v1).")

    # Optionally write GCP control points
    if gcp_csv_path:
        gcp_points = parse_gcp_csv(Path(gcp_csv_path), flight_id)
        write_gcp_features(gdb_path, gcp_points)
        click.echo(f"Wrote {len(gcp_points)} GCP feature(s) to DroneControlPoints.")

    _render_qa(qa, report, fail_on)
```

- [ ] **Step 5: Run all CLI tests**

```
python -m pytest tests/envmon/test_cli_import_drone_products.py -v
```

Expected output — 7 PASS. The `test_import_drone_products_missing_arcpy_exits_clean` test passes because `_guard("import-drone-products")` raises a clean `click.ClickException` when arcpy is absent (since `"import-drone-products"` is `Runtime.LOCAL`).

- [ ] **Step 6: Full suite**

```
python -m pytest -q
```

Expected: all tests pass (no regressions).

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_import_drone_products.py
git commit -m "feat(cli): add validate-drone-products (CLOUD) and import-drone-products (LOCAL) commands"
```

---

## Self-Review

### 1. Spec coverage

| Requirement | Task |
|---|---|
| Parse drone product manifest (orthomosaic/DSM/DEM/point cloud) | Task 1, `parse_product_manifest` |
| Link to registered drone flight | Task 1 (`flight_id` argument); non-goal note covers 8.6 gap |
| Validate product types, paths, CRS | Task 1, `validate_drone_products` |
| Classify rasters vs. non-rasters (pure, testable) | Task 1, `classify_records` |
| Parse GCP control points | Task 1, `parse_gcp_csv` |
| Write DroneProductRegistry rows (arcpy seam) | Task 1, `write_product_registry` `# pragma: no cover` |
| Load rasters into mosaic dataset (arcpy seam) | Task 1, `add_rasters_to_catalog` `# pragma: no cover` |
| Write GCP features (arcpy seam) | Task 1, `write_gcp_features` `# pragma: no cover` |
| Register commands in capabilities.py (no KeyError) | Task 2 |
| `validate-drone-products` CLOUD CLI command | Task 3 |
| `import-drone-products` LOCAL CLI command with `_guard` | Task 3 |
| arcpy-free invariant enforced | All tasks — arcpy imports only inside `# pragma: no cover` functions |

### 2. Placeholder scan

No TBD, TODO, or "similar to Task N" patterns are present. Every step shows the complete code block.

### 3. Type consistency

- `parse_product_manifest` → `list[DroneProductRecord]` — consumed by `validate_drone_products`, `classify_records`, `write_product_registry`, `add_rasters_to_catalog` — all consistent.
- `parse_gcp_csv` → `list[DroneControlPoint]` — consumed by `write_gcp_features` — consistent.
- `classify_records` → `tuple[list[DroneProductRecord], list[DroneProductRecord]]` — unpacked as `rasters, others` in the CLI — consistent.
- `QACollector.add(SEV_ERROR, category_string, message_string)` — tests check `r.category` (not `r.code`) — consistent with `autogis/core/common/qa.py` `QARecord.category` field.

---

## Risks

| Risk | Mitigation |
|---|---|
| `DroneProductRecord.product_id` has no default in the schema dataclass — `parse_product_manifest` must always supply it | Verified: `uuid.uuid4()` is called per-row in `parse_product_manifest`; tests assert uniqueness |
| `arcpy.management.AddRastersToMosaicDataset` signature varies across ArcGIS Pro versions (< 3.x vs 3.x) | The call uses positional `"Raster Dataset"` raster type which is stable; `.pyt` toolbox can override if needed |
| RegisterDroneFlight (8.6) not yet implemented — `DroneFlights` table may be empty | Documented as non-goal; the GDB write does not attempt to foreign-key validate; the `.pyt` toolbox should enforce referential integrity |
| Point-cloud LAS datasets not created (v1 scope cut) | Documented in non-goals; path is stored in `DroneProductRegistry` for a future v2 `add_las_to_dataset` extension |
| `capabilities.py` `TOOLS` dict KeyError if command name changes | Adding the entries in Task 2 prevents this; `test_import_drone_products_missing_arcpy_exits_clean` exercises the guard path |
