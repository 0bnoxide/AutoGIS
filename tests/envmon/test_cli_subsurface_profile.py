"""CLI tests for envmon generate-subsurface-profile command."""
import sqlite3

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.schema.boring import BoringLocation, LithologyInterval
from autogis.core.common.sqlite_schema import insert_rows
from autogis.core.envmon.create_boring_log_database import create_boring_log_database


def _seed_db(tmp_path):
    db = tmp_path / "borings.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    try:
        insert_rows(conn, BoringLocation, [
            BoringLocation(boring_id="B-A", site_id="H281", location_type="boring",
                           northing=0.0, easting=0.0, ground_elevation=100.0,
                           toc_elevation=None, status="logged").to_row(),
            BoringLocation(boring_id="B-B", site_id="H281", location_type="boring",
                           northing=100.0, easting=0.0, ground_elevation=95.0,
                           toc_elevation=None, status="logged").to_row(),
        ])
        insert_rows(conn, LithologyInterval, [
            LithologyInterval(boring_id="B-A", top_depth=0.0, bottom_depth=5.0,
                              uscs="CL").to_row(),
        ])
        conn.commit()
    finally:
        conn.close()
    return db


def test_generate_subsurface_profile_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-subsurface-profile" in result.output


def test_generate_subsurface_profile_requires_endpoints(tmp_path):
    db = _seed_db(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-subsurface-profile", str(db),
        "--out", str(tmp_path / "profile.png"),
    ])
    assert result.exit_code != 0
    assert "Specify profile endpoints" in result.output


def test_generate_subsurface_profile_renders(tmp_path):
    pytest.importorskip("matplotlib")
    db = _seed_db(tmp_path)
    out = tmp_path / "profile.png"
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-subsurface-profile", str(db),
        "--boring-a", "B-A", "--boring-b", "B-B", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "2 boring" in result.output


def test_generate_subsurface_profile_unknown_boring_is_clean_error(tmp_path):
    db = _seed_db(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "generate-subsurface-profile", str(db),
        "--boring-a", "B-X", "--boring-b", "B-B",
        "--out", str(tmp_path / "profile.png"),
    ])
    assert result.exit_code != 0
    assert "B-X" in result.output
