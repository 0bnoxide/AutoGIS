import inspect
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
    geoms = [row[0] for row in conn.execute(
        "SELECT geom FROM wells ORDER BY fid"
    ).fetchall()]
    geom_metadata = conn.execute(
        "SELECT geometry_type_name, srs_id, z, m "
        "FROM gpkg_geometry_columns WHERE table_name = 'wells'"
    ).fetchone()
    contents_metadata = conn.execute(
        "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = 'wells'"
    ).fetchone()
    srs_metadata = conn.execute(
        "SELECT srs_name, srs_id, organization, organization_coordsys_id "
        "FROM gpkg_spatial_ref_sys WHERE srs_id = 4326"
    ).fetchone()
    geom_type = next(
        row[2] for row in conn.execute("PRAGMA table_info(wells)")
        if row[1] == "geom"
    )
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    assert count == 2
    assert geoms == [
        struct.pack(
            "<2sBBibIdd", b"GP", 0, 0x01, 4326,
            1, 1, -118.4567, 34.1234,
        ),
        struct.pack(
            "<2sBBibIdd", b"GP", 0, 0x01, 4326,
            1, 1, -118.5678, 34.2345,
        ),
    ]
    coords = [struct.unpack_from("<dd", geom, 13) for geom in geoms]
    assert coords[0] == pytest.approx((-118.4567, 34.1234))
    assert coords[1] == pytest.approx((-118.5678, 34.2345))
    assert integrity == "ok"
    assert geom_type == "POINT"
    assert geom_metadata == ("POINT", 4326, 0, 0)
    assert contents_metadata == ("features", 4326)
    assert srs_metadata == ("WGS 84", 4326, "EPSG", 4326)


def test_write_wells_layer_has_no_silent_id_field_keyword():
    assert "id_field" not in inspect.signature(write_wells_layer).parameters


def test_write_wells_layer_coords_only(tmp_path):
    # Wells with only Latitude/Longitude (no extra columns) must not produce a
    # trailing-comma CREATE/INSERT and crash. Regression for the empty
    # extra_cols case.
    gpkg = tmp_path / "minimal.gpkg"
    create_geopackage(gpkg)
    conn = sqlite3.connect(str(gpkg))
    count = write_wells_layer(
        conn, [{"Latitude": "34.1", "Longitude": "-118.4"}])
    conn.commit()
    rows = conn.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
    conn.close()
    assert count == 1
    assert rows == 1


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
