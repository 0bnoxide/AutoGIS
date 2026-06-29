# CreateBoringLogDatabase Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** CreateBoringLogDatabase (Tool 8.0a)
**Priority:** HIGH (Foundation) — the store boring-import/PDF tools write into
**Runtime:** CLI ✓ (SQLite, headless) / LOCAL ✓ (gdb via `.pyt`)

---

## Problem

Boring-log workflows (`ImportFieldBoringLogs` 8.0b, `GenerateBoringLogPDFs` 8.0c) need a
normalized store for boring locations, lithology intervals, samples, well construction,
groundwater observations, photos, and review comments. The **dataclasses already exist**
(`core/common/schema/boring.py`: `BoringLocation`, `LithologyInterval`, `BoringSample`,
`WellConstruction`, `GroundwaterObservation`, `BoringPhoto`, `BoringComment`) and
`upgrade-schema` (ADR-0018) ships the gdb tables — but there is no headless way to stand up
the database, so import/PDF tools can't be developed or tested without ArcGIS Pro.

---

## Approach

**Chosen:** Generate the schema from the existing `boring.py` dataclasses into two
back-ends from one definition:
- **SQLite (headless, stdlib `sqlite3`):** the arcpy-free path — `CREATE TABLE` per
  dataclass, with foreign keys to `BoringLocations`. Fully testable in CI; the boring
  import/PDF tools develop against this.
- **File geodatabase (arcpy, `.pyt`):** routes through `upgrade-schema`'s existing
  table-creation seam for the Pro path.

A single `boring_schema_ddl()` derives column names/types from the dataclasses, so the two
back-ends never drift and the schema has one source of truth.

**Rejected: a fresh schema definition.** The dataclasses are already canonical (ADR-0014);
this tool *materializes* them, it does not redefine them.

**Rejected: PostgreSQL in v1.** SQLite covers the headless/test need with zero deps; the
DDL generator can target Postgres later if a multi-user store is needed. (ponytail: add
the Postgres emitter when a second writer actually exists.)

---

## Architecture

```
autogis/
  core/common/schema/
    boring.py                 ← EXISTS (7 dataclasses = source of truth)
  core/envmon/
    boring_database.py        ← NEW (DDL generator + sqlite3 creator, arcpy-free)
  adapters/
    cli.py                    ← add create-boring-db command (headless sqlite)
    toolbox.pyt               ← gdb path via upgrade-schema seam
tests/envmon/
  test_boring_database.py     ← NEW (arcpy-free, in-memory sqlite)
```

---

## Public API (`boring_database.py`)

```python
def boring_schema_ddl(dialect: str = "sqlite") -> list[str]:
    """Emit CREATE TABLE statements for the 7 boring dataclasses, with FKs."""

@dataclass
class CreateDBResult:
    tables_created: list[str]
    db_path: Path
    qa: QACollector

def create_sqlite_boring_db(db_path: Path, *, overwrite: bool = False) -> CreateDBResult:
    """Create a SQLite boring-log database from the dataclass-derived DDL."""
```

Column types map from dataclass annotations (`str`→TEXT, `float`→REAL, `int`→INTEGER,
`bool`→INTEGER). `LithologyInterval`/`BoringSample`/etc. carry a `boring_id` FK to
`BoringLocations`.

---

## CLI Command

```
autogis envmon create-boring-db \
  --out <borings.sqlite> \
  [--overwrite] \
  [--report <create_qa.md>]
```

Headless (stdlib `sqlite3`). The gdb equivalent is the `.pyt` upgrade-schema tool.

---

## Test Strategy

`tests/envmon/test_boring_database.py` — arcpy-free, in-memory SQLite:

1. `boring_schema_ddl()` emits one CREATE TABLE per dataclass (7 tables).
2. Each child table has a `boring_id` foreign key to `BoringLocations`.
3. `create_sqlite_boring_db` produces a DB whose `sqlite_master` lists all 7 tables.
4. Column types map correctly from dataclass annotations.
5. `overwrite=False` against an existing file → QA error, no clobber.
6. A round-trip insert of a `BoringLocation` row succeeds against the created schema.
