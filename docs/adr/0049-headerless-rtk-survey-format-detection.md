# ADR-0049: Headerless RTK survey CSV format detection — sniff, guess-with-confidence-gate, retain GNSS metadata end-to-end

**Status:** Accepted

**Date:** 2026-07-03

## Context

`parse_rtk_csv()` (`core/envmon/import_rtk_survey.py`) always treated row 1
as a header via `csv.DictReader`, matching exact column names (`PointID`,
`Northing`, `Easting`, ...). Real RTK data-collector exports are frequently
headerless — an industry-standard PNEZD/PENZD convention (legacy CAD
compatibility, storage minimization on old hardware, crews trained on a
fixed column order). Every row silently failed to match, and both
`validate-rtk-survey` and `import-rtk-survey` reported "0 points — nothing
to check" with no error.

Confirmed against a real file this session: `BroadWATER2059.csv` (Montana
site, 12 points, comma-delimited, headerless, 5-column
`Point, Easting, Northing, Elevation, Description`). Some RTK units also
emit GNSS accuracy/quality metadata (HRMS, VRMS, PDOP, satellite count, fix
type, collection time) in an extended 11-column row shape, which had no
home in the existing schema.

Full design: `docs/superpowers/specs/2026-07-03-headerless-rtk-survey-format-detection-design.md`.

## Decision

- **Header sniffing:** peek at row 1; if columns 2-4 (Coord1/Coord2/
  Elevation) all parse as floats, treat the file as headerless. Otherwise,
  parsing is byte-for-byte identical to the existing `RTKColumnMap` +
  `DictReader` path — zero behavior change for headered CSVs.
- **Column-width dispatch:** 5 columns → PNEZD/PENZD; 11 columns → the
  built-in extended layout (adds `pdop`, `satellites` to `RTKPoint`); any
  other width requires an explicit `--extra-columns` (fixed vocabulary:
  `hrms_ft`, `vrms_ft`, `pdop`, `satellites`, `fix_type`, `collected_at`,
  `operator`, `feature_code`) or the command errors clearly rather than
  guessing.
- **Northing/Easting order:** new `--format {auto,pnezd,penzd}` (default
  `auto`). Auto mode compares average integer-digit-count magnitude between
  the two coordinate columns (Northing reliably exceeds Easting in UTM/most
  State Plane zones) and emits a `guessed_coord_order` QA `WARNING` when
  confident. Equal magnitudes → refuse and demand an explicit `--format`
  rather than silently guessing wrong.
- **FixType normalization:** a case-insensitive synonym map (`FIXED` →
  `RTK_FIXED`, `FLOAT` → `RTK_FLOAT`, `NETWORK RTK`/`NRTK` →
  `NETWORK_RTK`) applied only within the headerless parse path, so headered
  CSVs are unaffected and genuinely non-RTK fixes (`DGPS`, etc.) still trip
  `fix_type_not_rtk`.
- **Schema (additive, three files):** `RTKPoint` gains `pdop`/`satellites`;
  `SurveyPointRaw` (`core/common/schema/survey.py`) gains matching fields as
  the declared GDB-write superset; `gdb_schema.py`'s `SurveyPoints_Raw`
  table definition gains `PDOP`/`Satellites` columns, and
  `import_rtk_survey()`'s `InsertCursor` field list/values are updated to
  match. `upgrade_schema.SCHEMA_VERSION` bumped `2.0` → `2.1` per its
  existing additive-upgrade convention.
- **CLI surface:** both `validate-rtk-survey` and `import-rtk-survey` gain
  `--format` and `--extra-columns`. Both commands build one `QACollector`
  before parsing and pass it into `parse_rtk_csv(..., qa=qa)` (matching the
  existing `qa: QACollector | None = None` convention, e.g.
  `audit_item_dependencies`), so parse-time warnings land in the same
  `--report`/`--fail-on` output as validation warnings. Both options are
  no-ops with a warning on already-headered input.

## Consequences

- `BroadWATER2059.csv` and similarly-shaped headerless exports now validate
  and import correctly instead of silently reporting zero points.
- `validate_rtk_points()` gained an optional `qa` parameter (backward
  compatible — defaults to a fresh `QACollector` exactly as before) so
  parse-time and validation-time QA merge into one report.
- `import_rtk_survey()`'s GDB write path (arcpy-backed) cannot be exercised
  headlessly here; it stays `# pragma: no cover` per existing convention.
  Verified arcpy-free-importable; pure-Python coverage added for
  `SurveyPointRaw`'s new fields.
- `BroadWATER2059.csv` itself lives only on the user's local machine
  (outside this session's environment) — its regression test
  (`test_broadwater_real_fixture_12_points`) is written against that literal
  path with `skipif not exists`, so it exercises the real file on a machine
  where it's present and skips cleanly elsewhere, rather than substituting
  synthetic data for a fixture the spec called out as real.
- Non-goals carried over unimplemented, as scoped: the PT/QA
  interleaved-line format, numeric NMEA fix-quality codes, and new
  PDOP/satellite-count QA threshold checks.

## Alternatives considered

Changing the return type of `parse_rtk_csv()` to `(points, qa)` was
rejected in favor of the existing in-place `qa` populate-by-reference
convention already used elsewhere in the codebase, for consistency and to
avoid a breaking signature change for existing callers
(`export-survey-cad`, `survey-to-well-elevation`) that don't need the new
options.
