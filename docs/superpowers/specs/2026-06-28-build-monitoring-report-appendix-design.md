# BuildMonitoringReportAppendix Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildMonitoringReportAppendix (Phase 5 / Tool 9.2)
**Priority:** MEDIUM-HIGH — report delivery milestone; saves 2–4 hours per event

---

## Problem

Every monitoring report includes an analytical data appendix: a formatted
multi-sheet Excel workbook with one sheet per analyte group showing all
results tabulated by well and event date, screening level comparison columns,
exceedance highlighting, and summary statistics (detection frequency,
min/max/avg). This workbook is currently assembled manually from the normalized
database — a 2–4 hour task per report cycle.

---

## Approach

**Chosen:** openpyxl workbook builder. Input: long-format `Env_AnalyticalResults`
CSV + optional screening levels YAML. Output: multi-sheet Excel with:
- One sheet per analyte group (VOC, SVOC, Metals, etc.)
- Columns: Well ID, then one date column per sampling event
- Conditional formatting: yellow for detected, red for exceedance (openpyxl
  rule objects, no arcpy)
- Summary row at bottom: detection frequency, max, median

**Rejected: Word/PDF output.** Word automation requires pywin32 (Windows-only).
Excel appendix is the regulatory standard and is editable by reviewers.

**Rejected: Template-based approach.** Template drift is a maintenance burden.
Programmatic generation from data is reproducible and format-consistent.

---

## Architecture

```
autogis/
  core/envmon/
    report_appendix_builder.py  ← NEW
  adapters/
    cli.py                      ← add build-report-appendix command (headless)
tests/envmon/
  test_report_appendix_builder.py ← NEW
```

---

## Public API (`report_appendix_builder.py`)

```python
@dataclass
class AppendixSheetSpec:
    sheet_name: str
    analyte_group: str       # e.g. "VOC", "Metals"
    analytes: list[str]      # ordered list for row layout
    screening_levels: dict[str, float]   # {analyte: value}
    units: str               # "ug/L"

@dataclass
class AppendixBuildResult:
    workbook_path: Path
    sheet_count: int
    well_count: int
    event_count: int
    qa: QACollector

def build_appendix_sheet_specs(
    result_rows: list[dict],
    screening_levels: dict[str, float] | None = None,
    group_map: dict[str, str] | None = None,  # {analyte: group}
) -> list[AppendixSheetSpec]:
    """Auto-partition analytes into groups; build one AppendixSheetSpec per group."""

def write_appendix_workbook(
    result_rows: list[dict],
    specs: list[AppendixSheetSpec],
    out_path: Path,
    *,
    site_id: str = "",
    event_dates: list[str] | None = None,
    nd_qualifier: str = "ND",
) -> AppendixBuildResult:
    """
    Build multi-sheet Excel appendix.
    Layout: rows = analytes, cols = wells (then date sub-cols).
    Conditional format: detected=yellow, exceedance=red.
    Summary stats row at bottom of each sheet.
    """
```

---

## Sheet Layout

```
                 MW-01            MW-02            MW-03
Analyte   Units  2026-01  2026-04  2026-01  2026-04  2026-01  2026-04
────────────────────────────────────────────────────────────────────
Benzene   ug/L   5.2      3.0      ND       ND       12.4*    8.1*
Toluene   ug/L   ND       8.5      2.1      ND       ND       ND
────────────────────────────────────────────────────────────────────
Detects   —      1/2      2/2      1/2      0/2      1/2      1/2
Max       —      5.2      8.5      2.1      ND       12.4     8.1
```

`*` = exceeds screening level (red cell fill)

---

## Conditional Formatting

- **Detected (non-ND):** `PatternFill(fgColor="FFFF99")` (yellow)
- **Exceedance:** `PatternFill(fgColor="FF9999")` (red), overrides yellow
- **ND:** no fill, text `"ND"`

Applied via `openpyxl.styles` (no arcpy).

---

## CLI Command

```
autogis envmon build-report-appendix \
  --results <env_results.csv> \
  [--screening-levels <screening.yaml>] \
  [--group-map <group_map.yaml>] \
  [--site <site_id>] \
  [--event-dates 2026-01-15,2026-04-15] \
  --out <appendix.xlsx> \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_report_appendix_builder.py` — arcpy-free:

1. `build_appendix_sheet_specs` groups analytes by `group_map` into separate specs
2. `write_appendix_workbook` produces xlsx with one sheet per analyte group
3. Sheet has correct wells as column groups
4. ND result → cell value "ND", no fill
5. Detected result → yellow fill
6. Exceedance (result > screening_level) → red fill
7. Summary row at bottom has detection frequency `"1/2"` format
8. `event_count` and `well_count` in result correct
