# ExportEnvDataToGeoPackage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ExportEnvDataToGeoPackage` — write wells with WKB geometry + analytical results as non-spatial table into a minimal GeoPackage (SQLite) using only stdlib `sqlite3`; no GDAL/geopandas.
See spec: `docs/superpowers/specs/2026-06-28-export-env-data-geopackage-design.md`.

**Architecture:**
- New: `autogis/core/envmon/geopackage_exporter.py`
- Modify: `autogis/adapters/cli.py` — add `export-geopackage` command (headless)
- New: `tests/envmon/test_geopackage_exporter.py`

## Global Constraints

- Arcpy-free. stdlib only: `sqlite3`, `struct`, `csv`.
- WKB point: 21 bytes (byte order + type + x + y, all little-endian).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `geopackage_exporter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_geopackage_exporter.py`:

```python
import sqlite3
import struct
from pathlib import Path
import pytest
from autogis.core.envmon.geopackage_exporter import (
    encode_wkb_point, create_geopackage,
    write_wells_layer, write_tabular_layer,
    export_env_data_geopackage, GeoPackageResult,
)

_WELLS = [
    {"LocationID": "MW-01", "Latitude": "34.1234", "Longitude": "-118.4567",
     "WellType": "monitoring well"},
    {"LocationID": "MW-02", "Latitude": "34.2345", "Longitude": "-118.5678",
     "WellType": "piezometer"},
    {"LocationID": "MW-BAD", "Latitude": "", "Longitude": "",
     "WellType": "monitoring well"},  # missing coords
]
_RESULTS = [
    {"SampleID": "S1", "LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "5.0", "SampleDate": "2026-06-15"},
]


def test_wkb_length():
    wkb = encode_wkb_point(-118.4567, 34.1234)
    assert len(wkb) == 21


def test_wkb_round_trip():
    lon, lat = -118.4567, 34.1234
    wkb = encode_wkb_point(lon, lat)
    # byte_order (1) + wkb_type (4) + x (8) + y (8)
    assert wkb[0:1] == b"\x01"  # little-endian
    x = struct.unpack_from("<d", wkb, 5)[0]
    y = struct.unpack_from("<d", wkb, 13)[0]
    assert x == pytest.approx(lon)
    assert y == pytest.approx(lat)


def test_create_geopackage(tmp_path):
    gpkg = tmp_path / "test.gpkg"
    create_geopackage(gpkg)
    assert gpkg.exists()
    conn = sqlite3.connect(str(gpkg))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "gpkg_contents" in tables
    conn.close()


def test_write_wells_layer(tmp_path):
    gpkg = tmp_path / "test.gpkg"
    create_geopackage(gpkg)
    conn = sqlite3.connect(str(gpkg))
    count = write_wells_layer(conn, _WELLS)
    conn.commit()
    conn.close()
    # MW-BAD has no coords → skipped or placeholder
    assert count == 2  # only valid coords inserted


def test_write_tabular_layer(tmp_path):
    gpkg = tmp_path / "test.gpkg"
    create_geopackage(gpkg)
    conn = sqlite3.connect(str(gpkg))
    count = write_tabular_layer(conn, "analytical_results", _RESULTS)
    conn.commit()
    row = conn.execute("SELECT COUNT(*) FROM analytical_results").fetchone()[0]
    conn.close()
    assert row == 1


def test_export_produces_gpkg(tmp_path):
    gpkg = tmp_path / "site.gpkg"
    result = export_env_data_geopackage(_WELLS, _RESULTS, gpkg)
    assert gpkg.exists()
    assert result.well_count == 2
    assert result.result_count == 1


def test_missing_coords_warning(tmp_path):
    gpkg = tmp_path / "site.gpkg"
    result = export_env_data_geopackage(_WELLS, _RESULTS, gpkg)
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_overwrite_false_fails_if_exists(tmp_path):
    gpkg = tmp_path / "site.gpkg"
    export_env_data_geopackage(_WELLS[:1], [], gpkg)
    with pytest.raises(Exception):
        export_env_data_geopackage(_WELLS[:1], [], gpkg, overwrite=False)


def test_overwrite_true_succeeds(tmp_path):
    gpkg = tmp_path / "site.gpkg"
    export_env_data_geopackage(_WELLS[:1], [], gpkg)
    result = export_env_data_geopackage(_WELLS[:1], [], gpkg, overwrite=True)
    assert result.well_count >= 1
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_geopackage_exporter.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/geopackage_exporter.py`**

