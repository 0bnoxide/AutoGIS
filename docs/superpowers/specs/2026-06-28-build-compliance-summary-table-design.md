# BuildComplianceSummaryTable Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildComplianceSummaryTable (Phase 3 / Tool 4.8)
**Priority:** MEDIUM — required for compliance status sections of annual reports

---

## Problem

Annual monitoring reports include a compliance status table: for each well and
each regulated analyte, was the analyte detected? Did it exceed the MCL? How
many events had exceedances? Is the trend improving or worsening? Currently
this table is built by copying values from event-by-event spreadsheets into a
Word or Excel template. With multi-year event histories and dozens of analytes
per site, the manual process takes hours and is error-prone.

---

## Approach

**Chosen:** Cross-event compliance matrix from long-format merged results.
Reads merged results CSV (from `merge-event-results`) + screening levels YAML.
For each `(LocationID, AnalyteName)` pair, computes:
- `ever_detected`: bool
- `ever_exceeded`: bool
- `exceedance_count` / `total_event_count`
- `trend`: improving | worsening | stable | insufficient_data
  (trend = linear slope sign over last N events; `insufficient_data` if < 3 events)
- `max_value`, `max_event_date`, `max_ratio` (max / MCL)

Outputs one openpyxl workbook with a compliance matrix sheet (wells × analytes)
plus a detail sheet (one row per location-analyte pair).

**Rejected: Requiring per-event files.** Works from the merged long-format CSV
produced by `merge-event-results`.

**Rejected: Including trend model uncertainty.** Simple sign-of-slope is
sufficient for compliance narrative; statistical tests add complexity without
proportional value for regulatory tables.

---

## Architecture

```
autogis/
  core/envmon/
    compliance_summary.py          ← NEW
  adapters/
    cli.py                         ← add build-compliance-table command (headless)
tests/envmon/
  test_compliance_summary.py       ← NEW
```

---

## Public API (`compliance_summary.py`)

```python
@dataclass
class ComplianceRecord:
    location_id: str
    analyte_name: str
    screening_level: float | None
    units: str
    ever_detected: bool
    ever_exceeded: bool
    detection_count: int
    exceedance_count: int
    total_event_count: int
    max_value: float | None
    max_event_date: str
    max_ratio: float | None       # max / MCL; None if no MCL
    trend: str                    # improving | worsening | stable | insufficient_data

@dataclass
class ComplianceSummaryResult:
    records: list[ComplianceRecord]
    well_count: int
    analyte_count: int
    locations_with_exceedances: int
    qa: QACollector

def compute_trend(values: list[float], dates: list[str]) -> str:
    """
    Simple linear trend from (date_ordinal, value) pairs.
    Returns 'improving' (negative slope), 'worsening' (positive), 'stable' (≈0),
    or 'insufficient_data' if fewer than 3 detected values.
    """

def build_compliance_summary(
    result_rows: list[dict],
    *,
    screening_levels: dict[str, float] | None = None,
    analytes: list[str] | None = None,
    wells: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    nd_qualifiers: frozenset = frozenset({"ND", "U", "BDL"}),
    min_events_for_trend: int = 3,
    qa: QACollector | None = None,
) -> ComplianceSummaryResult:

def write_compliance_workbook(
    result: ComplianceSummaryResult,
    out_path: Path,
    *,
    group_map: dict[str, str] | None = None,
) -> None:
    """Write matrix sheet + detail sheet. Matrix: wells×analytes cells show
    'ND' | numeric | '**' for exceedance. Color: green=ND, yellow=detect, red=exceed."""
```

---

## CLI Command

```
autogis envmon build-compliance-table \
  --results <merged_results.csv> \
  --screening-levels <sl.yaml> \
  --out <compliance_summary.xlsx> \
  [--analytes Benzene,Toluene] \
  [--date-from 2024-01-01] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_compliance_summary.py` — arcpy-free:

1. `compute_trend` with increasing values → `worsening`
2. `compute_trend` with decreasing values → `improving`
3. `compute_trend` with fewer than 3 points → `insufficient_data`
4. `build_compliance_summary` populates `ever_detected`, `ever_exceeded` correctly
5. `exceedance_count` equals count of rows where value > MCL
6. `max_ratio` = max_value / MCL for detected exceedances
7. `locations_with_exceedances` counts distinct wells with at least one exceedance
8. `write_compliance_workbook` produces xlsx with matrix sheet and detail sheet
