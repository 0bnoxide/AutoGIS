# MigrateLegacyMonitoringData Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Build `migrate-legacy-data` CLI command (Tool 2.4) that reads flat CSV/XLSX exports from pre-AutoGIS monitoring databases, applies a YAML column-mapping file, validates required canonical fields, and writes `samples.csv` + `results.csv` ready for `import-gdb` — all without arcpy.

**Architecture:**
- New: `autogis/core/envmon/legacy_migrator.py` — `LegacyMigrationConfig`, `ColumnMapping`, `MigrationResult`, `migrate_legacy_data()`
- New: `autogis/config/legacy_mappings/example_mapping.yaml` — reference column mapping
- Modify: `autogis/adapters/cli.py` — add `migrate-legacy-data` command
- Modify: `autogis/runtime/capabilities.py` — register `"migrate-legacy-data": Runtime.CLOUD`
- New: `tests/envmon/test_legacy_migrator.py`

**Tech stack:** Python 3.14, click, stdlib `csv`/`dataclasses`/`pathlib`, PyYAML (already in project), openpyxl (already in project). No new packages.

## Global Constraints

- `core/` and `adapters/` import without arcpy or arcgis present.
- `legacy_migrator.py` is entirely arcpy-free. GDB writes go via a subsequent `import-gdb` call.
- Command name exactly `migrate-legacy-data`. Register as `Runtime.CLOUD`.
- YAML mapping has two top-level sections — `samples` and `results` — each declaring `canonical_field_name: legacy_column_name` pairs.
- Required canonical fields for samples: `site_id`, `location_id`, `event_date`, `matrix`, `sample_id`.
- Required canonical fields for results: `sample_id`, `analyte`, `result`, `units`.
- Missing required canonical field on a row → `SEV_ERROR` per row; row skipped from both outputs.
- Source column present in data but absent from mapping → `SEV_WARNING` emitted once per column name (not once per row).
- `event_id` from config is written as `import_batch_id` in output CSVs.
- `site_id` from config is used as fallback when the mapping omits `site_id` (most legacy files omit it).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `legacy_migrator.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/legacy_migrator.py`
- Create: `tests/envmon/test_legacy_migrator.py`

**Complete code — `legacy_migrator.py`:**

