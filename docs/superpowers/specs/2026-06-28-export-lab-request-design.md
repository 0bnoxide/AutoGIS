# ExportLabAnalyticalRequest Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** ExportLabAnalyticalRequest (Phase 2 / Tool 2.11)
**Priority:** MEDIUM — reduces pre-event lab coordination overhead; eliminates COC transcription errors

---

## Problem

Before each sampling event, the project manager emails the lab a list of wells
to be sampled, the analyte groups required for each well, the matrix (groundwater,
soil, etc.), the requested turnaround time, and the billing project code. This is
done manually from the sampling event plan in Word or by forwarding a PDF. Labs
frequently receive ambiguous requests and call back for clarification. The
sampling event plan (from `create-sampling-event`) already contains all the
information needed — it just needs to be formatted for lab submission.

---

## Approach

**Chosen:** openpyxl lab request workbook generated from the sampling event plan
CSV. One sheet per lab (or single sheet if one lab), with columns the lab expects:
`SampleID`, `Matrix`, `ContainerType`, `Preservative`, `AnalyteGroup`,
`AnalyteList`, `TurnaroundDays`, `ProjectCode`. A second sheet lists analytes
per group (expanded from the analyte groups YAML) so the lab knows exactly what
to analyze. Tab-separated and CSV export options for labs that reject Excel.

**Rejected: Email automation.** Email sending is out of scope for the headless
core. The tool produces the file; the analyst attaches it to an email.

**Rejected: Lab-specific template matching.** Each lab has different column
names and order. A configurable column-mapping YAML makes this extensible
without hardcoding per-lab formats.

---

## Architecture

```
autogis/
  core/envmon/
    lab_request_exporter.py       ← NEW
  adapters/
    cli.py                        ← add export-lab-request command (headless)
tests/envmon/
  test_lab_request_exporter.py    ← NEW
```

---

## Public API (`lab_request_exporter.py`)

```python
@dataclass
class LabRequestRow:
    sample_id: str
    location_id: str
    matrix: str
    analyte_group: str
    analyte_list: str       # comma-separated analyte names
    container_type: str
    preservative: str
    hold_time_days: int
    turnaround_days: int
    project_code: str
    collection_date: str
    notes: str

@dataclass
class LabRequestResult:
    workbook_path: Path
    sample_count: int
    analyte_group_count: int
    qa: QACollector

def build_lab_request_rows(
    plan_rows: list[dict],           # from event plan CSV (SampleID, LocationID, ...)
    analyte_groups: dict,            # group_name → {analytes: [...], container, ...}
    *,
    project_code: str = "",
    turnaround_days: int = 5,
) -> list[LabRequestRow]:
    """Expand plan rows with analyte list from groups config."""

def write_lab_request_workbook(
    rows: list[LabRequestRow],
    out_path: Path,
    *,
    site_id: str = "",
    event_date: str = "",
    column_map: dict[str, str] | None = None,  # internal → lab column name
) -> LabRequestResult:
    """Write openpyxl workbook: Sheet 1 = sample request, Sheet 2 = analyte list."""

def write_lab_request_csv(rows: list[LabRequestRow], out_path: Path) -> None:
    """Write flat CSV for labs that don't accept Excel."""
```

---

## CLI Command

```
autogis envmon export-lab-request \
  --plan <sampling_event_plan.csv> \
  --analyte-groups <groups.yaml> \
  --out <lab_request.xlsx> \
  [--project-code <code>] \
  [--turnaround 5] \
  [--site <site_id>] \
  [--csv-also <lab_request.csv>] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_lab_request_exporter.py` — arcpy-free:

1. `build_lab_request_rows` produces one row per plan entry
2. `analyte_list` column contains comma-separated analytes from groups config
3. `hold_time_days` carried from groups config
4. `write_lab_request_workbook` produces xlsx at out_path
5. Sheet 1 has `SampleID` column
6. Sheet 2 lists analytes per group
7. `write_lab_request_csv` produces readable CSV
8. `column_map` renames columns in output workbook
