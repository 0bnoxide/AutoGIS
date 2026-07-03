# Headerless RTK Survey CSV Format Detection — Design

**Date:** 2026-07-03
**Status:** Approved — spec only, implementation deferred to a scheduled routine agent
**Tool:** extends `validate-rtk-survey` and `import-rtk-survey` (no new CLI command)
**Runtime:** CLOUD (`validate-rtk-survey`) / LOCAL (`import-rtk-survey`) — both call the same core parser
**Priority:** MEDIUM — blocks real field data (see Problem) but has a working manual workaround

---

## Problem

`parse_rtk_csv()` (`autogis/core/envmon/import_rtk_survey.py`) always treats
row 1 as a header via `csv.DictReader`, looking for exact column names
(`PointID`, `Northing`, `Easting`, `Elevation_ft`, ...). Real RTK data-collector
exports are frequently headerless — an industry-standard convention (legacy CAD
compatibility, storage minimization on old hardware, crews trained on a fixed
column order) — so every row silently fails to match, and the tool reports
`"0 points — nothing to check"` with no error. There is no `--column-map` or
equivalent CLI escape hatch today.

Confirmed against a real file this session: `BroadWATER2059.csv` (Montana
site, 12 points), a comma-delimited, headerless, 5-column
`Point, Easting, Northing, Elevation, Description` export (PENZD convention).
Manually adding a header and confirming column order (Easting is the
6-digit column near a ~600,000 ft false-easting origin; Northing is the
7-digit column) unblocked validation for that one file, but the tool should
handle this shape natively.

Some RTK units also emit accuracy/quality metadata (horizontal/vertical RMS,
PDOP, satellite count, fix type, timestamp) alongside the coordinates in the
same headerless row. That metadata has no home in the current schema and
would otherwise be silently discarded even after headerless parsing is fixed.

---

## Goals

1. Auto-detect whether an RTK CSV has a header row at all.
2. Parse two recognized headerless layouts, dispatched by column count:
   - **5 columns** — `PNEZD`/`PENZD` (Point, Coord1, Coord2, Elevation, Description).
   - **11 columns** — extended layout that also retains HRMS, VRMS, PDOP,
     satellite count, fix type, and collection time (schema below).
3. Auto-detect Northing-vs-Easting column order via a magnitude/digit-count
   heuristic, gated by confidence: proceed with a loud warning when the two
   columns are clearly different orders of magnitude; refuse and demand an
   explicit flag when they're not.
4. Let the user override every guess explicitly and per-run — coordinate
   order and extra-column layout — rather than trusting auto-detection
   unconditionally.
5. Zero behavior change for existing well-formed headered CSVs.
6. Retained accuracy metadata must survive both consumers: the CLOUD path
   (`validate-rtk-survey`, in-memory/report) **and** the LOCAL path
   (`import-rtk-survey` → GDB). Storing new fields on `RTKPoint` but dropping
   them before the GDB write would only be half a fix.

## Non-goals (this pass — no real sample to design against yet)

- The "PT/QA" interleaved two-physical-line-per-point format some units
  (Trimble/Leica) emit. Structurally a different parsing strategy (row
  pairing by shared ID), not a wider positional read. Separate spec if/when
  a real file in that shape shows up.
- Numeric NMEA-style fix-quality codes (e.g. `4` = RTK Fixed) as an alternate
  encoding of `FixType`. The real sample obtained this session uses the
  literal string `FIXED`, not a numeric code — build against what's real.