```python
"""MigrateLegacyMonitoringData — Tool 2.4.

Reads flat CSV/XLSX legacy monitoring exports, applies a YAML column mapping,
validates required canonical fields, and writes canonical samples.csv +
results.csv accepted by import-gdb.  No arcpy dependency.
"""
from __future__ import annotations

import csv
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

# ---------------------------------------------------------------------------
# Canonical field sets (matches autogis/core/common/schema/envmon.py)
# ---------------------------------------------------------------------------

_REQUIRED_SAMPLE_FIELDS = {"site_id", "location_id", "event_date", "matrix", "sample_id"}
_ALL_SAMPLE_FIELDS = [
    "site_id", "location_id", "event_date", "matrix", "sample_id",
    "depth_top_ft", "depth_bot_ft", "sampled_by", "import_batch_id",
]

_REQUIRED_RESULT_FIELDS = {"sample_id", "analyte", "result", "units"}
_ALL_RESULT_FIELDS = [
    "sample_id", "analyte", "result", "units",
    "qualifier", "reporting_limit", "method", "lab", "is_nondetect",
    "import_batch_id",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LegacyMigrationConfig:
    source_path: Path
    mapping_yaml: Path
    output_dir: Path
    event_id: str
    site_id: str


@dataclass
class ColumnMapping:
    """Holds per-table canonical→legacy column name mappings loaded from YAML."""
    samples: dict  # canonical_field_name -> legacy_column_name
    results: dict  # canonical_field_name -> legacy_column_name

    @classmethod
    def from_yaml(cls, path: Path) -> "ColumnMapping":
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(
            samples=dict(data.get("samples", {})),
            results=dict(data.get("results", {})),
        )

    @classmethod
    def from_dicts(cls, samples: dict, results: dict) -> "ColumnMapping":
        """Convenience constructor for tests — pass dicts directly."""
        return cls(samples=dict(samples), results=dict(results))


@dataclass
class MigrationResult:
    rows_migrated: int
    rows_skipped: int
    output_files: list  # list[Path]
    qa: QACollector


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_source(path: Path) -> list:
    """Read CSV or XLSX; return list of row dicts."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    if suffix in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h) if h is not None else "" for h in rows[0]]
        return [dict(zip(headers, row)) for row in rows[1:]]
    raise ValueError(f"Unsupported source file extension '{suffix}'; expected .csv or .xlsx")


# ---------------------------------------------------------------------------
# Core transform
# ---------------------------------------------------------------------------

def _apply_mapping(row: dict, mapping: dict) -> dict:
    """Return a canonical-keyed dict by applying mapping to one source row."""
    out = {}
    for canonical, legacy in mapping.items():
        val = row.get(str(legacy))
        out[canonical] = "" if val is None else str(val).strip()
    return out


def migrate_legacy_data(config: LegacyMigrationConfig) -> MigrationResult:
    """Read source file, apply column mapping, validate, write canonical CSVs.

    Returns MigrationResult with counts and a QACollector populated with any
    warnings (unmapped columns) or errors (missing required fields).
    """
    qa = QACollector()
    config = dataclasses.replace(
        config,
        source_path=Path(config.source_path),
        mapping_yaml=Path(config.mapping_yaml),
        output_dir=Path(config.output_dir),
    )

    # Load mapping
    mapping = ColumnMapping.from_yaml(config.mapping_yaml)

    # Read source rows
    raw_rows = _read_source(config.source_path)

    # Warn once per unmapped source column
    if raw_rows:
        source_cols = set(raw_rows[0].keys())
        mapped_legacy_cols: set = (
            set(mapping.samples.values()) | set(mapping.results.values())
        )
        for col in sorted(source_cols - mapped_legacy_cols):
            qa.add(SEV_WARNING, "unmapped_column",
                   f"Source column '{col}' has no entry in mapping; "
                   f"it will be ignored in output.",
                   source_workbook=str(config.source_path.name))

    # Transform rows
    sample_rows: list = []
    result_rows: list = []
    seen_sample_keys: set = set()
    rows_migrated = 0
    rows_skipped = 0

    for row_num, raw in enumerate(raw_rows, start=2):
        sample_can = _apply_mapping(raw, mapping.samples)
        result_can = _apply_mapping(raw, mapping.results)

        # Inject config-level site_id and event_id
        if not sample_can.get("site_id"):
            sample_can["site_id"] = config.site_id
        if not result_can.get("site_id", None) is None:
            pass  # results table has no site_id column
        sample_can["import_batch_id"] = config.event_id
        result_can["import_batch_id"] = config.event_id

        # Validate required canonical fields — check both tables together
        missing_sample = [f for f in _REQUIRED_SAMPLE_FIELDS
                          if not sample_can.get(f)]
        missing_result = [f for f in _REQUIRED_RESULT_FIELDS
                          if not result_can.get(f)]
        all_missing = sorted(set(missing_sample) | set(missing_result))

        if all_missing:
            qa.add(SEV_ERROR, "missing_required_field",
                   f"Row {row_num}: missing required canonical field(s): "
                   f"{', '.join(all_missing)} — row skipped.",
                   source_workbook=str(config.source_path.name),
                   source_row=row_num)
            rows_skipped += 1
            continue

        # Deduplicate sample rows
        sample_key = (
            sample_can.get("site_id", ""),
            sample_can.get("location_id", ""),
            sample_can.get("event_date", ""),
            sample_can.get("matrix", ""),
            sample_can.get("sample_id", ""),
        )
        if sample_key not in seen_sample_keys:
            seen_sample_keys.add(sample_key)
            # Ensure all canonical columns present (fill missing optional fields with "")
            full_sample = {f: sample_can.get(f, "") for f in _ALL_SAMPLE_FIELDS}
            sample_rows.append(full_sample)

        # Always emit one result row per source row
        full_result = {f: result_can.get(f, "") for f in _ALL_RESULT_FIELDS}
        result_rows.append(full_result)
        rows_migrated += 1

    # Write output CSVs
    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_files = []

    samples_path = config.output_dir / "samples.csv"
    with samples_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_ALL_SAMPLE_FIELDS)
        writer.writeheader()
        writer.writerows(sample_rows)
    output_files.append(samples_path)

    results_path = config.output_dir / "results.csv"
    with results_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_ALL_RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(result_rows)
    output_files.append(results_path)

    qa.add(SEV_INFO, "migration_complete",
           f"migrate_legacy_data: {rows_migrated} rows migrated, "
           f"{rows_skipped} skipped, "
           f"{len(seen_sample_keys)} unique samples → {config.output_dir}")

    return MigrationResult(
        rows_migrated=rows_migrated,
        rows_skipped=rows_skipped,
        output_files=output_files,
        qa=qa,
    )
```

