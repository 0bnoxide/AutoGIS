"""Tests for autogis/core/envmon/subsurface_profile.py (headless)."""
import sqlite3

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.boring import BoringLocation, LithologyInterval
from autogis.core.common.sqlite_schema import insert_rows
from autogis.core.envmon.create_boring_log_database import create_boring_log_database
from autogis.core.envmon.subsurface_profile import (
    build_profile, place_borings, project_onto_line, resolve_endpoints,
)


def _loc(boring_id, northing, easting, ground_elevation=100.0):
    return BoringLocation(
        boring_id=boring_id, site_id="H281", location_type="boring",
        northing=northing, easting=easting, ground_elevation=ground_elevation,
        toc_elevation=None, status="logged",
    ).to_row()


def _seed_db(tmp_path, locations, lithology=()):
    db = tmp_path / "borings.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    try:
        insert_rows(conn, BoringLocation, locations)
        if lithology:
            insert_rows(conn, LithologyInterval, lithology)
        conn.commit()
    finally:
        conn.close()
    return db


# ---- project_onto_line -------------------------------------------------------

def test_project_onto_line_station_and_offset():
    a, b = (0.0, 0.0), (100.0, 0.0)
    station, offset = project_onto_line((50.0, 10.0), a, b)
    assert station == pytest.approx(50.0)
    assert abs(offset) == pytest.approx(10.0)


def test_project_onto_line_on_the_line_has_zero_offset():
    a, b = (0.0, 0.0), (100.0, 0.0)
    station, offset = project_onto_line((30.0, 0.0), a, b)
    assert station == pytest.approx(30.0)
    assert offset == pytest.approx(0.0)


def test_project_onto_line_rejects_coincident_endpoints():
    with pytest.raises(ValueError, match="coincident"):
        project_onto_line((1.0, 1.0), (5.0, 5.0), (5.0, 5.0))


# ---- resolve_endpoints --------------------------------------------------------

def test_resolve_endpoints_by_coords():
    a, b = resolve_endpoints({}, start=(0.0, 0.0), end=(100.0, 0.0))
    assert (a, b) == ((0.0, 0.0), (100.0, 0.0))


def test_resolve_endpoints_by_boring_ids():
    locations = {"B-A": {"location": {"northing": 0.0, "easting": 0.0}},
                 "B-B": {"location": {"northing": 100.0, "easting": 0.0}}}
    a, b = resolve_endpoints(locations, boring_a="B-A", boring_b="B-B")
    assert (a, b) == ((0.0, 0.0), (100.0, 0.0))


def test_resolve_endpoints_rejects_mixed_modes():
    with pytest.raises(ValueError, match="not both"):
        resolve_endpoints({}, boring_a="B-A", start=(0.0, 0.0))


def test_resolve_endpoints_rejects_unknown_boring():
    with pytest.raises(ValueError, match="B-X"):
        resolve_endpoints({}, boring_a="B-X", boring_b="B-Y")


def test_resolve_endpoints_requires_a_mode():
    with pytest.raises(ValueError, match="Specify profile endpoints"):
        resolve_endpoints({})


# ---- place_borings -------------------------------------------------------------

def test_place_borings_keeps_within_tolerance_and_sorts_by_station():
    locations = {
        "B-1": {"location": {"northing": 50.0, "easting": 10.0}, "lithology": []},
        "B-2": {"location": {"northing": 20.0, "easting": 0.0}, "lithology": []},
    }
    placements = place_borings(locations, (0.0, 0.0), (100.0, 0.0), tolerance_ft=50.0)
    assert [p.boring_id for p in placements] == ["B-2", "B-1"]


def test_place_borings_excludes_beyond_tolerance_with_qa_warning():
    locations = {
        "B-1": {"location": {"northing": 50.0, "easting": 10.0}, "lithology": []},
        "B-2": {"location": {"northing": 50.0, "easting": 999.0}, "lithology": []},
    }
    qa = QACollector()
    placements = place_borings(locations, (0.0, 0.0), (100.0, 0.0),
                                tolerance_ft=50.0, qa=qa)
    assert [p.boring_id for p in placements] == ["B-1"]
    warning = next(r for r in qa.records if r.category == "boring_outside_tolerance")
    assert "B-2" in warning.message


def test_place_borings_skips_borings_missing_coordinates():
    locations = {"B-1": {"location": {"northing": None, "easting": None},
                         "lithology": []}}
    placements = place_borings(locations, (0.0, 0.0), (100.0, 0.0), tolerance_ft=50.0)
    assert placements == []


# ---- build_profile (end-to-end against the SQLite DB) --------------------------

def test_build_profile_end_to_end(tmp_path):
    locations = [_loc("B-A", 0.0, 0.0), _loc("B-B", 100.0, 0.0),
                 _loc("B-MID", 50.0, 5.0)]
    lithology = [LithologyInterval(boring_id="B-MID", top_depth=0.0,
                                    bottom_depth=5.0, uscs="CL").to_row()]
    db = _seed_db(tmp_path, locations, lithology)
    placements = build_profile(db, boring_a="B-A", boring_b="B-B",
                                tolerance_ft=50.0)
    assert [p.boring_id for p in placements] == ["B-A", "B-MID", "B-B"]
    mid = next(p for p in placements if p.boring_id == "B-MID")
    assert mid.station_ft == pytest.approx(50.0)
    assert len(mid.lithology) == 1
