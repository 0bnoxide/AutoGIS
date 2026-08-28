"""create_boring_log_database.py — Tool 8.0a CreateBoringLogDatabase (headless).

Creates the normalized boring-log SQLite database: one table per
``core/common/schema/boring.py`` dataclass (the same seven consumed by the
8.0b import side), columns derived programmatically from the dataclass fields
via ``common/sqlite_schema.py`` — the schema is never hand-written twice.
Also validates an existing database against that expected schema.

Stdlib sqlite3 only (same pattern as ``geopackage_exporter.py``). Arcpy-free.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING
from ..common.schema.boring import (
    BoringComment, BoringLocation, BoringPhoto, BoringSample,
    GroundwaterObservation, LithologyInterval, WellConstruction,
)
from ..common.sqlite_schema import create_table_sql, sqlite_columns

#: All boring-domain tables, roadmap §8.0a. Order matters only for readability.
BORING_TABLES = (
    BoringLocation, LithologyInterval, BoringSample, WellConstruction,
    GroundwaterObservation, BoringPhoto, BoringComment,
)


def create_boring_log_database(
    db_path: Path, *, overwrite: bool = False,
    qa: Optional[QACollector] = None,
) -> Path:
    """Create the boring-log SQLite database with all seven schema tables."""
    if qa is None:
        qa = QACollector()
    p = Path(db_path)
    if p.exists():
        if not overwrite:
            qa.add(SEV_ERROR, "file_exists",
                   f"{p} already exists. Use --overwrite to replace it.")
            raise FileExistsError(f"{p} already exists.")
        p.unlink()
    if p.parent != Path("."):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        for dc in BORING_TABLES:
            conn.execute(create_table_sql(dc))
        conn.commit()
    finally:
        conn.close()
    qa.add(SEV_INFO, "database_created",
           f"Created {len(BORING_TABLES)} boring-log tables -> {p}")
    return p


def validate_boring_log_database(db_path: Path, qa: QACollector) -> None:
    """Check an existing DB's tables/columns against the expected schema."""
    p = Path(db_path)
    if not p.exists():
        qa.add(SEV_ERROR, "db_missing", f"Database not found: {p}")
        return
    conn = sqlite3.connect(str(p))
    try:
        for dc in BORING_TABLES:
            # table_name is a code constant (ClassVar), not user input.
            try:
                info = conn.execute(
                    f'PRAGMA table_info("{dc.table_name}")').fetchall()
            except sqlite3.DatabaseError as exc:
                # Corrupt or non-SQLite file: a QA error, not a traceback (#512).
                qa.add(SEV_ERROR, "db_unreadable",
                       f"Not a readable SQLite database: {p} ({exc})")
                return
            if not info:
                qa.add(SEV_ERROR, "missing_table",
                       f"Table {dc.table_name} not found.")
                continue
            actual = {r[1]: (r[2] or "").upper() for r in info}
            expected = sqlite_columns(dc)
            for name, sqltype in expected:
                if name not in actual:
                    qa.add(SEV_ERROR, "missing_column",
                           f"{dc.table_name}.{name} is missing.")
                elif actual[name] != sqltype:
                    qa.add(SEV_ERROR, "column_type_mismatch",
                           f"{dc.table_name}.{name}: expected {sqltype}, "
                           f"found {actual[name] or '(untyped)'}.")
            known = {n for n, _ in expected} | {"id"}
            for extra in sorted(set(actual) - known):
                qa.add(SEV_WARNING, "unexpected_column",
                       f"{dc.table_name}.{extra} is not in the expected schema.")
    finally:
        conn.close()
    qa.add(SEV_INFO, "validation_complete",
           f"Checked {len(BORING_TABLES)} expected tables in {p}.")