**Complete code — `tests/envmon/test_legacy_migrator.py`:**

```python
"""Unit tests for legacy_migrator (Tool 2.4)."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.legacy_migrator import (
    ColumnMapping,
    LegacyMigrationConfig,
    MigrationResult,
    migrate_legacy_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLES_MAP = {
    "site_id":      "SiteCode",
    "location_id":  "WellID",
    "event_date":   "SampleDate",
    "matrix":       "Medium",
    "sample_id":    "LabID",
}
_RESULTS_MAP = {
    "sample_id":  "LabID",
    "analyte":    "Chemical",
    "result":     "ResultValue",
    "units":      "ReportedUnits",
    "qualifier":  "Qualifier",
}

_MAPPING_YAML = """\
samples:
  site_id:     SiteCode
  location_id: WellID
  event_date:  SampleDate
  matrix:      Medium
  sample_id:   LabID
results:
  sample_id:  LabID
  analyte:    Chemical
  result:     ResultValue
  units:      ReportedUnits
  qualifier:  Qualifier
"""

_LEGACY_ROW = {
    "SiteCode": "H281",
    "WellID": "MW-1",
    "SampleDate": "2026-04-01",
    "Medium": "GW",
    "LabID": "H281-MW1-001",
    "Chemical": "Benzene",
    "ResultValue": "5.0",
    "ReportedUnits": "ug/L",
    "Qualifier": "",
    "ExtraColumn": "should_warn",
}


def _make_config(tmp_path: Path, rows: list[dict],
                 mapping_yaml: str = _MAPPING_YAML,
                 event_id: str = "EVT-2026-04",
                 site_id: str = "H281",
                 fmt: str = "csv") -> LegacyMigrationConfig:
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(mapping_yaml, encoding="utf-8")

    if fmt == "csv":
        src = tmp_path / "legacy.csv"
        if rows:
            with src.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                for r in rows:
                    w.writerow(r)
        else:
            src.write_text("", encoding="utf-8")
    else:
        raise ValueError("Only CSV fixture supported in tests; XLSX tested via read path")

    return LegacyMigrationConfig(
        source_path=src,
        mapping_yaml=mapping_path,
        output_dir=tmp_path / "out",
        event_id=event_id,
        site_id=site_id,
    )


# ---------------------------------------------------------------------------
# ColumnMapping
# ---------------------------------------------------------------------------

def test_column_mapping_from_yaml(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text(_MAPPING_YAML, encoding="utf-8")
    cm = ColumnMapping.from_yaml(p)
    assert cm.samples["location_id"] == "WellID"
    assert cm.results["analyte"] == "Chemical"


def test_column_mapping_from_dicts():
    cm = ColumnMapping.from_dicts(_SAMPLES_MAP, _RESULTS_MAP)
    assert cm.samples["site_id"] == "SiteCode"
    assert cm.results["units"] == "ReportedUnits"


# ---------------------------------------------------------------------------
# migrate_legacy_data — happy path
# ---------------------------------------------------------------------------

def test_basic_migration_writes_csvs(tmp_path):
    config = _make_config(tmp_path, [_LEGACY_ROW])
    result = migrate_legacy_data(config)
    assert result.rows_migrated == 1
    assert result.rows_skipped == 0
    assert len(result.output_files) == 2
    samples_path = config.output_dir / "samples.csv"
    results_path = config.output_dir / "results.csv"
    assert samples_path.exists()
    assert results_path.exists()


def test_canonical_field_names_in_output(tmp_path):
    config = _make_config(tmp_path, [_LEGACY_ROW])
    migrate_legacy_data(config)
    with (config.output_dir / "samples.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        row = next(reader)
    assert "location_id" in row
    assert "event_date" in row
    assert "WellID" not in row          # legacy column name must not appear
    assert row["location_id"] == "MW-1"


def test_event_id_written_as_import_batch_id(tmp_path):
    config = _make_config(tmp_path, [_LEGACY_ROW], event_id="EVT-2026-04")
    migrate_legacy_data(config)
    with (config.output_dir / "results.csv").open(newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    assert row["import_batch_id"] == "EVT-2026-04"


def test_site_id_injected_from_config(tmp_path):
    row = dict(_LEGACY_ROW)
    del row["SiteCode"]          # omit site_id from source
    yaml_no_site = _MAPPING_YAML.replace("  site_id:     SiteCode\n", "")
    config = _make_config(tmp_path, [row], mapping_yaml=yaml_no_site, site_id="H281")
    migrate_legacy_data(config)
    with (config.output_dir / "samples.csv").open(newline="", encoding="utf-8") as fh:
        sample = next(csv.DictReader(fh))
    assert sample["site_id"] == "H281"


def test_sample_deduplication(tmp_path):
    """Two result rows for the same sample should yield one sample row."""
    row2 = dict(_LEGACY_ROW)
    row2["Chemical"] = "Toluene"
    row2["ResultValue"] = "12.0"
    config = _make_config(tmp_path, [_LEGACY_ROW, row2])
    result = migrate_legacy_data(config)
    assert result.rows_migrated == 2
    with (config.output_dir / "samples.csv").open(newline="", encoding="utf-8") as fh:
        sample_rows = list(csv.DictReader(fh))
    assert len(sample_rows) == 1
    with (config.output_dir / "results.csv").open(newline="", encoding="utf-8") as fh:
        result_rows = list(csv.DictReader(fh))
    assert len(result_rows) == 2


def test_empty_source_file(tmp_path):
    config = _make_config(tmp_path, [])
    result = migrate_legacy_data(config)
    assert result.rows_migrated == 0
    assert result.rows_skipped == 0
    assert (config.output_dir / "samples.csv").exists()


# ---------------------------------------------------------------------------
# QA: unmapped column → WARNING
# ---------------------------------------------------------------------------

def test_unmapped_column_emits_warning(tmp_path):
    """Source column 'ExtraColumn' not in mapping → SEV_WARNING."""
    config = _make_config(tmp_path, [_LEGACY_ROW])
    result = migrate_legacy_data(config)
    warnings = [r for r in result.qa.records if r.severity == SEV_WARNING
                and r.category == "unmapped_column"]
    assert any("ExtraColumn" in w.message for w in warnings), (
        f"Expected warning about ExtraColumn; got: {[w.message for w in warnings]}"
    )


def test_unmapped_column_warning_emitted_once(tmp_path):
    """Multiple rows with same unmapped column → only one warning."""
    row2 = dict(_LEGACY_ROW)
    row2["Chemical"] = "Toluene"
    row2["ResultValue"] = "2.0"
    config = _make_config(tmp_path, [_LEGACY_ROW, row2])
    result = migrate_legacy_data(config)
    extra_warnings = [r for r in result.qa.records
                      if r.severity == SEV_WARNING
                      and r.category == "unmapped_column"
                      and "ExtraColumn" in r.message]
    assert len(extra_warnings) == 1


# ---------------------------------------------------------------------------
# QA: missing required field → ERROR, row skipped
# ---------------------------------------------------------------------------

def test_missing_required_result_field_emits_error(tmp_path):
    """Row missing 'analyte' (canonical) → SEV_ERROR, row skipped."""
    row = dict(_LEGACY_ROW)
    del row["Chemical"]          # Chemical maps to 'analyte'
    config = _make_config(tmp_path, [row])
    result = migrate_legacy_data(config)
    assert result.rows_skipped == 1
    assert result.rows_migrated == 0
    errors = [r for r in result.qa.records if r.severity == SEV_ERROR]
    assert errors, "Expected at least one SEV_ERROR QA record"
    assert any("analyte" in e.message for e in errors)


def test_missing_required_sample_field_emits_error(tmp_path):
    """Row missing 'location_id' → SEV_ERROR, row skipped."""
    row = dict(_LEGACY_ROW)
    del row["WellID"]            # WellID maps to 'location_id'
    config = _make_config(tmp_path, [row])
    result = migrate_legacy_data(config)
    assert result.rows_skipped == 1
    errors = [r for r in result.qa.records if r.severity == SEV_ERROR]
    assert any("location_id" in e.message for e in errors)


def test_valid_rows_pass_despite_earlier_error(tmp_path):
    """A bad row is skipped; subsequent valid rows are still migrated."""
    bad_row = dict(_LEGACY_ROW)
    del bad_row["Chemical"]
    good_row = dict(_LEGACY_ROW)
    good_row["Chemical"] = "Toluene"
    config = _make_config(tmp_path, [bad_row, good_row])
    result = migrate_legacy_data(config)
    assert result.rows_migrated == 1
    assert result.rows_skipped == 1


# ---------------------------------------------------------------------------
# MigrationResult dataclass
# ---------------------------------------------------------------------------

def test_migration_result_fields(tmp_path):
    config = _make_config(tmp_path, [_LEGACY_ROW])
    result = migrate_legacy_data(config)
    assert isinstance(result, MigrationResult)
    assert isinstance(result.output_files, list)
    assert all(isinstance(p, Path) for p in result.output_files)
    assert isinstance(result.qa, QACollector)
```

