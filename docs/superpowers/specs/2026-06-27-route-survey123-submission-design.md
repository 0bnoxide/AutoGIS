# RouteSurvey123Submission Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** RouteSurvey123Submission (Phase 2.8 / Tool 7.1b)
**Priority:** HIGH (field-to-database pipeline; closes the Survey123 form → GDB loop)

---

## Problem

Survey123 field submissions arrive as JSON payloads (via ArcGIS webhook or exported
CSV from AGOL). There is no path from a Survey123 submission to the GDB tables
(`Env_WaterLevels`, `Env_Samples`, `Env_AnalyticalResults`). Currently the field
crew's data has to be re-entered or processed through Excel workbooks — the very
problem `BuildSurvey123XLSFormFromConfig` was designed to shortcut.

---

## Approach

**Chosen:** New `normalize_survey123.py` maps a Survey123 JSON payload (or CSV export
row) to the same typed record dicts that `import_to_gdb.py` already writes via
`append_records_idempotent`. The GDB write layer (`create_edd_import_batch`,
`append_records_idempotent`, `finalize_batch`, `write_qa_to_gdb`) is reused unchanged.
The normalize tier is arcpy-free and fully testable.

Two input modes:
- **Webhook JSON** — single submission dict from ArcGIS webhook POST body
- **AGOL CSV export** — batch CSV of Survey123 submissions (column names from the XLSForm)

**Rejected: Reusing normalize_*.py functions.** Those functions are tightly coupled to
`ProfileWorkbookReader` (openpyxl sheet access). The Survey123 JSON/CSV structure maps
field names directly — no sheet abstraction needed.

**Rejected: Direct AGOL API polling.** Requires credentials and network; out of scope
for the local pipeline. The CSV export path covers the immediate need.

---

## Architecture

```
autogis/
  core/envmon/
    normalize_survey123.py   ← NEW (arcpy-free)
  adapters/
    cli.py                   ← add route-survey123 command (LOCAL — needs arcpy to write GDB)
tests/envmon/
  test_normalize_survey123.py ← NEW, arcpy-free
```

---

## Public API (`normalize_survey123.py`)

```python
@dataclass
class Survey123Field:
    """Maps XLSForm field names to target GDB fields."""
    well_id_field: str = "WellID"
    sampling_date_field: str = "SamplingDate"
    matrix_field: str = "Matrix"
    sampled_by_field: str = "SampledBy"
    coc_number_field: str = "COCNumber"
    dtw_field: str = "DepthToWater_ft"

def normalize_survey123_submission(
    payload: dict,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Map one Survey123 submission dict to (water_level_records, sample_records).
    Returns typed dicts in the same format as normalize_groundwater / normalize_*.
    Water level records: subset matching Env_WaterLevels schema.
    Sample records: subset matching Env_Samples schema (one row; analytes in separate dicts).
    """

def load_survey123_csv_submissions(
    path: Path,
    site_id: str,
    batch_id: str,
    qa: QACollector,
    field_map: Optional[Survey123Field] = None,
) -> tuple[list[dict], list[dict]]:
    """Batch: read CSV export of Survey123 submissions, normalize all rows."""
```

---

## Data Flow

```
route-survey123 <csv_or_json> --site H281 --gdb H281.gdb
    │
    ├─ if JSON: parse single submission
    │   normalize_survey123_submission(payload) → (wl_records, sample_records)
    │
    ├─ if CSV: iterate rows
    │   load_survey123_csv_submissions(path) → (wl_records, sample_records)
    │
    └─ LOCAL (arcpy) write layer:
       create_edd_import_batch(gdb, batch_id, site_id, ...)
       append_records_idempotent(gdb, "Env_WaterLevels", wl_records, ...)
       append_records_idempotent(gdb, "Env_Samples", sample_records, ...)
       finalize_batch(gdb, batch_id, ...)
       write_qa_to_gdb(gdb, qa, batch_id)
```

---

## Field Mapping

Survey123 JSON payload keys → GDB fields:

| Survey123 field | Env_WaterLevels / Env_Samples field |
|---|---|
| `WellID` | `LocationID` |
| `SamplingDate` | `SampleDate` / `MeasurementDate` |
| `DepthToWater_ft` | `DTW_ft` → GWE computed |
| `Matrix` | `Matrix` |
| `SampledBy` | `CollectedBy` / `SampledBy` |
| `COCNumber` | `COCNumber` |

GWE computed as: `GWE_ft = TOCElevation_ft - DTW_ft` (looks up TOCElevation from
`MonitoringWells` by `LocationID`; logs WARNING if well not found).

---

## Test Strategy

`tests/envmon/test_normalize_survey123.py` — all arcpy-free:

1. Minimal JSON payload → returns water_level_record with `LocationID`, `DTW_ft`
2. Missing `WellID` → QA ERROR `missing_required_field`
3. Missing `DepthToWater_ft` → water level record omitted; no crash
4. CSV batch with two rows → two water level records
5. Custom `Survey123Field` map overrides column names
6. `normalize_survey123_submission` with full payload → sample_record has `Matrix`, `SampleDate`
7. Invalid date string → QA WARNING `invalid_date`; record date set to None
