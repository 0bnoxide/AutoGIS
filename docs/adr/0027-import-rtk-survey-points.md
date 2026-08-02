# ADR-0027 — ImportRTKSurveyPoints: configurable-column CSV parser + two-table GDB write

**Status:** Accepted
**Date:** 2026-06-28
**Deciders:** Greg / Claude Code
**Related:** ADR-0002 (arcpy-free core), ADR-0014 (schema-dataclass package),
ADR-0018 (upgrade-schema)

---

## Context

RTK (Real-Time Kinematic) GPS surveys produce CSV/TXT exports whose column
names vary by instrument vendor and field crew convention.  Survey data must be
ingested into the site GDB alongside other spatial measurements, with a QA pass
that flags points with poor horizontal/vertical precision or non-RTK fix types
before a human reviewer approves them.

The GDB already carries `SurveyPoints_Raw` and `SurveyPoints_QA` tables
(provisioned by `gdb_schema.py`, ADR-0014/0018).  The question is how to get
CSV rows into those tables without requiring arcpy during parsing or testing.

## Decision

Implement `autogis/core/envmon/import_rtk_survey.py` with a strict
parse/QA/write split:

### 1. `RTKColumnMap` — configurable header dataclass

A plain dataclass whose fields are column-name strings (defaulting to the most
common export format: `PointID`, `Northing`, `Easting`, `Elevation_ft`, …).
Callers override individual fields to match their vendor's headers. This avoids
a YAML-per-vendor overhead for what is effectively a one-off mapping.

```python
@dataclass
class RTKColumnMap:
    point_id: str = "PointID"
    northing: str = "Northing"
    ...
```

### 2. `RTKPoint` — pure-Python domain object

A simple dataclass with typed fields.  Rows where any of Northing/Easting/
Elevation_ft cannot be parsed to float are silently skipped (bad GPS lock
produces empty cells, not sentinel values).

### 3. `parse_rtk_csv` — stdlib only

Uses `csv.DictReader`.  No pandas dependency.  Returns `list[RTKPoint]`.
Arcpy-free; fully unit-tested.

### 4. `assign_qa_flags` — threshold + fix-type check

Pure-Python function that returns a list of flag strings:

| Flag | Condition |
|---|---|
| `hrms_exceeds_threshold` | `HRMS_ft > hrms_threshold_ft` (default 0.03 ft) |
| `vrms_exceeds_threshold` | `VRMS_ft > vrms_threshold_ft` (default 0.05 ft) |
| `fix_type_not_rtk` | `FixType` not in `{RTK_FIXED, RTK_FLOAT, NETWORK_RTK}` |

Default thresholds are 0.03 ft horizontal / 0.05 ft vertical (roughly 1 cm /
1.5 cm), matching NGS survey-grade expectations for environmental monitoring
wells.  Both are CLI-overridable.

Keeping QA flags out of the parser means the parser never makes a
PASS/FAIL decision; the QA step is separately testable and separately
replaceable.

### 5. Two-table GDB write (`import_rtk_survey`)

Write to two GDB tables in a single call:

- **`SurveyPoints_Raw`** — verbatim field values from the CSV; no QA filtering.
- **`SurveyPoints_QA`** — one row per point: `QAStatus` (PASS/FAIL), `QAFlags`
  (JSON array stored as TEXT), `Approved` (SHORT, default 0).

Both tables persist the caller-supplied `SiteID` and `BatchID`. This provenance
must travel in the same `arcpy.da.InsertCursor` field list and row order as the
survey values; accepting the values only at the Python boundary is not
sufficient.

`Approved=0` requires an explicit human sign-off before the data are used
downstream.  The two-table split preserves the original measurements even for
failing points.

`QAFlags` is stored as a JSON array string (e.g. `'["hrms_exceeds_threshold"]'`)
rather than a bitmask or separate flag table.  The GDB TEXT field is wide enough
for any realistic combination; JSON is human-readable and round-trips cleanly to
Python without a lookup table.

The write function is marked `# pragma: no cover` and imports arcpy lazily
(ADR-0002 compliant).  The tables must pre-exist (created by the schema
provisioner); the function does not create them.

> **Amended 2026-07-30 for issue #344:** `SiteID` and `BatchID` were added
> additively to both table definitions and the schema version advanced from
> 2.6 to 2.7, so `upgrade-schema` provisions them in existing GDBs. The cursor
> ordering was verified against Esri's
> [InsertCursor documentation](https://pro.arcgis.com/en/pro-app/3.6/arcpy/data-access/insertcursor-class.htm):
> row values must follow the order of the supplied field-name sequence.

### 6. CLI command `import-rtk-survey` (LOCAL)

Registered under the `envmon` Click group, guarded by `_guard("import-rtk-survey")`.
Accepts `--hrms-threshold` / `--vrms-threshold` overrides.  Emits a one-line
summary (total points, QA pass count, QA fail count) to stdout.

## Consequences

### Positive

- Parsing and QA are arcpy-free → fully unit-tested without Pro.
- `RTKColumnMap` handles vendor variation without per-site YAML overhead.
- Two-table design preserves raw data while separating QA state.
- Site and import-batch provenance remains queryable on both raw and QA rows.
- Thresholds are explicit and overridable, not hard-coded magic numbers.
- Pattern consistent with `edd_importer.py` (parse → domain objects → GDB write).

### Negative

- `QAFlags` as JSON string is slightly awkward to query in ArcGIS attribute tables
  (no native JSON field type in FileGDB); accepted because the primary consumer
  is Python, not ArcGIS SQL.
- `Approved` requires a manual workflow step; there is no automated approval path yet.

## Alternatives considered

1. **Single `SurveyPoints` table with inline QA columns**
   — Rejected: complicates the schema and makes it harder to reset/rerun QA
   without losing raw data.

2. **YAML per-vendor column map**
   — Rejected: adds file management overhead for a mapping that is typically
   set once per project. `RTKColumnMap` as a CLI argument or Python override
   is sufficient.

3. **pandas for CSV parsing**
   — Rejected: pandas is not a base dependency (ADR-0008); stdlib `csv` is
   sufficient and keeps the import tree clean.
