# ADR-018: UpgradeEnvMonitoringGDBSchema tool design

**Status:** Accepted

**Date:** 2026-06-25

## Context

The Phase 4 fast-track tools (boring logs, survey/elevation, drone, dashboards) require 27 new GDB tables that do not exist in the current schema. The existing `create_or_update_gdb_schema()` in `gdb_schema.py` handles additive schema creation but is only called from `run_import` — there is no standalone tool to upgrade an existing site GDB, no version tracking, and no CLI command for schema administration.

Four design decisions were made during brainstorming:

1. **Version tracking** — whether to track schema versions at all, and how
2. **CLI invocation** — whether the command executes directly or stubs to the `.pyt` toolbox
3. **Table scope** — whether to add all 27 new tables at once or phase them
4. **Output format** — what the CLI prints when run

## Decisions

### 1. Lightweight version table (`Env_SchemaVersion`)

A single non-spatial table is added to `TABLE_SCHEMAS`. One row is appended per upgrade run:

| Field | Type | Notes |
|---|---|---|
| `SchemaVersion` | TEXT 16 | e.g. `"2.0"` |
| `UpgradedAt` | DATE | timestamp of run |
| `PreviousVersion` | TEXT 16 | `""` if first upgrade |
| `TablesCreated` | LONG | count of tables created this run |
| `FieldsAdded` | LONG | count of fields added to existing tables |
| `UpgradedBy` | TEXT 64 | `os.getlogin()` or `""` |
| `Notes` | TEXT 256 | optional |

Full migration scripts (Alembic-style) were rejected as overkill for a codebase where schema changes are infrequent and the existing function already handles idempotent-add.

### 2. New `upgrade_schema.py` module wraps `create_or_update_gdb_schema()` — not the other way

`TABLE_SCHEMAS` in `gdb_schema.py` is extended with all 28 new entries (27 domain tables + `Env_SchemaVersion`). `create_or_update_gdb_schema()` is not modified. A new `autogis/core/envmon/upgrade_schema.py` provides:

- `SCHEMA_VERSION = "2.0"`
- `TableUpgradeStatus(table_name, status, fields_added)` — status is `"CREATED"` | `"UPDATED"` | `"OK"`
- `UpgradeReport(gdb_path, previous_version, new_version, tables)`
- `upgrade_gdb_schema(gdb_path, spatial_reference=None) -> UpgradeReport` — pre-scans existing tables/fields, calls `create_or_update_gdb_schema()`, derives per-table status from the pre-scan (no post-scan needed since the function is additive-only and `TABLE_SCHEMAS` is the ground truth), writes `Env_SchemaVersion` row
- `format_report(report) -> str` — formats table-by-table output

The motivation for keeping `create_or_update_gdb_schema()` untouched: it is called by `run_import` on every import run with the caller's own `QACollector` passed in. Mixing upgrade-reporting logic into it would complicate a function with a stable, single-purpose contract.

### 3. Real CLI invocation — not a `.pyt` stub

`autogis envmon upgrade-schema <gdb>` calls `upgrade_gdb_schema()` directly after `_guard()`. The existing LOCAL tools (2-8) stub out at the CLI and redirect to the `.pyt` toolbox because they require full ArcGIS Pro session state (layouts, data frames, active maps). Schema administration needs only `arcpy.management` functions, which are available from any arcpy-licensed Python environment — a Pro session is not required.

### 4. All 27 new tables in a single version bump (v1 → v2)

All schemas are already fully defined in `schema/boring.py`, `schema/survey.py`, and `schema/drone.py` (a fourth module, `schema/dashboard.py`, was removed 2026-07-02 as orphaned dead code -- see ADR-0014's status update and issue #120). Adding them in one pass avoids noise from multiple partial-version bumps. No tool can write to a new table until the tool itself is built, so adding tables early has no operational downside.

### 5. Table-by-table output

CLI prints one line per table in `TABLE_SCHEMAS` order:
```
[CREATED] BoringLocations
[CREATED] LithologyIntervals
...
[OK]      Env_Samples
[UPDATED] Env_ImportBatch  (+1 field)
...
Schema upgraded v1.0 → v2.0: 27 tables created, 1 field added.
```

This is preferred over a one-line summary because schema upgrades are infrequent admin operations where verifying exactly what changed on each site GDB matters more than brevity.

## Consequences

### Positive consequences

- All 18 fast-track Phase 4 tools can write to GDB the moment they are built — no per-tool schema setup step
- Any GDB can be inspected for its schema version by querying `Env_SchemaVersion`
- `create_or_update_gdb_schema()` and `run_import` are unmodified — no regression risk to the existing import pipeline
- Schema upgrade is scriptable (CLI, no Pro GUI required) — supports batch-upgrading multiple site GDBs

### Negative consequences

- Adding new fields to an existing table requires manually keeping the `TABLE_SCHEMAS` entry and `create_import_batch` / `finalize_batch` explicit field lists in sync (pre-existing constraint, not introduced here)
- `Env_SchemaVersion` uses one row per run — querying the current version requires `MAX(UpgradedAt)` rather than a single-row lookup

## Alternatives considered

1. **Extend `create_or_update_gdb_schema()` in place:** Rejected — mixes upgrade-reporting concerns into a function with a stable, single-call contract in `run_import`.

2. **Full migration scripts (Alembic-style):** Rejected — significant design overhead; the additive-only constraint makes discrete up/down migrations unnecessary.

3. **`.pyt` stub at CLI:** Rejected — schema admin does not require a full Pro session; real CLI invocation adds scriptability with no downside.

4. **Phased table additions (one version bump per tool group):** Rejected — schemas are fully designed; partial version bumps add noise without benefit.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — `upgrade_schema.py` types are arcpy-free; arcpy only in `upgrade_gdb_schema()` body
- [ADR-014: Schema dataclass package](0014-schema-dataclass-package.md) — the 27 new tables in this ADR correspond to the dataclasses defined there
- [ADR-009: Config dataclass style](0009-config-dataclass-style.md) — `TableUpgradeStatus` and `UpgradeReport` follow the same dataclass pattern