- New QA threshold checks against PDOP or satellite count (e.g. "PDOP > 2.0 →
  warning"). Retaining the data is in scope; alerting on it is a separate
  feature.
- Any change to `rtk-control-check` (different CSV schema entirely —
  control-point benchmarks, not raw survey shots) or `export-survey-cad`.

---

## Design

### 1. Header sniffing

Before falling into `csv.DictReader`, peek at row 1's fields. Columns 2–4
(index 1–3) hold Coord1, Coord2, and Elevation in *every* recognized
headerless layout — that positional fact holds regardless of 5- vs
11-column width, since width only diverges starting at column 6. If those
three fields all parse as floats, the row is data, not column names →
treat the file as headerless. Otherwise, parsing is byte-for-byte identical
to today (`RTKColumnMap` + `DictReader`) — existing headered CSVs and their
tests are unaffected.

### 2. Column-width dispatch (headerless path only)

- **width == 5** → `PNEZD`/`PENZD`: `PointID, Coord1, Coord2, Elevation_ft, Description`.
- **width == 11** → extended layout (see field table below).
- **any other width, and no `--extra-columns` given** → hard error:
  `"headerless parsing only supports 5-column PNEZD/PENZD or 11-column
  extended layouts; got N columns. Use --extra-columns to declare a custom
  layout."` No silent partial guessing at unrecognized shapes.
- **`--extra-columns <name,name,...>`** (optional, both commands): explicit
  override naming columns 6+ in order, from a fixed vocabulary — `hrms_ft`,
  `vrms_ft`, `pdop`, `satellites`, `fix_type`, `collected_at`, `operator`,
  `feature_code`. When given, it replaces the built-in 11-column assumption
  for that run, so a different vendor's export shape doesn't have to wait on
  a new built-in layout. An unrecognized field name in the list fails with
  the valid vocabulary listed. Given on a 5-column file (nothing for it to
  map), it's a no-op with a warning that there were no extra columns to map.

### 3. Extended 11-column layout (built-in default when `--extra-columns` is absent)

Derived from a real sample provided this session (values are row 1,
`MW-5R`):

| Col | Field | Sample | Maps to |
|---|---|---|---|
| 1 | PointID | `1` | `RTKPoint.point_id` |
| 2 | Coord1 | `558281.5482` | Easting or Northing — see §4 |
| 3 | Coord2 | `2206038.3110` | Northing or Easting — see §4 |
| 4 | Elevation_ft | `3224.0823` | `RTKPoint.elevation_ft` |
| 5 | Description | `MW-5R` | `RTKPoint.description` |
| 6 | HRMS_ft (HzPrec) | `0.011` | `RTKPoint.hrms_ft` |
| 7 | VRMS_ft (VrtPrec) | `0.019` | `RTKPoint.vrms_ft` |
| 8 | PDOP | `1.2` | `RTKPoint.pdop` **(new field)** |
| 9 | Satellites | `22` | `RTKPoint.satellites` **(new field)** |
| 10 | FixType | `FIXED` | `RTKPoint.fix_type` (normalized — see §5) |
| 11 | CollectedAt | `14:23:10` | `RTKPoint.collected_at` |

### 4. Northing/Easting order detection

New option on both commands: **`--format {auto,pnezd,penzd}`**, default
`auto`. Governs the meaning of Coord1/Coord2 in both the 5- and 11-column
layouts.

- **`auto`:** compute the average magnitude (integer-part digit count) of
  Coord1 and Coord2 across all data rows. The larger-magnitude column is
  Northing — in both UTM (measured from the equator) and most US State
  Plane zones (large false-northing origins), Northing reliably exceeds
  Easting, which is centered near a false easting around 500,000–600,000.
  This is the same reasoning used to resolve `BroadWATER2059.csv` manually
  (Easting ≈ 558,281 ft — 6 digits; Northing ≈ 2,206,038 ft — 7 digits).
- **Confidence gate:** if Coord1 and Coord2 have the *same* average digit
  count (can't tell them apart by magnitude), auto mode does not guess — it
  raises a clear error demanding `--format pnezd` or `--format penzd`
  explicitly. An uncertain silent guess is worse than refusing.
- **When confident:** proceed, and emit a `QACollector` `WARNING` record
  (folded into the same object `validate_rtk_points()` already produces, so
  it shows up in the existing `--report`/`--fail-on` machinery) stating the
  guess and the magnitudes behind it, e.g.: `guessed_coord_order: column 2
  = Easting (avg magnitude ~558,281, 6 digits), column 3 = Northing (avg
  magnitude ~2,206,038, 7 digits) — pass --format pnezd|penzd to override
  if wrong.`
- **`pnezd`** — Coord1 = Northing, Coord2 = Easting.
- **`penzd`** — Coord1 = Easting, Coord2 = Northing.

`parse_rtk_csv()` needs a way to surface this warning to its caller. Match
the existing codebase convention already used elsewhere (e.g.
`audit_item_dependencies(gis, item_id, qa=qa, ...)`): add an optional
`qa: QACollector | None = None` parameter that gets populated in place,
rather than changing the return type.

### 5. FixType normalization

The real sample uses the literal string `FIXED`, but `assign_qa_flags()`
only recognizes `RTK_FIXED` / `RTK_FLOAT` / `NETWORK_RTK`
(`_RTK_FIX_TYPES` in `import_rtk_survey.py`) — unmapped, every point parsed
from this layout would be falsely flagged `fix_type_not_rtk`. Apply a
case-insensitive synonym normalization after parsing, before QA evaluation:

| Raw value (any case) | Normalized to |
|---|---|
| `FIXED` | `RTK_FIXED` |
| `FLOAT` | `RTK_FLOAT` |
| `NETWORK RTK`, `NRTK` | `NETWORK_RTK` |

Anything not in this table passes through unchanged, so genuinely
non-RTK fixes (`DGPS`, `AUTONOMOUS`, etc.) are still correctly flagged by
the existing check — this is a synonym map, not a permissive bypass.

### 6. Schema changes required to actually retain PDOP/Satellites end-to-end

Two fields (`pdop`, `satellites`) have no home in the current schema. Three
places need them, or the LOCAL/GDB path silently drops what the CLOUD path
retains:

1. **`RTKPoint`** (`autogis/core/envmon/import_rtk_survey.py`) — add
   `pdop: Optional[float] = None`, `satellites: Optional[int] = None`.
2. **`SurveyPointRaw`** (`autogis/core/common/schema/survey.py`) — the
   canonical intermediate representation `to_row()`s into the GDB write path;
   already has fields `RTKPoint` doesn't (`correction_source`,
   `occupation_time_s`, `rod_height`), confirming this dataclass is meant to
   be the superset. Add matching `pdop`/`satellites` fields here too, and
   verify/update wherever `RTKPoint` → `SurveyPointRaw` conversion happens.
3. **`gdb_schema.py`** (`autogis/core/envmon/gdb_schema.py`) — the Esri-side
   field definitions for `SurveyPoints_Raw`. Add the two fields as an
   additive change via the existing schema-upgrade mechanism
   (`upgrade_schema.py`, `SCHEMA_VERSION` — currently `"2.0"`, bump per its
   existing convention) so upgrading an existing GDB doesn't require a
   rebuild.
4. **`import_rtk_survey()`** InsertCursor field list (same file, ~line
   119–125) needs `"PDOP"` / `"Satellites"` added alongside the existing
   column list, with corresponding values from each `RTKPoint`.

This part touches arcpy-backed code (`import_rtk_survey()`, `gdb_schema.py`
additions) and cannot be exercised in a headless test environment — the
implementing agent should verify it compiles/imports arcpy-free (per the
project's `core`/`adapters` invariant) and add pure-Python unit coverage
where possible (e.g. the `SurveyPointRaw.to_row()` shape), leaving the
actual GDB write path to manual/Pro verification, consistent with how the
rest of `import_rtk_survey()` is already `# pragma: no cover`.

---

## CLI surface changes

Both `validate-rtk-survey` and `import-rtk-survey` (the two commands that
call `parse_rtk_csv()`) gain two new options:

```
--format [auto|pnezd|penzd]     Coordinate column order for headerless input. [default: auto]
--extra-columns TEXT             Comma-separated field names for columns 6+ of a headerless
                                  file, overriding the built-in 11-column layout. Vocabulary:
                                  hrms_ft, vrms_ft, pdop, satellites, fix_type, collected_at,
                                  operator, feature_code.
```

Both options are no-ops (with a warning if passed) on files that already
have a matching header row — headered CSVs are unambiguous already.

---

## Testing

New coverage in `tests/envmon/test_import_rtk_survey.py`:

- Headerless 5-column file, confident magnitude difference → correct
  `RTKPoint`s, `guessed_coord_order` WARNING present in the passed-in `qa`.
- Headerless 5-column file, ambiguous magnitudes (same digit count) →
  raises, no guess made.
- `--format pnezd` / `--format penzd` on a headerless file → bypasses
  guessing entirely, correct mapping, no warning.
- Headerless 11-column file (the real sample from this spec) → all eleven
  fields land correctly on `RTKPoint`, including `pdop`/`satellites`.
- FixType normalization: `FIXED`/`FLOAT`/`NRTK` (mixed case) → normalized;
  unrecognized value passes through and still trips `fix_type_not_rtk`.
- `--extra-columns` override on a non-11-column headerless file → correct
  positional mapping; unrecognized field name in the list → clear error.
- Malformed column count with no `--extra-columns` → clear error, no
  partial/silent parse.
- Regression: existing headered-CSV fixtures/tests unchanged in behavior.

CLI-level test in `tests/envmon/test_validate_rtk_survey.py` exercising
`--format` and the QA-report integration end-to-end (report file contains
the `guessed_coord_order` warning).

Pure-Python coverage only for the `SurveyPointRaw` schema changes and
`RTKPoint`→`SurveyPointRaw` conversion; `import_rtk_survey()` itself stays
`# pragma: no cover` per existing convention (needs arcpy).

---

## Real fixture available

`BroadWATER2059.csv` (referenced in this spec) exists at
`C:\Users\ichbi\OneDrive\Desktop\AutoGIS\BroadWATER2059.csv` — a real
5-column headerless PENZD file, useful as a live regression fixture beyond
synthetic test data. The 11-column extended-format sample used in §3 was
provided inline in the design conversation (not yet saved as a file) — the
implementing agent should materialize it as a test fixture rather than
re-deriving it.
