"""geopackage_exporter.py — minimal GeoPackage-style SQLite writer (stdlib sqlite3 only).

Note: point geometries are stored as raw ISO WKB, not the full GeoPackageBinary
(GPB) blob (no magic header/envelope). Some strict GIS clients may not read the
``wells.geom`` column as a spatial column. Wrapping WKB in a GPB header is a
deferred follow-up.
"""
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
    # Build the column list without a trailing comma when there are no extra
    # columns (a wells CSV with only Latitude/Longitude) — otherwise the SQL
    # is invalid and the export crashes on minimal input.
    cols_sql = "fid INTEGER PRIMARY KEY AUTOINCREMENT, geom BLOB"
    if extra_cols:
        cols_sql += ", " + ", ".join(f'"{c}" TEXT' for c in extra_cols)
    conn.execute(f"CREATE TABLE IF NOT EXISTS wells ({cols_sql})")
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
        col_names = "geom"
        if extra_cols:
            col_names += ", " + ", ".join(f'"{c}"' for c in extra_cols)
        placeholders = ", ".join(["?"] * len(vals))
        conn.execute(
            f"INSERT INTO wells ({col_names}) VALUES ({placeholders})", vals,
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
                    f"{well_count} wells, {result_count} results -> {gpkg_path}"))

    return GeoPackageResult(
        gpkg_path=gpkg_path, layers=layers,
        well_count=well_count, result_count=result_count, qa=qa,
    )
