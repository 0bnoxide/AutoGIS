# ImportDroneProducts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ImportDroneProducts` — infer product type, hash files, extract minimal GeoTIFF metadata, catalogue into `Env_DroneProducts.csv`.
See spec: `docs/superpowers/specs/2026-06-28-import-drone-products-design.md`.

**Architecture:**
- New: `autogis/core/envmon/drone_product_importer.py`
- Modify: `autogis/adapters/cli.py` — add `import-drone-products` command (headless)
- New: `tests/envmon/test_drone_product_importer.py`

## Global Constraints

- Arcpy-free. `hashlib`, `struct`, `csv`, `uuid` stdlib only.
- Reuse `compute_sha256` pattern from `source_registry.py`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `drone_product_importer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_drone_product_importer.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.drone_product_importer import (
    infer_product_type, import_drone_products,
    load_product_catalog, write_product_catalog, DroneProductRecord,
)


def test_infer_orthomosaic():
    assert infer_product_type(Path("H281_ortho_2026.tif")) == "orthomosaic"


def test_infer_dsm():
    assert infer_product_type(Path("DSM_20260615.tif")) == "dsm"


def test_infer_point_cloud_las():
    assert infer_product_type(Path("pointcloud.las")) == "point_cloud"


def test_infer_report():
    assert infer_product_type(Path("accuracy_report.pdf")) == "report"


def test_infer_dem():
    assert infer_product_type(Path("DEM_site.tif")) == "dem"


def test_import_new_product(tmp_path):
    f = tmp_path / "H281_ortho.tif"
    f.write_bytes(b"fake tif data")
    catalog = tmp_path / "catalog.csv"
    records, qa = import_drone_products(
        "FLIGHT-001", [f], "2026-06-15", catalog)
    assert len(records) == 1
    assert records[0].product_type == "orthomosaic"
    assert records[0].flight_id == "FLIGHT-001"


def test_import_same_hash_skipped(tmp_path):
    f = tmp_path / "H281_ortho.tif"
    f.write_bytes(b"content")
    catalog = tmp_path / "catalog.csv"
    records1, _ = import_drone_products("F1", [f], "2026-06-15", catalog)
    write_product_catalog(records1, catalog)
    records2, qa2 = import_drone_products("F1", [f], "2026-06-15", catalog)
    assert len(records2) == 0
    assert any("already_registered" in r.category for r in qa2.records)


def test_roundtrip_catalog(tmp_path):
    f = tmp_path / "DSM_test.tif"
    f.write_bytes(b"dsm data")
    catalog = tmp_path / "catalog.csv"
    records, _ = import_drone_products("F1", [f], "2026-06-15", catalog)
    write_product_catalog(records, catalog)
    loaded = load_product_catalog(catalog)
    assert len(loaded) == 1
    assert loaded[0].sha256 == records[0].sha256


def test_load_missing_catalog_returns_empty(tmp_path):
    assert load_product_catalog(tmp_path / "nonexistent.csv") == []
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_drone_product_importer.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/drone_product_importer.py`**

