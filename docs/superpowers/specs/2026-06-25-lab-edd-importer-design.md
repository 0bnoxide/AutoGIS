# Lab EDD Importer Design

**Date:** 2026-06-25  
**Status:** Approved  
**Tool:** ImportLabEDD (2.3)  
**Priority:** HIGH

---

## Problem

Labs deliver Electronic Data Deliverables (EDDs) as flat CSV or two-tab XLSX files.
The existing import pipeline only handles Excel workbooks profiled via `ParserProfile` /
`SheetProfile`. There is no path to ingest lab EDDs without manual reformatting — a
time-consuming, error-prone step before every event import.

---

## Approach: Option A — `edd_importer.py` + `LabEDDProfile` config

New `edd_importer.py` in `core/envmon/` provides the parsing core. A `LabEDDProfile`
YAML config (parallel to `ParserProfile`) handles per-lab column mapping. The importer
reuses `result_parser.py` helpers and produces `gdb_schema.SampleRecord` +
`AnalyticalResultRecord` rows — the same types the existing `append_records_idempotent`
write path already consumes.

---

## Architecture

```
autogis/
  core/envmon/
    edd_profile.py       ← LabEDDProfile dataclass + YAML loader
    edd_importer.py      ← run_edd_import(): read → map → parse → write
    import_to_gdb.py     ← existing; no changes needed (append_records_idempotent reused)
  config/
    lab_profiles/        ← one YAML per lab  (e.g. testamerica.yaml)
  adapters/
    cli.py               ← add `import-edd` command
tests/envmon/
  test_edd_importer.py
  test_edd_profile.py
  fixtures/edd/          ← synthetic EDD CSV + XLSX files
```

**Data flow:**
```
EDD file + LabEDDProfile YAML
        ↓
  run_edd_import()
        ↓
  create_import_batch()              ← import_to_gdb.py (existing)
        ↓
  normalize_edd_rows()               ← edd_importer.py (new internal)
    ├─ parse_result_value()          ← result_parser.py (reused)
    ├─ _apply_qualifiers()           ← result_parser.py (reused, expose as semi-public)
    ├─ parse_excel_date()            ← result_parser.py (reused)
    ├─ normalize_analyte_name()      ← result_parser.py (reused)
    ├─ evaluate_screening()          ← result_parser.py (reused)
    └─ classify_display()            ← result_parser.py (reused)
        ↓
  append_records_idempotent()        ← import_to_gdb.py (existing, unchanged)
  finalize_batch()                   ← import_to_gdb.py (existing, unchanged)
  write_qa_to_gdb()                  ← import_to_gdb.py (existing, unchanged)
```

No arcpy anywhere in `core/`. GDB writes happen only through the existing adapter-layer
functions in `import_to_gdb.py`.

---

## Section 1: `LabEDDProfile` (`edd_profile.py`)

### Purpose

Maps lab-specific EDD column names to canonical AutoGIS field names. One YAML file
per lab, stored in `autogis/config/lab_profiles/`. Loaded via the existing `load_config()`
helper — same pattern as `ParserProfile.load()`.

### YAML structure

```yaml
# autogis/config/lab_profiles/testamerica.yaml
profile_id: testamerica
lab_name: "TestAmerica"
format: flat_csv          # flat_csv | two_tab_xlsx
date_format: "%m/%d/%Y"
encoding: "utf-8-sig"     # handles Windows BOM on exported CSVs

# Two-tab XLSX only — omit for flat_csv:
# sample_sheet: "Samples"
# result_sheet: "Results"

columns:
  # Required fields
  sample_id:    "LabID"          # str or list of alternates (first match wins)
  location_id:  "SysLocCode"
  event_date:   "CollDate"
  matrix:       "Medium"
  analyte:      "Chemical"
  result:       "Result"
  units:        "Unit"
  qualifier:    "Qualifier"      # separate qualifier column (not combined with result)
  reporting_limit: "RL"

  # Optional fields
  method:       "AnalytMeth"
  lab_sample_id: "LabID"
  depth_top_ft: "TopDepth"
  depth_bot_ft: "BotDepth"

matrix_map:               # EDD matrix value → canonical code (GW, SOIL, etc.)
  WS: GW
  WG: GW
  SO: SOIL
  SB: SOIL

nondetect_qualifiers: ["U", "UJ"]   # qualifiers that force is_nondetect=True
```

