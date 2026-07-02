"""sqlite_schema.py — derive SQLite DDL and row inserts from schema dataclasses.

One home for the "one table per ``core/common/schema`` dataclass" convention:
columns are derived programmatically from the dataclass fields (never
hand-written twice). Stdlib only (same sqlite3 pattern as
``envmon/geopackage_exporter.py``). Arcpy-free.
"""
from __future__ import annotations

import types
from dataclasses import fields
from datetime import date, datetime
from typing import Union, get_args, get_origin, get_type_hints

# bool before int would not matter here (dict lookup is exact), but note that
# date/datetime are stored as ISO-8601 TEXT — SQLite has no native temporal type.
_TYPE_MAP = {str: "TEXT", float: "REAL", int: "INTEGER", bool: "INTEGER",
             date: "TEXT", datetime: "TEXT"}


def _unwrap_optional(t):
    if get_origin(t) in (Union, types.UnionType):
        args = [a for a in get_args(t) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return t


def sqlite_columns(dc) -> list[tuple[str, str]]:
    """(column_name, sqlite_type) per dataclass field, in declaration order."""
    hints = get_type_hints(dc)  # resolves `from __future__ import annotations`
    return [(f.name, _TYPE_MAP.get(_unwrap_optional(hints[f.name]), "TEXT"))
            for f in fields(dc)]


def create_table_sql(dc) -> str:
    """CREATE TABLE IF NOT EXISTS for *dc* (needs a ``table_name`` ClassVar)."""
    cols = ", ".join(f'"{n}" {t}' for n, t in sqlite_columns(dc))
    return (f'CREATE TABLE IF NOT EXISTS "{dc.table_name}" '
            f"(id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})")


def _encode(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def insert_rows(conn, dc, rows) -> int:
    """Insert dataclass instances (or dicts) into *dc*'s table. Returns count."""
    names = [f.name for f in fields(dc)]
    col_sql = ", ".join(f'"{n}"' for n in names)
    ph = ", ".join("?" for _ in names)
    sql = f'INSERT INTO "{dc.table_name}" ({col_sql}) VALUES ({ph})'
    n = 0
    for r in rows:
        d = r.to_row() if hasattr(r, "to_row") else dict(r)
        conn.execute(sql, [_encode(d.get(c)) for c in names])
        n += 1
    return n
