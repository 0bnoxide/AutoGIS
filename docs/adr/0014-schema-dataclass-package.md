# ADR-014: Domain-split dataclass schema package for envmon tables

**Status:** Accepted (dashboard.py removed — see below)

**Date:** 2026-06-25

## Status update (2026-07-02)

`schema/dashboard.py`'s 10 `Dash*` dataclasses were removed as orphaned dead
code (issue #120): zero importers anywhere in the repo, and the already-shipped
`BuildDashboardDataMart` (§6.7, `dashboard_data_mart.py`) never imported them
either — it defines its own inline row structures instead. The package is now
five domain modules, not six; everything else in this ADR (the `table_name`/
`to_row()` contract, the four remaining domains) stands.

## Context

The Phase 1-4 roadmap introduces ~27 new database tables across four domains: environmental monitoring (Env_Samples, Env_AnalyticalResults, etc.), boring logs (BoringLocations, LithologyIntervals, etc.), field survey (SurveyPoints_Raw/QA, LevelLoopRuns, ElevationHistory, etc.), drone operations (DroneFlights, DroneControlPoints, etc.), and dashboard data marts (Dash_SiteStatus, Dash_WellStatus, etc.).

Each fast-track tool needs to write rows into these tables. Without a shared schema layer, every tool would define its own dict structure, with no contract on field names, types, or table names.

## Decision

Add `autogis/core/common/schema/` — a pure-Python dataclass package that defines all 27 tables as `@dataclass` classes split across five domain modules:

- `schema/envmon.py` — Env_* tables
- `schema/boring.py` — boring log tables
- `schema/survey.py` — survey, level loop, and elevation history tables
- `schema/drone.py` — drone flight and product tables
- `schema/dashboard.py` — Dash_* mart tables
- `schema/__init__.py` — re-exports all dataclasses

Every dataclass exposes two interfaces:
- `table_name: ClassVar[str]` — canonical GDB/AGOL table name
- `to_row() -> dict` — serializes all fields for CSV/GDB/AGOL write

No arcpy, no GIS objects, no external dependencies. Safe to import without an ArcGIS Pro license.

## Consequences

### Positive consequences

- Single source of truth for table names and field names — tools don't hard-code strings
- `to_row()` contract makes it trivial to write to CSV, GDB cursors, or AGOL feature service rows
- Arcpy-free layer means all fast-track tools can be unit-tested without a license
- Domain split keeps each module small and independently readable
- `ClassVar[str] table_name` makes table-name lookups discoverable (grep-friendly)

### Negative consequences

- Adding a new field to a table requires editing the schema dataclass *and* any GDB migration scripts — two places to change
- `asdict()` serializes `date`/`datetime` objects as-is; callers that write to ArcGIS must convert to strings or `datetime` depending on cursor type
- `SurveyPointQA.qa_flags` is a `list` serialized to JSON string in `to_row()` — a leaky abstraction that callers must be aware of

## Alternatives considered

1. **Raw dicts per tool:** Each tool defines its own field names.
   - **Rejected:** No shared contract; field name typos silently produce bad data; can't grep for table name usage.

2. **SQLAlchemy ORM models:** Full ORM with declarative base.
   - **Rejected:** Overkill; introduces a heavy dependency; doesn't map cleanly to ArcGIS GDB cursors or AGOL feature service rows.

3. **Single flat `schema.py`:** All 27 tables in one file.
   - **Rejected:** File would be ~600 lines; domain separation is clearer for navigation and review.

4. **TypedDict instead of dataclass:** `TypedDict` for lightweight type hints.
   - **Rejected:** No `to_row()` method, no `ClassVar` table name, no default values — less ergonomic for tool authors.

## Related decisions

- [ADR-009: Config dataclass style](0009-config-dataclass-style.md) — same dataclass pattern used in HarvestConfig/EnvMonConfig
- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — schema/ upholds this invariant
- [ADR-015: npg/ absorbed-in-place vendoring](0015-npg-vendoring-pattern.md)
