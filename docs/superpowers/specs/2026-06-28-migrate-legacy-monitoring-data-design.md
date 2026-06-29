# MigrateLegacyMonitoringData Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** MigrateLegacyMonitoringData (Tool 2.4)
**Priority:** MEDIUM — onboards historical sites so trend/time-series tools have data

---

## Problem

Older sites carry years of one-off Excel tables, legacy geodatabases/shapefiles with
analytical fields hard-coded as wide columns, and prior report tables. None of it fits
the normalized schema (`EnvSample`/`EnvAnalyticalResult`), so trend maps
(`GenerateWellTrendCharts`), `CompareMonitoringEvents`, and `BuildMaxResultMapDataset`
have nothing historical to chew on. Migrating by hand is the bottleneck to making the
whole analysis suite useful on real long-running sites.

---

## Approach

**Chosen:** Mapping-driven wide→long migrator. A YAML migration mapping declares, per
source, how legacy columns map to the normalized schema: which columns are
location/date/matrix, and which wide analyte columns unpivot into
`(analyte, result, units, qualifier)` long rows. The tool reads CSV-exported legacy
tables (the arcpy-free common denominator — feature classes/gdb are exported to CSV
first, or read via the `.pyt` seam), unpivots to long format, runs the records through
the existing screening/units validators, and emits normalized CSVs + a migration QA
report. A `source_dataset` provenance column records where each row came from.

**Rejected: a bespoke importer per legacy format.** The wide→long mapping YAML covers
the dominant case (analytes-as-columns); odd formats get a one-off mapping file, not
new code.

**Rejected: direct gdb/shapefile reads in core.** Violates ADR-0002. Spatial legacy
sources are exported to CSV (or read through the `.pyt` toolbox), keeping the migrator
arcpy-free and CI-testable.

**Rejected: silent unit coercion.** Migration reuses `validate_units.py`; unknown units
become QA errors, never guessed.

---

## Architecture

```
autogis/
  core/envmon/
    validate_units.py        ← EXISTS (reused)
    apply_screening.py        ← EXISTS (reused, optional)
    legacy_migrator.py        ← NEW
  core/common/
    records_csv.py            ← EXISTS (read/write helpers)
  adapters/
    cli.py                    ← add migrate-legacy command (headless)
tests/envmon/
  test_legacy_migrator.py     ← NEW
```

---

## Public API (`legacy_migrator.py`)

```python
@dataclass
class MigrationMapping:
    location_col: str
    date_col: str
    matrix: str | None              # fixed matrix, or matrix_col below
    matrix_col: str | None
    analyte_columns: list[str]      # wide columns to unpivot
    units_default: str | None
    units_col: str | None
    qualifier_suffix: str | None    # e.g. "U" flags nondetect in a sibling col

@dataclass
class MigrationResult:
    rows: list[dict]                # EnvAnalyticalResult-shaped long rows
    skipped: int
    qa: QACollector

def load_mapping(path: Path) -> MigrationMapping: ...

def migrate_legacy_table(
    source_rows: list[dict],
    mapping: MigrationMapping,
    *,
    source_dataset: str,
    validate_units: bool = True,
) -> MigrationResult:
    """Unpivot wide legacy rows to normalized long rows with provenance."""
```

`source_dataset` is written into each row's provenance column (the reserved
provenance columns, ADR-0012).

---

## CLI Command

```
autogis envmon migrate-legacy \
  --source <legacy_table.csv> \
  --mapping <migration_mapping.yaml> \
  --source-name "H281 2008-2015 archive" \
  --out <normalized_results.csv> \
  [--no-validate-units] \
  [--report <migration_qa.md>]
```

Headless. Spatial sources are CSV-exported first or routed through the `.pyt` toolbox.

---

## Test Strategy

`tests/envmon/test_legacy_migrator.py` — arcpy-free:

1. Wide table with 3 analyte columns unpivots to 3 long rows per sample.
2. Fixed `matrix` vs `matrix_col` both populate the matrix field.
3. `units_col` per-row beats `units_default`.
4. Qualifier suffix column flags nondetects.
5. Unknown units → QA error when `validate_units=True`.
6. `source_dataset` written to every row's provenance column.
7. Rows missing location or date are skipped and counted, with a WARNING.