### `LabEDDProfile` dataclass

```python
@dataclass
class LabEDDProfile:
    profile_id: str
    lab_name: str
    format: str                 # "flat_csv" | "two_tab_xlsx"
    date_format: str
    encoding: str
    columns: dict[str, str | list[str]]   # field_name → col_name(s)
    matrix_map: dict[str, str]
    nondetect_qualifiers: list[str]
    sample_sheet: str = "Samples"         # two_tab_xlsx only
    result_sheet: str = "Results"         # two_tab_xlsx only
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "LabEDDProfile": ...

    def resolve_column(
        self, row: dict, field: str
    ) -> str | None:
        """Return the value for a canonical field from a CSV row dict.
        Tries each alternate column name in order. Returns None if missing."""
```

`resolve_column` emits no errors itself — callers decide severity. This matches the
`SheetProfile` convention where column resolution and QA record creation are separate.

### Validation

`validate_edd_profile(profile: LabEDDProfile, qa: QACollector)` — parallel to
`validate_parser_profile()` in `config_validation.py`. Checks required column names
are non-empty and that `format` is a known value.

---

## Section 2: Core Importer (`edd_importer.py`)

### Top-level entry point

```python
def run_edd_import(
    edd_path: Path,
    profile: LabEDDProfile,
    gdb_path: Path,
    site_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    event_date_override: date | None = None,
    batch_id: str | None = None,    # auto-generated UUID if None
) -> str:
    """Run a full EDD import. Returns the import batch_id."""
```

Follows the exact lifecycle of `run_import()` in `import_to_gdb.py`:

1. `create_import_batch(gdb_path, ...)` — creates `Env_ImportBatch` row
2. Read rows from EDD file (see Section 3)
3. `normalize_edd_rows(rows, profile, ...)` — produces `SampleRecord` + `AnalyticalResultRecord` lists + `QACollector`
4. `append_records_idempotent(gdb_path, "Env_Samples", samples)`
5. `append_records_idempotent(gdb_path, "Env_AnalyticalResults", results)`
6. `finalize_batch(gdb_path, batch_id, ...)`
7. `write_qa_to_gdb(gdb_path, qa, batch_id)`
8. Return `batch_id`

### Internal normalizer

```python
def normalize_edd_rows(
    rows: list[dict],
    profile: LabEDDProfile,
    site_id: str,
    batch_id: str,
    analyte_dictionary: dict,
    screening_levels: dict,
    qa: QACollector,
    event_date_override: date | None = None,
) -> tuple[list[SampleRecord], list[AnalyticalResultRecord]]:
```

**Per-row processing:**

1. Extract fields via `profile.resolve_column(row, field)` — missing required fields → `SEV_ERROR` QA record, row skipped
2. Parse date via `parse_excel_date()` — bad date → `SEV_WARNING`, use `event_date_override` if set
3. Map matrix via `profile.matrix_map` — unknown matrix → `SEV_WARNING`, preserved as-is
4. Parse result via `parse_result_value(result_str)` — handles blank, ND, `<value`, numeric
5. Apply separate qualifier via a thin inline helper (mirrors `_apply_qualifiers` logic) — EDD qualifier column overrides any qualifier embedded in result string
6. If qualifier in `profile.nondetect_qualifiers` → force `is_nondetect=True`, `is_detected=False`
7. Normalize analyte via `normalize_analyte_name()` — unknown analyte → `SEV_WARNING`
8. Evaluate screening via `evaluate_screening()`
9. Classify display via `classify_display()`
10. Construct `SampleRecord` and `AnalyticalResultRecord` — field mapping follows lines 151–224 of `table_normalizer.py` exactly

**Sample deduplication:** same `(site_id, location_id, sample_id, event_date)` tuple → one `SampleRecord`, multiple `AnalyticalResultRecord` rows.

**Error policy:** Row-level errors emit `QARecord` with `source_row` set. Importer never raises on bad data — it flags and continues, consistent with `normalize_matrix_table`.

### File reading