**Steps:**
- [ ] Write `tests/envmon/test_legacy_migrator.py` as shown above.
- [ ] Run `python -m pytest tests/envmon/test_legacy_migrator.py -q` — expect `ImportError` (module not yet created).
- [ ] Implement `autogis/core/envmon/legacy_migrator.py` as shown above.
- [ ] Run `python -m pytest tests/envmon/test_legacy_migrator.py -q` — expect all pass.
- [ ] Run `python -m pytest -q` — expect no regressions.
- [ ] Commit: `feat(envmon): legacy_migrator — migrate_legacy_data core (Tool 2.4)`

---

### Task 2: Example YAML mapping file

**Files:**
- Create: `autogis/config/legacy_mappings/example_mapping.yaml`

**Complete file:**

```yaml
# autogis/config/legacy_mappings/example_mapping.yaml
#
# Reference column mapping for a typical pre-AutoGIS flat-export monitoring DB.
# Copy and edit to match your legacy system's column names.
#
# Format:
#   samples:
#     <canonical_field>: <legacy_column_name>
#   results:
#     <canonical_field>: <legacy_column_name>
#
# Required canonical fields:
#   samples: site_id, location_id, event_date, matrix, sample_id
#   results: sample_id, analyte, result, units
#
# site_id may be omitted here and supplied via --site-id on the CLI instead.

samples:
  site_id:      SiteCode          # or omit and pass --site-id on CLI
  location_id:  MonitoringWellID
  event_date:   SampleDate        # expected: YYYY-MM-DD or M/D/YYYY
  matrix:       SampleMedium      # e.g. GW, SOIL, SW
  sample_id:    LabSampleID
  depth_top_ft: TopDepthFt
  depth_bot_ft: BottomDepthFt
  sampled_by:   FieldTechnician

results:
  sample_id:        LabSampleID
  analyte:          ParameterName
  result:           ResultValue
  units:            ReportingUnits
  qualifier:        Qualifier
  reporting_limit:  ReportingLimit
  method:           AnalyticalMethod
  lab:              LaboratoryName
  is_nondetect:     NonDetectFlag   # optional; "Y"/"1"/etc. all treated as truthy
```

