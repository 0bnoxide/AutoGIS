"""Tests for autogis/core/envmon/create_boring_log_database.py (tool 8.0a)."""
import sqlite3
from datetime import date

import pytest

from autogis.core.common.qa import QACollector, SEV_ERROR
from autogis.core.common.schema.boring import BoringLocation
from autogis.core.common.sqlite_schema import insert_rows, sqlite_columns
from autogis.core.envmon.create_boring_log_database import (
    BORING_TABLES,
    create_boring_log_database,
    validate_boring_log_database,
)

EXPECTED_TABLES = {
    "BoringLocations", "LithologyIntervals", "BoringSamples",
    "WellConstruction", "GroundwaterObservations", "BoringPhotos",
    "BoringComments",
}


def _table_names(db):
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


def _errors(qa):
    return [r for r in qa.records if r.severity == SEV_ERROR]


def test_create_makes_all_seven_tables(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    assert _table_names(db) == EXPECTED_TABLES
    assert len(BORING_TABLES) == 7


def test_columns_derived_from_dataclass(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    try:
        info = {r[1]: r[2] for r in
                conn.execute('PRAGMA table_info("BoringLocations")')}
    finally:
        conn.close()
    assert info["boring_id"] == "TEXT"
    assert info["ground_elevation"] == "REAL"       # Optional[float] -> REAL
    assert info["drilling_start_date"] == "TEXT"    # date -> ISO TEXT
    assert info["id"] == "INTEGER"                  # surrogate key
    # every dataclass field is present
    for name, _ in sqlite_columns(BoringLocation):
        assert name in info


def test_create_existing_raises_without_overwrite(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    qa = QACollector()
    with pytest.raises(FileExistsError):
        create_boring_log_database(db, qa=qa)
    assert any(r.category == "file_exists" for r in _errors(qa))


def test_create_overwrite_replaces(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE leftover (x TEXT)")
    conn.commit()
    conn.close()
    create_boring_log_database(db, overwrite=True)
    assert "leftover" not in _table_names(db)


def test_created_db_validates_clean(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    qa = QACollector()
    validate_boring_log_database(db, qa)
    assert not _errors(qa)


def test_validate_missing_db_errors(tmp_path):
    qa = QACollector()
    validate_boring_log_database(tmp_path / "nope.sqlite", qa)
    assert any(r.category == "db_missing" for r in _errors(qa))


def test_validate_non_sqlite_file_is_qa_error_not_traceback(tmp_path):
    db = tmp_path / "bogus.sqlite"
    db.write_text("not a database", encoding="utf-8")
    qa = QACollector()
    validate_boring_log_database(db, qa)  # must not raise (#512)
    assert any(r.category == "db_unreadable" for r in _errors(qa))
    # validation did NOT complete -- no false all-clear alongside the error
    assert not any(r.category == "validation_complete" for r in qa.records)


def test_validate_truncated_db_is_qa_error(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    raw = db.read_bytes()
    db.write_bytes(raw[:len(raw) // 3])
    qa = QACollector()
    validate_boring_log_database(db, qa)
    assert any(r.category == "db_unreadable" for r in _errors(qa))


def test_validate_unopenable_path_is_qa_error(tmp_path):
    # A directory exists() but cannot be opened: sqlite3.connect raises here,
    # not the PRAGMA. The CLI's click.Path(dir_okay=False) rejects this first;
    # library callers of the core function have no such guard.
    d = tmp_path / "adir.sqlite"
    d.mkdir()
    qa = QACollector()
    validate_boring_log_database(d, qa)  # must not raise
    assert any(r.category == "db_unreadable" for r in _errors(qa))


def test_validate_missing_table_errors(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    conn.execute('DROP TABLE "BoringPhotos"')
    conn.commit()
    conn.close()
    qa = QACollector()
    validate_boring_log_database(db, qa)
    assert any(r.category == "missing_table" and "BoringPhotos" in r.message
               for r in _errors(qa))


def test_validate_missing_column_and_type_mismatch(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    conn = sqlite3.connect(str(db))
    conn.execute('ALTER TABLE "BoringLocations" DROP COLUMN "driller"')
    conn.execute('DROP TABLE "WellConstruction"')
    conn.execute('CREATE TABLE "WellConstruction" '
                 '(id INTEGER PRIMARY KEY, boring_id TEXT, '
                 'component_type TEXT, top_depth REAL, bottom_depth REAL, '
                 'diameter TEXT, material TEXT, slot_size TEXT, notes TEXT)')
    conn.commit()
    conn.close()
    qa = QACollector()
    validate_boring_log_database(db, qa)
    cats = {r.category for r in _errors(qa)}
    assert "missing_column" in cats
    assert "column_type_mismatch" in cats  # diameter TEXT, expected REAL


def test_insert_rows_roundtrip_encodes_dates(tmp_path):
    db = tmp_path / "boring.sqlite"
    create_boring_log_database(db)
    loc = BoringLocation(
        boring_id="B-1", site_id="H281", location_type="boring",
        northing=100.0, easting=200.0, ground_elevation=12.5,
        toc_elevation=None, status="logged",
        drilling_start_date=date(2026, 6, 1),
    )
    conn = sqlite3.connect(str(db))
    try:
        n = insert_rows(conn, BoringLocation, [loc])
        conn.commit()
        row = conn.execute(
            'SELECT boring_id, ground_elevation, drilling_start_date '
            'FROM "BoringLocations"').fetchone()
    finally:
        conn.close()
    assert n == 1
    assert row == ("B-1", 12.5, "2026-06-01")