**flat_csv:** `csv.DictReader(open(path, encoding=profile.encoding))` — headers become row keys, works directly with `resolve_column`.

**two_tab_xlsx:** `openpyxl.load_workbook(path, read_only=True)` — load `profile.sample_sheet` and `profile.result_sheet`, build dicts from header row, join on `sample_id`. `openpyxl` is already a project dependency.

---

## Section 3: CLI (`adapters/cli.py`)

New command added to the existing `autogis` Click group:

```
autogis import-edd \
  --edd       tests/fixtures/edd/testamerica_q2.csv \
  --profile   testamerica \           # resolves to config/lab_profiles/testamerica.yaml
  --site      H281 \
  --gdb       /path/to/H281.gdb \
  [--event-date 2026-06-01]           # optional override if EDD lacks event date
```

**Behaviour:**
- Loads profile from `config/lab_profiles/{profile}.yaml`
- Loads analyte dictionary and screening levels from site config
- Calls `run_edd_import()`
- Prints summary: rows read, samples imported, results imported, QA warnings, QA errors
- Exits non-zero if any `SEV_ERROR` QA records produced

**Dry-run (future):** Omitting `--gdb` prints QA report only, no GDB write. Not in scope for this iteration — `--gdb` is required for now.

---

## Section 4: GDB Write Path

**No new functions needed.** The existing `append_records_idempotent` in `import_to_gdb.py`
is fully table-agnostic. The EDD importer calls it the same way the Excel normalizers do:

```python
append_records_idempotent(gdb_path, "Env_Samples", sample_records)
append_records_idempotent(gdb_path, "Env_AnalyticalResults", result_records)
```

`SampleRecord` and `AnalyticalResultRecord` from `gdb_schema.py` are the output types —
they map 1:1 to the existing GDB table schemas.

`import_to_gdb.py` is **not modified** — only called.

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Output record types | `gdb_schema.SampleRecord` + `AnalyticalResultRecord` | Only types `append_records_idempotent` accepts; `schema/envmon.EnvSample` has no callers |
| Write path | Call `append_records_idempotent` directly | Already table-agnostic; no new write function needed |
| Separate qualifier column | Call `parse_result_value` then apply qualifier inline | EDDs split result + qualifier; existing `_apply_qualifiers` handles this |
| Profile loader | `load_config()` (existing) | Consistent with `ParserProfile.load()` |
| GDB path required | Yes, for this iteration | No dry-run mode until `--gdb` omit path is added |

---

## Testing Strategy

- `tests/envmon/test_edd_profile.py` — `LabEDDProfile.load()`, `resolve_column()`, validation
- `tests/envmon/test_edd_importer.py` — `normalize_edd_rows()` with synthetic rows:
  - Nondetect (qualifier `U`)
  - Detected value
  - Blank result
  - Missing required column
  - Unknown analyte
  - Unknown matrix
  - Date parsing variants
  - Sample deduplication
- `tests/envmon/fixtures/edd/` — synthetic CSV + XLSX fixtures (no real lab data)
- All tests arcpy-free: `normalize_edd_rows()` takes plain dicts, no GDB needed
- `run_edd_import()` tested via integration test with a mock GDB (or skipped in arcpy-free suite)

---

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `autogis/core/envmon/edd_profile.py` | Create | `LabEDDProfile` + `validate_edd_profile` |
| `autogis/core/envmon/edd_importer.py` | Create | `run_edd_import` + `normalize_edd_rows` |
| `autogis/config/lab_profiles/` | Create dir + example YAML | `testamerica.yaml` as reference |
| `autogis/adapters/cli.py` | Modify | Add `import-edd` command |
| `autogis/core/envmon/result_parser.py` | Modify (minor) | Expose `_apply_qualifiers` as `apply_qualifiers` |
| `tests/envmon/test_edd_profile.py` | Create | |
| `tests/envmon/test_edd_importer.py` | Create | |
| `tests/envmon/fixtures/edd/` | Create | Synthetic CSV + XLSX fixtures |

**Not modified:** `import_to_gdb.py`, `gdb_schema.py`, `table_normalizer.py`

---

## Dependencies

No new packages. Uses: `csv` (stdlib), `openpyxl` (already in project), `PyYAML` (already in project).