**Steps:**
- [ ] Create `autogis/config/legacy_mappings/` directory.
- [ ] Write `example_mapping.yaml` as shown above.
- [ ] Commit: `feat(config): legacy_mappings/example_mapping.yaml — reference column mapping for Tool 2.4`

---

### Task 3: CLI command + capabilities registration

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `autogis/runtime/capabilities.py`

**CLI command (add to `envmon` group in `autogis/adapters/cli.py`):**

```python
@envmon.command("migrate-legacy-data")
@click.option("--source", "source_path", required=True,
              type=click.Path(exists=True),
              help="Legacy CSV or XLSX file to migrate.")
@click.option("--mapping", "mapping_yaml", required=True,
              type=click.Path(exists=True),
              help="YAML column-mapping file (canonical_field: legacy_column).")
@click.option("--out-dir", required=True, type=click.Path(),
              help="Directory for output samples.csv and results.csv.")
@click.option("--event-id", required=True,
              help="Event identifier written as import_batch_id in output CSVs.")
@click.option("--site-id", required=True,
              help="Site ID (e.g. H281); injected when omitted from mapping.")
@click.option("--report", default=None, type=click.Path(),
              help="Optional QA report output path (.csv or .json).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True,
              help="Exit non-zero if QA reaches this severity.")
def migrate_legacy_data_cmd(source_path, mapping_yaml, out_dir,
                             event_id, site_id, report, fail_on):
    """Tool 2.4: migrate pre-AutoGIS flat CSV/XLSX to canonical envmon CSVs (headless)."""
    from autogis.core.envmon.legacy_migrator import (
        LegacyMigrationConfig, migrate_legacy_data,
    )

    config = LegacyMigrationConfig(
        source_path=Path(source_path),
        mapping_yaml=Path(mapping_yaml),
        output_dir=Path(out_dir),
        event_id=event_id,
        site_id=site_id,
    )
    result = migrate_legacy_data(config)
    click.echo(
        f"Migration complete: {result.rows_migrated} row(s) migrated, "
        f"{result.rows_skipped} skipped."
    )
    for f in result.output_files:
        click.echo(f"  Written: {f}")
    _render_qa(result.qa, report, fail_on)
```

