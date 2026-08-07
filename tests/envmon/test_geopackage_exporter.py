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


# ── issue #416: OGC Requirement 11 mandatory SRS rows ─────────────────────

def test_mandatory_undefined_srs_rows_are_present(tmp_path):
    """OGC GeoPackage Requirement 11 needs the undefined cartesian (-1) and
    undefined geographic (0) rows in every GeoPackage, not just the active
    SRS."""
    gpkg = tmp_path / "t.gpkg"
    create_geopackage(gpkg)
    conn = sqlite3.connect(str(gpkg))
    rows = conn.execute(
        "SELECT srs_id, organization, organization_coordsys_id, definition "
        "FROM gpkg_spatial_ref_sys ORDER BY srs_id").fetchall()
    conn.close()
    assert [r[0] for r in rows] == [-1, 0, 4326]
    assert rows[0][1:] == ("NONE", -1, "undefined")
    assert rows[1][1:] == ("NONE", 0, "undefined")


# ── issue #419: custom srs_id was accepted but never propagated ───────────

def test_custom_srs_id_is_rejected_not_silently_mislabelled(tmp_path):
    """create_geopackage advertised an arbitrary srs_id while writing WGS84
    WKT, WGS84 lat/lon geometry, and a wells layer registered as 4326."""
    with pytest.raises(ValueError) as exc:
        create_geopackage(tmp_path / "t.gpkg", srs_id=26911)
    assert "26911" in str(exc.value) and "4326" in str(exc.value)
    assert not (tmp_path / "t.gpkg").exists()


def test_srs_is_consistent_across_container_and_wells_metadata(tmp_path):
    """Every SRS registration and the embedded GeoPackageBinary header must
    agree -- the constraint above is what makes that guaranteed."""
    gpkg = tmp_path / "t.gpkg"
    create_geopackage(gpkg)
    conn = sqlite3.connect(str(gpkg))
    write_wells_layer(conn, [{"Latitude": "34.05", "Longitude": "-118.24"}])
    conn.commit()
    contents_srs = conn.execute(
        "SELECT srs_id FROM gpkg_contents WHERE table_name='wells'").fetchone()[0]
    geom_srs = conn.execute(
        "SELECT srs_id FROM gpkg_geometry_columns WHERE table_name='wells'"
    ).fetchone()[0]
    blob = conn.execute("SELECT geom FROM wells").fetchone()[0]
    conn.close()
    header_srs = struct.unpack("<2sBBi", blob[:8])[3]
    assert contents_srs == geom_srs == header_srs == 4326
    # ... and that SRS actually has a row in the container.
    conn = sqlite3.connect(str(gpkg))
    assert conn.execute(
        "SELECT COUNT(*) FROM gpkg_spatial_ref_sys WHERE srs_id=?",
        (header_srs,)).fetchone()[0] == 1
    conn.close()


# ── issue #417: nonnumeric coordinates were dropped with no QA record ─────

def test_nonnumeric_coordinates_are_reported_in_qa(tmp_path):
    """A non-empty but unparseable coordinate is truthy, so missing_coords
    stayed 0 while write_wells_layer skipped the row -- the export reported
    success with fewer wells than supplied and no explanation."""
    wells = [
        {"WellID": "MW-1", "Latitude": "34.05", "Longitude": "-118.24"},
        {"WellID": "MW-2", "Latitude": "not-a-number", "Longitude": "-118.4"},
        {"WellID": "MW-3", "Latitude": "", "Longitude": "-118.4"},
    ]
    result = export_env_data_geopackage(wells, [], tmp_path / "t.gpkg")
    codes = [r.category for r in result.qa.records]
    assert "invalid_coords" in codes and "missing_coords" in codes
    assert result.well_count == 1
    # Every supplied well is accounted for: written, missing, or invalid.
    skipped = sum(1 for r in result.qa.records
                  if r.category in ("missing_coords", "invalid_coords"))
    assert skipped == 2


def test_zero_coordinates_are_written_not_reported_as_missing(tmp_path):
    """A well on the equator/prime meridian is a real location -- the old
    truthiness test called it missing while the row was written."""
    wells = [{"WellID": "MW-0", "Latitude": 0, "Longitude": 0}]
    result = export_env_data_geopackage(wells, [], tmp_path / "t.gpkg")
    assert result.well_count == 1
    assert "missing_coords" not in [r.category for r in result.qa.records]
