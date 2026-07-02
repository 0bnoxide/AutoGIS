# ADR-0033 — Foundation-completion batch (2026-07-01): CreateBoringLogDatabase
+ SyncFieldAttachments envmon-side index

**Status:** Accepted
**Date:** 2026-07-01
**Deciders:** Greg / Claude Code
**Related:** ADR-0002 (arcpy-free core), ADR-0014 (schema dataclass package),
ADR-0032 (headless tools batch 2026-07-01)

---

## Context

Two roadmap tools sat in the README's "Foundation laid" bucket:

- **CreateBoringLogDatabase (8.0a):** `schema/boring.py` shipped 7 dataclasses
  and the 8.0b import side consumes them, but nothing scaffolds the normalized
  DB from scratch.
- **SyncFieldAttachments (6.5):** the AGOL download half is the fully-shipped
  attachment harvester (`core/harvest/` — untouched here), but envmon had no
  attachment table at all, so no envmon tool could join records to their
  harvested attachments.

Both halves are headless (Local ✓ / CLI ✓ / AGOL ✗) — no arcpy, no live AGOL
call — and were shipped together as one batch per repo convention.

## Decision

1. **`core/common/sqlite_schema.py`** — one small shared helper that derives
   SQLite DDL and inserts from any `core/common/schema` dataclass
   (`sqlite_columns` / `create_table_sql` / `insert_rows`, via
   `typing.get_type_hints`). The schema is defined once, in the dataclass;
   both new tools consume it. Types: str→TEXT, float→REAL, int/bool→INTEGER,
   date/datetime→ISO-8601 TEXT; every table gets a surrogate
   `id INTEGER PRIMARY KEY AUTOINCREMENT` (same stdlib-sqlite3 pattern as
   `geopackage_exporter.py`).
2. **CreateBoringLogDatabase** — `envmon create-boring-log-db`
   → `core/envmon/create_boring_log_database.py`. Creates one SQLite table per
   `schema/boring.py` dataclass (`BORING_TABLES`, all 7). `--validate` checks
   an existing DB against the derived schema instead: missing table/column and
   declared-type mismatch are `SEV_ERROR`; unexpected extra columns are
   `SEV_WARNING`. SQLite chosen over GDB/PostgreSQL (roadmap offered all
   three): headless, CI-able, zero new dependencies; the GDB path already
   exists via `upgrade-schema` + `import-boring-logs`.
3. **SyncFieldAttachments (envmon-side half only)** —
   `envmon index-field-attachments`
   → `core/envmon/index_field_attachments.py` + new
   `core/common/schema/attachments.py` (`AttachmentIndex`, table
   `AttachmentIndex`). Reads a harvester manifest (CSV or JSON, both already
   written by `harvest.manifest.Manifest.write`), maps
   `AttachmentResult` fields (objectid→related_id, source_table→related_table,
   saved_path→local_path, …), classifies attachment_type from the file
   extension, QA-gates (a "downloaded" row with no local path is
   `SEV_ERROR`), and persists to any SQLite DB via the shared helper
   (`--replace` truncates first for re-index). The AGOL download half was
   **not** rebuilt — that is the harvester's job.

Both commands are registered `Runtime.CLOUD` in
`autogis/runtime/capabilities.py` (+ `_REGISTRY_SEED` discovery rows), use the
established `QACollector` + `qa_report_options`/`_render_qa` CLI contract, and
ship with 24 tests (unit + CLI end-to-end against real `Manifest` output).
Suite: 1136 → 1160, green.

## Consequences

### Positive

- 8.0a and 6.5 leave "Foundation laid"; the boring-log domain now has a
  create → validate → import lifecycle, and envmon tools can join against
  harvested attachments for the first time.
- Column definitions can never drift from `schema/boring.py` — they are
  derived, not duplicated.
- `sqlite_schema.py` gives future tools a one-liner for "persist these schema
  dataclasses to SQLite".

### Negative

- The SQLite DB is a plain normalized store, not a GeoPackage — no spatial
  layer for `BoringLocations` (coordinates are plain REAL columns). Wrap via
  `geopackage_exporter` if a spatial view is ever needed.
- No foreign-key constraints between the boring tables (validation of
  cross-references stays in `validate_boring_package`, matching the existing
  import-side split).
- `AttachmentIndex.related_table` is only as good as the manifest's
  `source_table` (a reserved provenance column, ADR-0012); the
  `--related-table` CLI fallback covers manifests that predate it.

## Alternatives considered

- **Hand-written CREATE TABLE statements** (as in `geopackage_exporter.py`):
  rejected — the schema would exist twice (dataclass + DDL) and drift.
- **CSV persistence for the attachment index** (as `source_registry.py`):
  rejected — the index exists specifically for joins against other envmon
  tables; SQLite makes that a query instead of a client-side merge, and the
  helper needed for tool 8.0a made it free.
- **Rebuilding attachment download inside envmon:** rejected outright — the
  harvester is a separate, fully-shipped domain (task scope and ADR-0001
  separation).

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0014: schema dataclass package](0014-schema-dataclass-package.md)
- [ADR-0032: headless tools batch 2026-07-01](0032-headless-tools-batch-2026-07-01.md)