**`capabilities.py` entry (append to `TOOLS` dict):**

```python
"migrate-legacy-data": Runtime.CLOUD,  # tool 2.4 — headless CSV output only
```

**Failing CLI test to add to `tests/envmon/test_legacy_migrator.py` (or a new `tests/test_cli_migrate_legacy.py`):**

```python
def test_migrate_legacy_data_in_help():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as cli
    result = CliRunner().invoke(cli, ["envmon", "--help"])
    assert "migrate-legacy-data" in result.output


def test_migrate_legacy_data_cli_happy(tmp_path):
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis as cli

    # Write minimal legacy CSV
    src = tmp_path / "legacy.csv"
    src.write_text(
        "WellID,SampleDate,Medium,LabID,Chemical,ResultValue,ReportedUnits\n"
        "MW-1,2026-04-01,GW,H281-MW1-001,Benzene,5.0,ug/L\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(
        "samples:\n"
        "  location_id: WellID\n"
        "  event_date:  SampleDate\n"
        "  matrix:      Medium\n"
        "  sample_id:   LabID\n"
        "results:\n"
        "  sample_id: LabID\n"
        "  analyte:   Chemical\n"
        "  result:    ResultValue\n"
        "  units:     ReportedUnits\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, [
        "envmon", "migrate-legacy-data",
        "--source", str(src),
        "--mapping", str(mapping),
        "--out-dir", str(tmp_path / "out"),
        "--event-id", "EVT-2026-04",
        "--site-id", "H281",
    ])
    assert result.exit_code == 0, result.output
    assert "1 row(s) migrated" in result.output
    assert (tmp_path / "out" / "samples.csv").exists()
    assert (tmp_path / "out" / "results.csv").exists()
```

**Steps:**
- [ ] Write CLI tests as shown above (add to existing test file or create `tests/test_cli_migrate_legacy.py`).
- [ ] Run CLI tests — expect failure (command not yet registered).
- [ ] Add `migrate-legacy-data` command to `autogis/adapters/cli.py`.
- [ ] Add `"migrate-legacy-data": Runtime.CLOUD` to `TOOLS` in `autogis/runtime/capabilities.py`.
- [ ] Run `python -m pytest tests/test_cli_migrate_legacy.py -q` (or relevant path) — expect pass.
- [ ] Run `python -m pytest -q` — expect no regressions.
- [ ] Commit: `feat(envmon): migrate-legacy-data CLI + capabilities registration (Tool 2.4)`

---

## Self-Review

**Spec coverage:**
- `LegacyMigrationConfig` dataclass: `source_path`, `mapping_yaml`, `output_dir`, `event_id`, `site_id` — Task 1
- `ColumnMapping` loaded from YAML, `from_dicts` for tests — Task 1
- `migrate_legacy_data(config) -> MigrationResult` — Task 1
- `MigrationResult`: `rows_migrated`, `rows_skipped`, `output_files`, `qa` — Task 1
- Reads CSV and XLSX via openpyxl — Task 1 (`_read_source`)
- Writes `samples.csv` + `results.csv` to `output_dir` — Task 1
- Unmapped column → `SEV_WARNING` (once per column) — Task 1 + test
- Missing required canonical field → `SEV_ERROR`, row skipped — Task 1 + test
- `event_id` written as `import_batch_id` — Task 1 + test
- `site_id` injected from config when omitted from mapping — Task 1 + test
- Sample deduplication — Task 1 + test
- Reference YAML mapping file — Task 2
- CLI: `--source`, `--mapping`, `--out-dir`, `--event-id`, `--site-id`, `--report` — Task 3
- `Runtime.CLOUD` registration — Task 3
- All core tests arcpy-free — throughout

**Placeholder scan:** No TBD/TODO. All code blocks are complete implementations.

**Type consistency:**
- `migrate_legacy_data` → `MigrationResult` — matches test assertions
- `output_files` → `list[Path]` — matched by `isinstance(p, Path)` test
- `QACollector` passed via `result.qa` — matches all QA record assertions