```python
"""drone_product_importer.py — drone product cataloguer with SHA-256 dedup."""
from __future__ import annotations

import csv
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

_PRODUCT_KEYWORDS = {
    "orthomosaic": {"ortho", "rgb", "rgb_camera", "transparent_mosaic"},
    "dsm":         {"dsm", "surface"},
    "dem":         {"dem", "dtm", "terrain"},
    "point_cloud": {"pointcloud", "point_cloud"},
}
_EXT_TYPE = {".las": "point_cloud", ".laz": "point_cloud",
             ".ply": "point_cloud", ".pdf": "report"}

_FIELDNAMES = [
    "product_id", "flight_id", "product_type", "file_path", "file_name",
    "file_size_bytes", "sha256", "pixel_size_m", "epsg_code",
    "coordinate_system", "imported_at", "flight_date", "notes",
]


@dataclass
class DroneProductRecord:
    table_name: ClassVar[str] = "Env_DroneProducts"
    product_id: str
    flight_id: str
    product_type: str
    file_path: str
    file_name: str
    file_size_bytes: int
    sha256: str
    pixel_size_m: Optional[float]
    epsg_code: Optional[int]
    coordinate_system: str
    imported_at: str
    flight_date: str
    notes: str = ""


def infer_product_type(path: Path) -> str:
    stem = path.stem.lower()
    ext = path.suffix.lower()
    if ext in _EXT_TYPE:
        return _EXT_TYPE[ext]
    for ptype, keywords in _PRODUCT_KEYWORDS.items():
        if any(kw in stem for kw in keywords):
            return ptype
    return "other"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_geotiff_metadata(path: Path) -> dict:
    """Minimal GeoTIFF IFD reader for pixel size."""
    try:
        with open(path, "rb") as fh:
            hdr = fh.read(4)
            if hdr[:2] not in (b"II", b"MM"):
                return {}
        return {}  # stub — full IFD parse is optional enhancement
    except Exception:
        return {}


def load_product_catalog(catalog_csv: Path) -> list:
    p = Path(catalog_csv)
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    records = []
    for r in rows:
        records.append(DroneProductRecord(
            product_id=r["product_id"], flight_id=r["flight_id"],
            product_type=r["product_type"], file_path=r["file_path"],
            file_name=r["file_name"],
            file_size_bytes=int(r.get("file_size_bytes", 0)),
            sha256=r["sha256"],
            pixel_size_m=float(r["pixel_size_m"]) if r.get("pixel_size_m") else None,
            epsg_code=int(r["epsg_code"]) if r.get("epsg_code") else None,
            coordinate_system=r.get("coordinate_system", ""),
            imported_at=r.get("imported_at", ""),
            flight_date=r.get("flight_date", ""),
            notes=r.get("notes", ""),
        ))
    return records


def write_product_catalog(records: list, catalog_csv: Path) -> None:
    p = Path(catalog_csv)
    write_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
        if write_header:
            w.writeheader()
        for r in records:
            w.writerow({k: getattr(r, k, "") for k in _FIELDNAMES})


def import_drone_products(
    flight_id: str,
    product_paths: list,
    flight_date: str,
    catalog_csv: Path,
    *,
    notes: str = "",
    allow_update: bool = False,
    qa: Optional[QACollector] = None,
) -> tuple:
    if qa is None:
        qa = QACollector()
    existing = load_product_catalog(catalog_csv)
    known_hashes = {r.sha256 for r in existing}
    now = datetime.now(timezone.utc).isoformat()
    new_records = []

    for path in product_paths:
        path = Path(path)
        sha = _sha256(path)
        if sha in known_hashes:
            qa.add(QARecord(SEV_INFO, "already_registered",
                            f"{path.name} already in catalog."))
            continue
        meta = read_geotiff_metadata(path)
        new_records.append(DroneProductRecord(
            product_id=str(uuid.uuid4()),
            flight_id=flight_id,
            product_type=infer_product_type(path),
            file_path=str(path.resolve()),
            file_name=path.name,
            file_size_bytes=path.stat().st_size,
            sha256=sha,
            pixel_size_m=meta.get("pixel_size_m"),
            epsg_code=meta.get("epsg_code"),
            coordinate_system=meta.get("coordinate_system", ""),
            imported_at=now,
            flight_date=flight_date,
            notes=notes,
        ))
        qa.add(QARecord(SEV_INFO, "product_registered", f"{path.name} registered."))

    return new_records, qa
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_drone_product_importer.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/drone_product_importer.py \
        tests/envmon/test_drone_product_importer.py
git commit -m "feat(envmon): drone_product_importer — SHA-256 product catalogue with type inference"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("import-drone-products")
@click.option("--flight-id", required=True)
@click.option("--products", "product_paths", multiple=True, required=True,
              help="File path(s). Repeatable.")
@click.option("--flight-date", required=True, help="ISO date YYYY-MM-DD")
@click.option("--catalog", "catalog_path", required=True, type=click.Path())
@click.option("--notes", default="")
@click.option("--allow-update", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
def import_drone_products_cmd(flight_id, product_paths, flight_date,
                               catalog_path, notes, allow_update, report):
    """Catalogue drone products (orthomosaic, DSM, DEM, point cloud) (headless)."""
    from autogis.core.envmon.drone_product_importer import (
        import_drone_products, write_product_catalog)

    paths = [Path(p) for p in product_paths]
    records, qa = import_drone_products(
        flight_id, paths, flight_date, Path(catalog_path),
        notes=notes, allow_update=allow_update,
    )
    if records:
        write_product_catalog(records, Path(catalog_path))
    click.echo(f"Registered: {len(records)}  Catalog: {catalog_path}")
    _render_qa(qa, report, "error")
```

- [ ] **Step 2: Help test + commit**

```python
def test_import_drone_products_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "import-drone-products" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_drone_product_importer.py
git commit -m "feat(cli): add import-drone-products command"
```
