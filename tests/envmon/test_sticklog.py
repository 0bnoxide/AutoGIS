"""Tests for autogis/core/envmon/sticklog.py and the gen-sticklogs CLI."""
import sqlite3

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector
from autogis.core.common.schema.boring import (
    BoringLocation, GroundwaterObservation, LithologyInterval)
from autogis.core.common.sqlite_schema import insert_rows
from autogis.core.envmon.create_boring_log_database import create_boring_log_database
from autogis.core.envmon.sticklog import generate_sticklogs, render_sticklog


def _loc(boring_id, total_depth_ft=None):
    return BoringLocation(
        boring_id=boring_id, site_id="H281", location_type="boring",
        northing=0.0, easting=0.0, ground_elevation=100.0,
        toc_elevation=None, status="logged", total_depth_ft=total_depth_ft,
    ).to_row()


def _seed_db(tmp_path):
    db = tmp_path / "borings.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    try:
        insert_rows(conn, BoringLocation, [_loc("B-1"), _loc("B-EMPTY")])
        insert_rows(conn, LithologyInterval, [
            LithologyInterval(boring_id="B-1", top_depth=0.0, bottom_depth=5.0,
                              uscs="CL", primary_material="clay").to_row(),
            LithologyInterval(boring_id="B-1", top_depth=5.0, bottom_depth=12.0,
                              uscs="SM", description="silty sand").to_row(),
        ])
        insert_rows(conn, GroundwaterObservation, [
            GroundwaterObservation(boring_id="B-1", observation_datetime=None,
                                   depth_to_water=8.5).to_row(),
        ])
        conn.commit()
    finally:
        conn.close()
    return db


# ---- render_sticklog ---------------------------------------------------------

def test_render_sticklog_writes_figure(tmp_path):
    pytest.importorskip("matplotlib")
    bundle = {
        "location": {"site_id": "H281", "total_depth_ft": 15.0},
        "lithology": [{"top_depth": 0.0, "bottom_depth": 5.0, "uscs": "CL",
                       "primary_material": "clay", "description": ""}],
        "groundwater": [{"depth_to_water": 3.0}],
    }
    out = render_sticklog("B-1", bundle, tmp_path / "stick.png")
    assert out is not None and out.exists()


def test_render_sticklog_skips_boring_without_lithology(tmp_path):
    pytest.importorskip("matplotlib")
    qa = QACollector()
    out = render_sticklog("B-EMPTY", {"location": {}, "lithology": []},
                          tmp_path / "stick.png", qa=qa)
    assert out is None
    assert not (tmp_path / "stick.png").exists()
    warning = next(r for r in qa.records if r.category == "sticklog_no_lithology")
    assert "B-EMPTY" in warning.message


def test_generate_sticklogs_end_to_end(tmp_path):
    pytest.importorskip("matplotlib")
    db = _seed_db(tmp_path)
    qa = QACollector()
    paths = generate_sticklogs(db, tmp_path / "out", qa=qa)
    assert [p.name for p in paths] == ["sticklog_B-1.png"]
    assert all(p.exists() for p in paths)
    # B-EMPTY has a location but no lithology -> warned, not rendered
    warning = next(r for r in qa.records if r.category == "sticklog_no_lithology")
    assert "B-EMPTY" in warning.message


# ---- CLI ----------------------------------------------------------------------

def test_gen_sticklogs_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "gen-sticklogs" in result.output


def test_gen_sticklogs_cli_renders(tmp_path):
    pytest.importorskip("matplotlib")
    db = _seed_db(tmp_path)
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-sticklogs", "--db", str(db), "--out-dir", str(out_dir),
        "--borings", "B-1",
    ])
    assert result.exit_code == 0, result.output
    assert (out_dir / "sticklog_B-1.png").exists()
    assert "1 sticklog" in result.output


def test_gen_sticklogs_cli_no_matching_borings_fails(tmp_path):
    pytest.importorskip("matplotlib")
    db = _seed_db(tmp_path)
    result = CliRunner().invoke(autogis, [
        "envmon", "gen-sticklogs", "--db", str(db),
        "--out-dir", str(tmp_path / "out"), "--borings", "B-X",
    ])
    assert result.exit_code == 1
    assert "no_sticklogs" in result.output
