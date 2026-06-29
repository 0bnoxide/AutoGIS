# GenerateRegulatorySubmissionTables Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateRegulatorySubmissionTables (Phase 5 / Tool 11.2)
**Priority:** MEDIUM — required for permit reports and regulatory submissions

---

## Problem

Regulatory agencies require analytical results in specific table formats:
one row per location, one column per analyte, compared against MCLs/RSLs,
with footnotes for detections, exceedances, and non-detects. These are built
by hand in Word or Excel and are error-prone, inconsistent, and require
re-doing for every report cycle. The envmon toolset has max-result datasets
and exceedance data but no tool to format them as submission-ready tables.

---

## Approach

**Chosen:** openpyxl regulatory table workbook. Reads a long-format results
CSV (or max-result CSV from `build-max-result-dataset`) and a screening-levels
YAML. Pivots into regulatory table format: wells as rows, analytes as columns,
cell value = max result or "ND", comparison vs MCL in adjacent column.
Footnotes legend on a separate sheet. One sheet per analyte group.

**Rejected: PDF output.** PDF requires reportlab or WeasyPrint — new dependencies.
Excel output is editable and agencies accept it; `generate-boring-pdfs` handles
PDF conversion for other tools.

**Rejected: HTML table.** HTML output isn't the agency's preferred format
and opens cross-browser rendering questions.

---

## Architecture

```
autogis/
  core/envmon/
    regulatory_table_builder.py    ← NEW
  adapters/
    cli.py                         ← add generate-reg-tables command (headless)
tests/envmon/
  test_regulatory_table_builder.py ← NEW
```

---

## Public API (`regulatory_table_builder.py`)

```python
@dataclass
class RegulatoryTableSpec:
    analyte_group: str
    analytes: list[str]           # ordered column list
    screening_levels: dict[str, float]   # analyte → MCL/RSL
    units: dict[str, str]         # analyte → unit string
    footnotes: dict[str, str]     # letter → text (auto-populated)

@dataclass
class RegulatoryTableResult:
    workbook_path: Path
    group_count: int
    well_count: int
    exceedance_count: int
    qa: QACollector

def build_regulatory_table_specs(
    result_rows: list[dict],
    group_map: dict[str, str] | None = None,
    screening_levels: dict[str, float] | None = None,
) -> list[RegulatoryTableSpec]:
    """Partition analytes into groups; gather MCLs and units per group."""

def write_regulatory_workbook(
    result_rows: list[dict],
    specs: list[RegulatoryTableSpec],
    out_path: Path,
    *,
    site_id: str = "",
    event_label: str = "",
    nd_text: str = "ND",
    exceed_marker: str = "**",
) -> RegulatoryTableResult:
    """
    Build pivot table per spec:
    - Row 1: agency header (site, event, date generated)
    - Row 2: analyte names
    - Row 3: MCL values
    - Row 4+: one row per well; ND or numeric value; exceed_marker appended if > MCL
    - Trailing sheet: Footnotes legend
    """
```

---

## Table Layout (per sheet)

```
Site: H281-Eureka                     Event: Q1-2026        Generated: 2026-06-28
                 Benzene   Toluene   Ethylbenzene   Xylenes
MCL (ug/L)       5.0       1000.0    700.0          10000.0
MW-01            12.0**    ND        ND             ND
MW-02            ND        ND        ND             ND
MW-03            3.2       85.0      ND             250.0
** = Exceeds MCL
```

---

## CLI Command

```
autogis envmon generate-reg-tables \
  --results <long_results.csv> \
  --screening-levels <sl.yaml> \
  [--group-map <groups.yaml>] \
  [--site <site_id>] \
  [--event-label <label>] \
  --out <regulatory_tables.xlsx> \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_regulatory_table_builder.py` — arcpy-free:

1. `build_regulatory_table_specs` groups analytes by group_map
2. `write_regulatory_workbook` produces xlsx at out_path
3. MCL values appear in header row of each sheet
4. ND cells contain `nd_text` string
5. Exceedance cells contain `exceed_marker` suffix
6. `exceedance_count` correct in result
7. Missing screening level → INFO in QA (no crash)
8. Footnotes sheet present in workbook