```python
"""geopackage_exporter.py — minimal OGC GeoPackage writer (stdlib sqlite3 only)."""
from __future__ import annotations

import csv
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_ERROR, SEV_INFO, SEV_WARNING

_GPKG_SRS_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


@dataclass
class GeoPackageResult:
    gpkg_path: Path
    layers: list
    well_count: int
    result_count: int
    qa: QACollector


def encode_wkb_point(lon: float, lat: float) -> bytes:
    """ISO WKB point, little-endian: byte_order + type + x + y."""
    return struct.pack("<bIdd", 1, 1, lon, lat)


def _parse_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def create_geopackage(gpkg_path: Path, *, srs_id: int = 4326,
                      overwrite: bool = True) -> None:
    p = Path(gpkg_path)
    if p.exists():
        if not overwrite:
            raise FileExistsError(f"GeoPackage already exists: {p}")
        p.unlink()
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA application_id = 1196444487")  # 0x47504B47
    conn.execute("PRAGMA user_version = 10200")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );
        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x REAL, min_y REAL, max_x REAL, max_y REAL,
            srs_id INTEGER,
            CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)
                REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name)
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)",
        ("WGS 84", srs_id, "EPSG", srs_id, _GPKG_SRS_WKT, "WGS 84 geographic"),
    )
    conn.commit()
    conn.close()


def write_wells_layer(
    conn,
    well_rows: list,
    *,
    lat_field: str = "Latitude",
    lon_field: str = "Longitude",
    id_field: str = "LocationID",
) -> int:
    # Discover non-geometry columns from first row
    if not well_rows:
        return 0
    sample = well_rows[0]
    extra_cols = [k for k in sample.keys()
                  if k not in (lat_field, lon_field)]
    col_defs = ", ".join(f'"{c}" TEXT' for c in extra_cols)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS wells (
            fid INTEGER PRIMARY KEY AUTOINCREMENT,
            geom BLOB,
            {col_defs}
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
        ("wells", "geom", "POINT", 4326, 0, 0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO gpkg_contents(table_name,data_type,identifier,srs_id) "
        "VALUES (?,?,?,?)", ("wells", "features", "wells", 4326),
    )
    count = 0
    for r in well_rows:
        lat = _parse_float(r.get(lat_field, ""))
        lon = _parse_float(r.get(lon_field, ""))
        if lat is None or lon is None:
            continue
        wkb = encode_wkb_point(lon, lat)
        vals = [wkb] + [r.get(c, "") for c in extra_cols]
        placeholders = ", ".join(["?"] * (len(extra_cols) + 1))
        conn.execute(
            f"INSERT INTO wells (geom, {', '.join(f'{chr(34)}{c}{chr(34)}' for c in extra_cols)}) "
            f"VALUES ({placeholders})", vals,
        )
        count += 1
    return count


def write_tabular_layer(conn, table_name: str, rows: list) -> int:
    if not rows:
        return 0
    cols = list(rows[0].keys())
    col_defs = ", ".join(f'"{c}" TEXT' for c in cols)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            fid INTEGER PRIMARY KEY AUTOINCREMENT,
            {col_defs}
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO gpkg_contents(table_name,data_type,identifier) "
        "VALUES (?,?,?)", (table_name, "attributes", table_name),
    )
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(f'"{c}"' for c in cols)
    for r in rows:
        conn.execute(
            f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
            [r.get(c, "") for c in cols],
        )
    return len(rows)


def export_env_data_geopackage(
    well_rows: list,
    result_rows: list,
    gpkg_path: Path,
    *,
    water_level_rows: Optional[list] = None,
    overwrite: bool = False,
    qa: Optional[QACollector] = None,
) -> GeoPackageResult:
    if qa is None:
        qa = QACollector()
    gpkg_path = Path(gpkg_path)

    if gpkg_path.exists() and not overwrite:
        qa.add(QARecord(SEV_ERROR, "file_exists",
                        f"{gpkg_path} already exists. Use overwrite=True."))
        raise FileExistsError(f"{gpkg_path} already exists.")

    # Count wells with missing coords for warning
    missing_coords = sum(
        1 for r in well_rows
        if not r.get("Latitude") or not r.get("Longitude")
    )
    if missing_coords:
        qa.add(QARecord(SEV_WARNING, "missing_coords",
                        f"{missing_coords} well(s) skipped — missing lat/lon."))

    create_geopackage(gpkg_path, overwrite=True)
    conn = sqlite3.connect(str(gpkg_path))
    well_count = write_wells_layer(conn, well_rows)
    result_count = write_tabular_layer(conn, "analytical_results", result_rows)
    layers = ["wells", "analytical_results"]
    if water_level_rows:
        write_tabular_layer(conn, "water_levels", water_level_rows)
        layers.append("water_levels")
    conn.commit()
    conn.close()

    qa.add(QARecord(SEV_INFO, "geopackage_exported",
                    f"{well_count} wells, {result_count} results → {gpkg_path}"))

    return GeoPackageResult(
        gpkg_path=gpkg_path, layers=layers,
        well_count=well_count, result_count=result_count, qa=qa,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_geopackage_exporter.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/geopackage_exporter.py \
        tests/envmon/test_geopackage_exporter.py
git commit -m "feat(envmon): geopackage_exporter — stdlib sqlite3 GeoPackage writer with WKB points"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("export-geopackage")
@click.option("--wells", "wells_path", required=True, type=click.Path(exists=True))
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--water-levels", "wl_path", default=None, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
def export_geopackage_cmd(wells_path, results_path, wl_path, out,
                           overwrite, report):
    """Export envmon data to OGC GeoPackage (stdlib sqlite3, headless)."""
    import csv as _csv
    from autogis.core.envmon.geopackage_exporter import export_env_data_geopackage

    with open(wells_path, newline="", encoding="utf-8") as fh:
        wells = list(_csv.DictReader(fh))
    with open(results_path, newline="", encoding="utf-8") as fh:
        results = list(_csv.DictReader(fh))
    wl_rows = None
    if wl_path:
        with open(wl_path, newline="", encoding="utf-8") as fh:
            wl_rows = list(_csv.DictReader(fh))
    result = export_env_data_geopackage(wells, results, Path(out),
                                         water_level_rows=wl_rows,
                                         overwrite=overwrite)
    click.echo(f"Wells: {result.well_count}  Results: {result.result_count}  "
               f"Layers: {result.layers}  Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_export_geopackage_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "export-geopackage" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_geopackage_exporter.py
git commit -m "feat(cli): add export-geopackage command"
```
