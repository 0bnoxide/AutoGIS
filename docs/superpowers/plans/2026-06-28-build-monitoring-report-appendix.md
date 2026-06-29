# BuildMonitoringReportAppendix (9.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `build_report_appendix()` — compile the standard monitoring report appendix (analytical summary tables, exceedance summary, trend vs previous event, data gaps, QA notes) into a single multi-sheet XLSX workbook, headless (openpyxl only, no arcpy).

**Architecture:** A new `autogis/core/envmon/build_report_appendix.py` module assembles a multi-sheet XLSX workbook by reusing existing table-builder functions from `export_summary_tables.py` (exposed as public aliases in Task 1) and the `ComparisonRecord` / `DataGapRecord` dataclasses from existing modules. A new `autogis envmon build-report-appendix` CLI command reads optional CSV inputs and invokes the core function. All code is arcpy-free and imports cleanly without ArcGIS installed.

**Tech Stack:**
- `openpyxl` (already in the stack — used by `export_summary_tables`, `export_summary`). Chosen over `python-docx` (no narrative sections required in the appendix) and `reportlab`/WeasyPrint (neither is in the existing dependency stack). Pure Python, zero OS/GUI dependency.
- Standard library: `csv`, `datetime`, `dataclasses`, `pathlib`

## Global Constraints

- `autogis/core/` and `autogis/adapters/` MUST import with neither `arcpy` nor `arcgis` present. Do not add either to any `import` statement in the new module.
- Run tests with `python -m pytest -q`.
- Config (`SiteConfig`) is canonical in `autogis/core/common/config.py`. Do not duplicate it.
- `build_report_appendix()` is a pure headless function. It never touches a GDB, calls arcpy, or requires a network.
- **Scope (what this tool is):** Compiles *existing* analytical records, comparison records, data-gap records, and QA collector output into one deliverable XLSX. The appendix is the report-ready compiled artifact.
- **Scope (what this tool is NOT):**
  - Does not duplicate logic from `export_summary_tables.py` — reuses its builders.
  - Does not generate narrative Markdown text — that is `generate_event_report.py`.
  - Does not produce PDF or DOCX (those can be added later with `python-docx` or `reportlab` as a separate follow-on).
  - Does not replace `export-report-format-summary-tables` (the existing three-sheet exporter stays as-is).
- **Assumption:** All optional inputs (`comparison_records`, `gap_records`, `rpd_qa_rows`) may be `None`. The appendix builds successfully with only analytical `records` provided; optional inputs add optional sheets.
- **Assumption:** `rpd_qa_rows` is a `list[dict]` (raw CSV rows), matching the convention established in `generate_event_report.py`. Column names follow that module's fallback pattern (`"severity"`, `"location_id"`/`"LocationID"`, `"analyte"`/`"AnalyteName"`, `"message"`/`"Message"`).

---

### Task 1: Expose private table builders from `export_summary_tables` as public API

The functions `_build_current_event`, `_build_gw_by_event`, `_build_soil_by_depth`, and `_apply_sheet_style` in `export_summary_tables.py` are private. `build_report_appendix.py` needs to call them to embed their output as sheets in the larger workbook (rather than writing a separate file). This task adds four public aliases so the inter-module import is explicit and reviewable.

**Files:**
- Modify: `autogis/core/envmon/export_summary_tables.py` — append 4 alias lines
- Test: `tests/envmon/test_export_summary_tables.py` — append 5 new tests

**Interfaces:**
- Produces:
  - `build_current_event_table(records) -> (headers: list, rows: list[list], exc_coords: set[tuple[int,int]])`
  - `build_gw_by_event_table(records) -> (headers, rows, exc_coords)`
  - `build_soil_by_depth_table(records) -> (headers, rows, exc_coords)`
  - `apply_sheet_style(ws, exceedance_coords, header_row=1) -> None`

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_export_summary_tables.py`:

```python
# ---------------------------------------------------------------------------
# Task 1: Public alias imports
# ---------------------------------------------------------------------------

def test_build_current_event_table_importable():
    from autogis.core.envmon.export_summary_tables import build_current_event_table
    assert callable(build_current_event_table)


def test_build_gw_by_event_table_importable():
    from autogis.core.envmon.export_summary_tables import build_gw_by_event_table
    assert callable(build_gw_by_event_table)


def test_build_soil_by_depth_table_importable():
    from autogis.core.envmon.export_summary_tables import build_soil_by_depth_table
    assert callable(build_soil_by_depth_table)


def test_apply_sheet_style_importable():
    from autogis.core.envmon.export_summary_tables import apply_sheet_style
    assert callable(apply_sheet_style)


def test_build_current_event_table_returns_correct_tuple_shape():
    from datetime import date
    from autogis.core.envmon.export_summary_tables import build_current_event_table
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    r = AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW", LocationID="MW-01",
        SampleID="S1", ParentSampleID="", SampleDate=date(2026, 4, 1),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="8260",
        AnalyteName="TCE", AnalyteCanonicalName="TCE", AnalyteAbbreviation="TCE",
        ResultRawText="5.0", ResultNumeric=5.0, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=None,
        ScreeningLevelSource="", ExceedsScreeningLevel=0, DisplayText="5.0 ug/L",
    )
    headers, rows, exc_coords = build_current_event_table([r])
    assert isinstance(headers, list)
    assert "LocationID" in headers
    assert isinstance(rows, list)
    assert isinstance(exc_coords, set)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_export_summary_tables.py -k "importable or returns_correct_tuple" -v
```

Expected: 5 failures — `ImportError: cannot import name 'build_current_event_table'`

- [ ] **Step 3: Append public aliases to `export_summary_tables.py`**

Append these four lines at the very end of `autogis/core/envmon/export_summary_tables.py`:

```python
# Public aliases — used by build_report_appendix to embed sheets into a larger workbook
build_current_event_table = _build_current_event
build_gw_by_event_table = _build_gw_by_event
build_soil_by_depth_table = _build_soil_by_depth
apply_sheet_style = _apply_sheet_style
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_export_summary_tables.py -v
```

Expected: all tests PASS (including pre-existing ones).

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

Expected: all tests pass.

```bash
git add autogis/core/envmon/export_summary_tables.py tests/envmon/test_export_summary_tables.py
git commit -m "feat(envmon): expose private table builders as public aliases in export_summary_tables"
```

---

### Task 2: Core module scaffold — `AppendixManifest`, `build_report_appendix()`, Cover sheet, analytical sheets

This task creates the module file and implements the skeleton: the `AppendixManifest` return type, the main `build_report_appendix()` function, the Cover sheet, and the three analytical sheets (Current Event / GW by Event / Soil by Depth). Tasks 3–6 fill in the four stub functions (`_write_exceedance_sheet`, `_write_trend_sheet`, `_write_gaps_sheet`, `_write_qa_notes_sheet`) that are defined but empty here.

**Files:**
- Create: `autogis/core/envmon/build_report_appendix.py`
- Create: `tests/envmon/test_build_report_appendix.py`

**Interfaces:**
- Consumes: `build_current_event_table`, `build_gw_by_event_table`, `build_soil_by_depth_table`, `apply_sheet_style` from `export_summary_tables` (Task 1); `ComparisonRecord` from `compare_events`; `DataGapRecord` from `data_gaps`; `AnalyticalResultRecord` from `gdb_schema`; `QACollector` from `common.qa`
- Produces: `AppendixManifest`, `build_report_appendix(records, output_path, *, site_id, event_id, comparison_records, gap_records, rpd_qa_rows, generated_date, qa) -> AppendixManifest`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_build_report_appendix.py`:

```python
"""Tests for build_report_appendix module."""
from __future__ import annotations

from datetime import date

import openpyxl
import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.build_report_appendix import (
    AppendixManifest,
    build_report_appendix,
)
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _r(
    LocationID: str = "MW-01",
    AnalyteCanonicalName: str = "TCE",
    SampleDate: date = None,
    DisplayText: str = "5.0 ug/L",
    ExceedsScreeningLevel: int = 0,
    Matrix: str = "GW",
) -> AnalyticalResultRecord:
    return AnalyticalResultRecord(
        ImportBatchID="BATCH1",
        SiteID="SITE1",
        Matrix=Matrix,
        LocationID=LocationID,
        SampleID=f"S_{LocationID}_{AnalyteCanonicalName}",
        ParentSampleID="",
        SampleDate=SampleDate or date(2026, 4, 1),
        DepthTop_ft=None,
        DepthBottom_ft=None,
        DepthIntervalText="0-2 ft" if Matrix == "SOIL" else "",
        AnalyticalGroup="VOC",
        MethodGroup="EPA8260",
        AnalyteName=AnalyteCanonicalName,
        AnalyteCanonicalName=AnalyteCanonicalName,
        AnalyteAbbreviation=AnalyteCanonicalName[:3],
        ResultRawText=DisplayText,
        ResultNumeric=5.0,
        ReportingLimit=None,
        DetectionLimit=None,
        Units="ug/L",
        Qualifier="",
        IsNonDetect=0,
        IsDetected=1,
        IsEstimated=0,
        IsDiluted=0,
        IsNotAnalyzed=0,
        IsNotSampled=0,
        IsNotMeasured=0,
        ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL",
        ExceedsScreeningLevel=ExceedsScreeningLevel,
        DisplayText=DisplayText,
    )


_GW_RECORDS = [
    _r("MW-01", "TCE"),
    _r("MW-02", "TCE"),
    _r("MW-01", "Benzene"),
]


# ---------------------------------------------------------------------------
# Task 2: Core scaffold tests
# ---------------------------------------------------------------------------

def test_build_report_appendix_returns_manifest(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert isinstance(manifest, AppendixManifest)


def test_output_file_created(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert out.exists()


def test_manifest_fields_populated(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.site_id == "SITE1"
    assert manifest.event_id == "2026Q2"
    assert isinstance(manifest.generated, date)
    assert manifest.output_path == out


def test_generated_date_defaults_to_today(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.generated == date.today()


def test_generated_date_override(tmp_path):
    out = tmp_path / "appendix.xlsx"
    fixed = date(2026, 1, 15)
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        generated_date=fixed,
        qa=QACollector(),
    )
    assert manifest.generated == fixed


def test_cover_sheet_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Cover" in wb.sheetnames


def test_cover_sheet_is_first(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames[0] == "Cover"


def test_cover_sheet_contains_site_and_event(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["Cover"]
    all_values = [str(ws.cell(r, c).value or "") for r in range(1, 15) for c in range(1, 3)]
    assert any("SITE1" in v for v in all_values)
    assert any("2026Q2" in v for v in all_values)


def test_analytical_sheets_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Current Event" in wb.sheetnames
    assert "GW by Event" in wb.sheetnames


def test_soil_sheet_present_when_soil_records_provided(tmp_path):
    out = tmp_path / "appendix.xlsx"
    records = _GW_RECORDS + [_r("B-01", "TPH", Matrix="SOIL")]
    build_report_appendix(
        records, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Soil by Depth" in wb.sheetnames


def test_soil_sheet_absent_when_no_soil_records(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Soil by Depth" not in wb.sheetnames


def test_sheet_names_in_manifest_match_saved_workbook(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert set(manifest.sheet_names) == set(wb.sheetnames)


def test_n_exceedances_zero_when_none(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.n_exceedances == 0


def test_n_exceedances_counted(tmp_path):
    out = tmp_path / "appendix.xlsx"
    records = [
        _r("MW-01", "TCE", ExceedsScreeningLevel=1),
        _r("MW-02", "TCE", ExceedsScreeningLevel=0),
        _r("MW-01", "Benzene", ExceedsScreeningLevel=1),
    ]
    manifest = build_report_appendix(
        records, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.n_exceedances == 2


def test_n_gaps_zero_when_no_gap_records(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.n_gaps == 0


def test_output_parent_dir_created_automatically(tmp_path):
    out = tmp_path / "nested" / "subdir" / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert out.exists()
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all FAIL — `ModuleNotFoundError: No module named 'autogis.core.envmon.build_report_appendix'`

- [ ] **Step 3: Create `autogis/core/envmon/build_report_appendix.py`**

```python
"""Build the standard monitoring report appendix — compiled multi-sheet XLSX bundle.

Headless: openpyxl only, no arcpy. Entry point: build_report_appendix().

Reuses table builders from export_summary_tables (public aliases added in that
module) for the Current Event / GW by Event / Soil by Depth sheets, then adds
Exceedances, Trend Summary (optional), Data Gaps (optional), and QA Notes sheets.

Scope: this module compiles existing data into a single deliverable. It does NOT:
  - Duplicate logic from export_summary_tables
  - Generate narrative Markdown text (see generate_event_report)
  - Require arcpy or any ArcGIS runtime
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from .compare_events import ComparisonRecord
from .data_gaps import DataGapRecord
from .export_summary_tables import (
    apply_sheet_style,
    build_current_event_table,
    build_gw_by_event_table,
    build_soil_by_depth_table,
)
from .gdb_schema import AnalyticalResultRecord
from ..common.logging import get_logger
from ..common.qa import QACollector, SEV_INFO

LOG = get_logger(__name__)

_BOLD = Font(bold=True)
_TITLE_FONT = Font(bold=True, size=13)
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="366092")
_RED_FILL = PatternFill(fill_type="solid", fgColor="FFCCCC")
_YELLOW_FILL = PatternFill(fill_type="solid", fgColor="FFF2CC")
_MAX_COL_WIDTH = 40

_SHEET_DESCRIPTIONS = {
    "Current Event": "Latest sample results per well (current event only)",
    "GW by Event": "Groundwater results by location/analyte across all events",
    "Soil by Depth": "Soil results by location and depth interval",
    "Exceedances": "All screening-level exceedances for this event",
    "Trend Summary": "Trend vs previous monitoring event",
    "Data Gaps": "Missing wells or analytes vs expected schedule",
    "QA Notes": "Build-time QA messages and RPD QA errors",
}


@dataclass
class AppendixManifest:
    site_id: str
    event_id: str
    generated: date
    output_path: Path
    sheet_names: List[str]
    n_exceedances: int
    n_gaps: int
    n_rpd_errors: int


def _write_sheet_from_table(wb: Workbook, sheet_name: str,
                            headers: list, rows: list, exc_coords: set) -> None:
    ws = wb.create_sheet(sheet_name)
    ws.append(headers)
    for row in rows:
        ws.append(row)
    apply_sheet_style(ws, exc_coords)


def _build_cover_sheet(wb: Workbook, site_id: str, event_id: str,
                       generated: date, content_sheet_names: List[str]) -> None:
    """Insert Cover as the first sheet with site/event metadata and a sheet ToC."""
    ws = wb.create_sheet("Cover", 0)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 50

    ws.append(["Monitoring Report Appendix"])
    ws["A1"].font = _TITLE_FONT

    ws.append([])
    ws.append(["Site", site_id])
    ws.append(["Event", event_id])
    ws.append(["Generated", generated.isoformat()])
    ws.append([])
    ws.append(["Sheet", "Contents"])

    for cell in [ws["A3"], ws["A4"], ws["A5"], ws["A7"]]:
        cell.font = _BOLD

    for name in content_sheet_names:
        desc = _SHEET_DESCRIPTIONS.get(name, "")
        ws.append([name, desc])


def build_report_appendix(
    records: List[AnalyticalResultRecord],
    output_path: Path,
    *,
    site_id: str,
    event_id: str,
    comparison_records: Optional[List[ComparisonRecord]] = None,
    gap_records: Optional[List[DataGapRecord]] = None,
    rpd_qa_rows: Optional[List[dict]] = None,
    generated_date: Optional[date] = None,
    qa: Optional[QACollector] = None,
) -> AppendixManifest:
    """Compile the standard monitoring report appendix into one XLSX workbook.

    Args:
        records: AnalyticalResultRecord list for the event/site.
        output_path: Destination .xlsx path (parent directories created as needed).
        site_id: Site identifier for Cover and labelling.
        event_id: Event identifier (e.g. "2026Q2") for Cover and labelling.
        comparison_records: ComparisonRecord list from compare_events. When
            provided, a 'Trend Summary' sheet is added.
        gap_records: DataGapRecord list from identify_data_gaps. When provided,
            a 'Data Gaps' sheet is added.
        rpd_qa_rows: List of dicts from evaluate-rpd-qa CSV export. Columns used:
            'severity', 'location_id'/'LocationID', 'analyte'/'AnalyteName',
            'message'/'Message'. Rows appear in 'QA Notes' sheet.
        generated_date: Override today's date stamp (default: date.today()).
        qa: QACollector for build-time messages (default: new collector).

    Returns:
        AppendixManifest with output path, sheet inventory, and key counts.
    """
    qa = qa or QACollector()
    generated = generated_date or date.today()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_exceedances = sum(1 for r in records if r.ExceedsScreeningLevel == 1)
    n_gaps = len(gap_records) if gap_records else 0
    n_rpd_errors = sum(
        1 for row in (rpd_qa_rows or [])
        if str(row.get("severity", "")).upper() == "ERROR"
    )

    wb = Workbook()
    wb.remove(wb.active)  # remove the default empty sheet

    # --- Analytical sheets (reuse existing builders) ---
    soil_records = [r for r in records if r.Matrix == "SOIL"]

    headers, rows, exc_coords = build_current_event_table(records)
    _write_sheet_from_table(wb, "Current Event", headers, rows, exc_coords)

    headers, rows, exc_coords = build_gw_by_event_table(records)
    _write_sheet_from_table(wb, "GW by Event", headers, rows, exc_coords)

    if soil_records:
        headers, rows, exc_coords = build_soil_by_depth_table(records)
        _write_sheet_from_table(wb, "Soil by Depth", headers, rows, exc_coords)
    else:
        qa.add(SEV_INFO, "soil_absent",
               "No SOIL records — 'Soil by Depth' sheet omitted.")

    # --- Summary/QA sheets (Tasks 3–6 implement these stubs) ---
    _write_exceedance_sheet(wb, records)

    if comparison_records:
        _write_trend_sheet(wb, comparison_records)

    if gap_records:
        _write_gaps_sheet(wb, gap_records)

    _write_qa_notes_sheet(wb, qa, rpd_qa_rows or [])

    # --- Cover (inserted at position 0 after all content sheets are built) ---
    content_sheet_names = list(wb.sheetnames)
    _build_cover_sheet(wb, site_id, event_id, generated, content_sheet_names)

    wb.save(output_path)

    final_sheet_names = list(wb.sheetnames)
    manifest = AppendixManifest(
        site_id=site_id,
        event_id=event_id,
        generated=generated,
        output_path=output_path,
        sheet_names=final_sheet_names,
        n_exceedances=n_exceedances,
        n_gaps=n_gaps,
        n_rpd_errors=n_rpd_errors,
    )
    qa.add(SEV_INFO, "appendix_complete",
           f"Wrote {len(final_sheet_names)} sheet(s) to {output_path}; "
           f"{n_exceedances} exceedance(s), {n_gaps} gap(s), "
           f"{n_rpd_errors} RPD error(s).")
    LOG.info("build_report_appendix: %s sheets -> %s",
             len(final_sheet_names), output_path)
    return manifest


# ---------------------------------------------------------------------------
# Sheet-writer stubs — implemented in Tasks 3–6
# ---------------------------------------------------------------------------

def _write_exceedance_sheet(wb: Workbook,
                            records: List[AnalyticalResultRecord]) -> None:
    """Add 'Exceedances' sheet — all ExceedsScreeningLevel==1 rows. (Task 3)"""


def _write_trend_sheet(wb: Workbook,
                       comparison_records: List[ComparisonRecord]) -> None:
    """Add 'Trend Summary' sheet from ComparisonRecord list. (Task 4)"""


def _write_gaps_sheet(wb: Workbook,
                      gap_records: List[DataGapRecord]) -> None:
    """Add 'Data Gaps' sheet from DataGapRecord list. (Task 5)"""


def _write_qa_notes_sheet(wb: Workbook, qa: QACollector,
                          rpd_qa_rows: List[dict]) -> None:
    """Add 'QA Notes' sheet combining build QA and RPD QA rows. (Task 6)"""
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all 17 tests PASS. (The stub functions are syntactically valid empty functions; the Exceedances/QA Notes sheets won't exist yet — that's expected and those tests don't check for them until Tasks 3–6.)

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

Expected: all tests pass.

```bash
git add autogis/core/envmon/build_report_appendix.py tests/envmon/test_build_report_appendix.py
git commit -m "feat(envmon): build_report_appendix scaffold — AppendixManifest, Cover, analytical sheets"
```

---

### Task 3: Exceedances sheet

Implement `_write_exceedance_sheet` in `build_report_appendix.py`. The sheet lists every record where `ExceedsScreeningLevel == 1`, sorted by `LocationID` then `AnalyteCanonicalName`. All data rows are highlighted red (every row is an exceedance by definition).

**Files:**
- Modify: `autogis/core/envmon/build_report_appendix.py` (replace the `_write_exceedance_sheet` stub)
- Test: `tests/envmon/test_build_report_appendix.py` (append tests)

**Interfaces:**
- Consumes: `List[AnalyticalResultRecord]`
- Produces: `"Exceedances"` sheet in the workbook

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_build_report_appendix.py`:

```python
# ---------------------------------------------------------------------------
# Task 3: Exceedances sheet
# ---------------------------------------------------------------------------

def test_exceedances_sheet_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Exceedances" in wb.sheetnames


def test_exceedances_sheet_only_exceeding_records(tmp_path):
    out = tmp_path / "appendix.xlsx"
    records = [
        _r("MW-01", "TCE", ExceedsScreeningLevel=1),
        _r("MW-02", "TCE", ExceedsScreeningLevel=0),
        _r("MW-03", "Benzene", ExceedsScreeningLevel=1),
    ]
    build_report_appendix(records, out, site_id="S", event_id="E", qa=QACollector())
    wb = openpyxl.load_workbook(out)
    ws = wb["Exceedances"]
    # row 1 = header; rows 2+ = data
    location_ids = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)
                    if ws.cell(row=r, column=1).value]
    assert "MW-01" in location_ids
    assert "MW-03" in location_ids
    assert "MW-02" not in location_ids


def test_exceedances_sheet_has_header_only_when_no_exceedances(tmp_path):
    out = tmp_path / "appendix.xlsx"
    records = [_r("MW-01", "TCE", ExceedsScreeningLevel=0)]
    build_report_appendix(records, out, site_id="S", event_id="E", qa=QACollector())
    wb = openpyxl.load_workbook(out)
    ws = wb["Exceedances"]
    assert ws.max_row == 1  # header only


def test_exceedances_sheet_header_includes_key_columns(tmp_path):
    out = tmp_path / "appendix.xlsx"
    records = [_r("MW-01", "TCE", ExceedsScreeningLevel=1)]
    build_report_appendix(records, out, site_id="S", event_id="E", qa=QACollector())
    wb = openpyxl.load_workbook(out)
    ws = wb["Exceedances"]
    headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
    assert "LocationID" in headers
    assert "AnalyteCanonicalName" in headers
    assert "DisplayText" in headers
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_report_appendix.py -k "exceedance" -v
```

Expected: FAIL — `AssertionError: 'Exceedances' not in ...`

- [ ] **Step 3: Implement `_write_exceedance_sheet`**

Replace the stub in `autogis/core/envmon/build_report_appendix.py`:

```python
def _write_exceedance_sheet(wb: Workbook,
                            records: List[AnalyticalResultRecord]) -> None:
    """Add 'Exceedances' sheet — all ExceedsScreeningLevel==1 rows."""
    exc_records = sorted(
        [r for r in records if r.ExceedsScreeningLevel == 1],
        key=lambda r: (r.LocationID, r.AnalyteCanonicalName),
    )
    headers = [
        "LocationID", "Matrix", "SampleDate", "AnalyteCanonicalName",
        "DisplayText", "ScreeningLevel", "ScreeningLevelSource", "Units",
    ]
    ws = wb.create_sheet("Exceedances")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    ws.freeze_panes = "A2"

    for r in exc_records:
        sd = (r.SampleDate.isoformat()
              if isinstance(r.SampleDate, (_dt.date, _dt.datetime))
              else str(r.SampleDate or ""))
        ws.append([
            r.LocationID, r.Matrix, sd, r.AnalyteCanonicalName,
            r.DisplayText, r.ScreeningLevel, r.ScreeningLevelSource, r.Units,
        ])

    # Highlight all data rows red — every row is an exceedance by definition
    for ri in range(2, len(exc_records) + 2):
        for ci in range(1, len(headers) + 1):
            ws.cell(row=ri, column=ci).fill = _RED_FILL

    for col_cells in ws.columns:
        width = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            width + 2, _MAX_COL_WIDTH
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all tests PASS (including Task 2 tests + new Task 3 tests).

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

```bash
git add autogis/core/envmon/build_report_appendix.py tests/envmon/test_build_report_appendix.py
git commit -m "feat(envmon): build_report_appendix — Exceedances sheet"
```

---

### Task 4: Trend Summary sheet

Implement `_write_trend_sheet`. Sheet is added only when `comparison_records` is not `None` (already guarded by the caller). Rows come from `ComparisonRecord` objects produced by `compare_events.compare_monitoring_events()`.

**Files:**
- Modify: `autogis/core/envmon/build_report_appendix.py` (replace `_write_trend_sheet` stub)
- Test: `tests/envmon/test_build_report_appendix.py` (append tests)

**Interfaces:**
- Consumes: `List[ComparisonRecord]` from `autogis.core.envmon.compare_events`
- Produces: `"Trend Summary"` sheet

Key `ComparisonRecord` fields (all needed for the sheet):
`SiteID, LocationID, Matrix, AnalyteCanonicalName, CurrentEventDate, PreviousEventDate, CurrentResultRaw, PreviousResultRaw, Delta, PercentChange, TrendClass, CurrentExceedance, PreviousExceedance`

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_build_report_appendix.py`:

```python
# ---------------------------------------------------------------------------
# Task 4: Trend Summary sheet
# ---------------------------------------------------------------------------

from autogis.core.envmon.compare_events import ComparisonRecord as _CR


def _comp(loc="MW-01", analyte="TCE", trend="INCREASING") -> _CR:
    return _CR(
        SiteID="SITE1", LocationID=loc, Matrix="GW",
        AnalyteCanonicalName=analyte,
        CurrentEventDate=date(2026, 4, 1),
        PreviousEventDate=date(2025, 10, 1),
        CurrentResultRaw="10.0 ug/L", PreviousResultRaw="5.0 ug/L",
        CurrentResultNumeric=10.0, PreviousResultNumeric=5.0,
        Delta=5.0, PercentChange=100.0, TrendClass=trend,
        CurrentExceedance="N", PreviousExceedance="N",
    )


def test_trend_summary_sheet_present_when_comparison_records_given(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        comparison_records=[_comp()],
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Trend Summary" in wb.sheetnames


def test_trend_summary_sheet_absent_when_no_comparison_records(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        comparison_records=None,
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Trend Summary" not in wb.sheetnames


def test_trend_summary_sheet_trend_class_values_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    comps = [_comp("MW-01", "TCE", "INCREASING"), _comp("MW-02", "Benzene", "STABLE")]
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        comparison_records=comps,
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["Trend Summary"]
    all_values = [ws.cell(r, c).value for r in range(1, ws.max_row + 1)
                  for c in range(1, ws.max_column + 1)]
    assert "INCREASING" in all_values
    assert "STABLE" in all_values


def test_trend_summary_header_has_trendclass_column(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        comparison_records=[_comp()],
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["Trend Summary"]
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert "TrendClass" in headers
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_report_appendix.py -k "trend" -v
```

Expected: FAIL — `AssertionError: 'Trend Summary' not in ...`

- [ ] **Step 3: Implement `_write_trend_sheet`**

Replace the stub in `autogis/core/envmon/build_report_appendix.py`:

```python
def _write_trend_sheet(wb: Workbook,
                       comparison_records: List[ComparisonRecord]) -> None:
    """Add 'Trend Summary' sheet from ComparisonRecord list."""
    headers = [
        "LocationID", "Matrix", "AnalyteCanonicalName",
        "CurrentEventDate", "PreviousEventDate",
        "CurrentResultRaw", "PreviousResultRaw",
        "Delta", "PercentChange", "TrendClass",
        "CurrentExceedance", "PreviousExceedance",
    ]

    def _d(v) -> str:
        if isinstance(v, (_dt.date, _dt.datetime)):
            return v.isoformat()
        return str(v or "")

    sorted_comps = sorted(
        comparison_records,
        key=lambda r: (r.LocationID, r.AnalyteCanonicalName),
    )
    rows = [
        [
            r.LocationID, r.Matrix, r.AnalyteCanonicalName,
            _d(r.CurrentEventDate), _d(r.PreviousEventDate),
            r.CurrentResultRaw, r.PreviousResultRaw,
            f"{r.Delta:.4f}" if r.Delta is not None else "",
            f"{r.PercentChange:.1f}" if r.PercentChange is not None else "",
            r.TrendClass,
            r.CurrentExceedance, r.PreviousExceedance,
        ]
        for r in sorted_comps
    ]

    ws = wb.create_sheet("Trend Summary")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    ws.freeze_panes = "A2"
    for row in rows:
        ws.append(row)
    for col_cells in ws.columns:
        width = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            width + 2, _MAX_COL_WIDTH
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

```bash
git add autogis/core/envmon/build_report_appendix.py tests/envmon/test_build_report_appendix.py
git commit -m "feat(envmon): build_report_appendix — Trend Summary sheet"
```

---

### Task 5: Data Gaps sheet

Implement `_write_gaps_sheet`. Sheet is added only when `gap_records` is not `None` (already guarded by the caller). ERROR-severity rows are red; WARNING rows are yellow.

**Files:**
- Modify: `autogis/core/envmon/build_report_appendix.py` (replace `_write_gaps_sheet` stub)
- Test: `tests/envmon/test_build_report_appendix.py` (append tests)

**Interfaces:**
- Consumes: `List[DataGapRecord]` from `autogis.core.envmon.data_gaps`
- Produces: `"Data Gaps"` sheet

Key `DataGapRecord` fields: `SiteID, LocationID, AnalyteCanonicalName, GapType, Severity, EventLabel, Detail`

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_build_report_appendix.py`:

```python
# ---------------------------------------------------------------------------
# Task 5: Data Gaps sheet
# ---------------------------------------------------------------------------

from autogis.core.envmon.data_gaps import DataGapRecord as _DGR


def _gap(loc="MW-01", analyte="TCE", gap_type="MISSING_WELL",
         severity="ERROR") -> _DGR:
    return _DGR(
        SiteID="SITE1", LocationID=loc, AnalyteCanonicalName=analyte,
        GapType=gap_type, Severity=severity,
        EventLabel="2026Q2", Detail="Not sampled this event",
    )


def test_data_gaps_sheet_present_when_gap_records_given(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        gap_records=[_gap()],
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Data Gaps" in wb.sheetnames


def test_data_gaps_sheet_absent_when_no_gap_records(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        gap_records=None,
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "Data Gaps" not in wb.sheetnames


def test_data_gaps_sheet_gap_type_values_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    gaps = [_gap("MW-01", "TCE", "MISSING_WELL"), _gap("MW-02", "Benzene", "MISSED_ANALYTE")]
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        gap_records=gaps,
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["Data Gaps"]
    all_values = [ws.cell(r, c).value for r in range(1, ws.max_row + 1)
                  for c in range(1, ws.max_column + 1)]
    assert "MISSING_WELL" in all_values
    assert "MISSED_ANALYTE" in all_values


def test_n_gaps_in_manifest(tmp_path):
    out = tmp_path / "appendix.xlsx"
    gaps = [_gap(), _gap("MW-02", "Benzene")]
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        gap_records=gaps,
        qa=QACollector(),
    )
    assert manifest.n_gaps == 2
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_report_appendix.py -k "data_gaps or n_gaps" -v
```

Expected: FAIL — `AssertionError: 'Data Gaps' not in ...`

- [ ] **Step 3: Implement `_write_gaps_sheet`**

Replace the stub in `autogis/core/envmon/build_report_appendix.py`:

```python
def _write_gaps_sheet(wb: Workbook,
                      gap_records: List[DataGapRecord]) -> None:
    """Add 'Data Gaps' sheet from DataGapRecord list."""
    headers = [
        "SiteID", "LocationID", "AnalyteCanonicalName",
        "GapType", "Severity", "EventLabel", "Detail",
    ]
    sorted_gaps = sorted(
        gap_records,
        key=lambda r: (r.Severity, r.LocationID, r.GapType),
    )
    ws = wb.create_sheet("Data Gaps")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    ws.freeze_panes = "A2"

    for ri, r in enumerate(sorted_gaps, start=2):
        ws.append([r.SiteID, r.LocationID, r.AnalyteCanonicalName,
                   r.GapType, r.Severity, r.EventLabel, r.Detail])
        sev = r.Severity.upper()
        row_fill = (_RED_FILL if sev == "ERROR"
                    else _YELLOW_FILL if sev == "WARNING"
                    else None)
        if row_fill:
            for ci in range(1, len(headers) + 1):
                ws.cell(row=ri, column=ci).fill = row_fill

    for col_cells in ws.columns:
        width = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            width + 2, _MAX_COL_WIDTH
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

```bash
git add autogis/core/envmon/build_report_appendix.py tests/envmon/test_build_report_appendix.py
git commit -m "feat(envmon): build_report_appendix — Data Gaps sheet"
```

---

### Task 6: QA Notes sheet and `n_rpd_errors` manifest count

Implement `_write_qa_notes_sheet`. This sheet is always present (even when empty). It combines:
1. Records from the build-time `QACollector` (source `"Build"`).
2. Raw dicts from `rpd_qa_rows` (source `"RPD_QA"`), read from the evaluate-rpd-qa CSV export.

ERROR/CRITICAL rows are red; WARNING rows are yellow. The `AppendixManifest.n_rpd_errors` count (already computed in `build_report_appendix`) counts only `"ERROR"` rows in `rpd_qa_rows`.

**Files:**
- Modify: `autogis/core/envmon/build_report_appendix.py` (replace `_write_qa_notes_sheet` stub)
- Test: `tests/envmon/test_build_report_appendix.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_build_report_appendix.py`:

```python
# ---------------------------------------------------------------------------
# Task 6: QA Notes sheet
# ---------------------------------------------------------------------------

def test_qa_notes_sheet_always_present(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    assert "QA Notes" in wb.sheetnames


def test_qa_notes_sheet_has_header_even_when_empty(tmp_path):
    out = tmp_path / "appendix.xlsx"
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["QA Notes"]
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)
               if ws.cell(1, c).value]
    assert "Severity" in headers
    assert "Message" in headers


def test_qa_notes_rpd_error_rows_appear(tmp_path):
    out = tmp_path / "appendix.xlsx"
    rpd_rows = [
        {"severity": "ERROR", "location_id": "MW-01", "analyte": "TCE",
         "message": "RPD exceeds 20%"},
        {"severity": "INFO", "location_id": "MW-02", "analyte": "Benzene",
         "message": "RPD within limits"},
    ]
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        rpd_qa_rows=rpd_rows,
        qa=QACollector(),
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["QA Notes"]
    all_values = [str(ws.cell(r, c).value or "")
                  for r in range(2, ws.max_row + 1)
                  for c in range(1, ws.max_column + 1)]
    assert any("RPD exceeds 20%" in v for v in all_values)


def test_n_rpd_errors_manifest_count(tmp_path):
    out = tmp_path / "appendix.xlsx"
    rpd_rows = [
        {"severity": "ERROR", "message": "bad"},
        {"severity": "ERROR", "message": "also bad"},
        {"severity": "WARNING", "message": "mild"},
    ]
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        rpd_qa_rows=rpd_rows,
        qa=QACollector(),
    )
    assert manifest.n_rpd_errors == 2


def test_n_rpd_errors_zero_when_no_rpd_rows(tmp_path):
    out = tmp_path / "appendix.xlsx"
    manifest = build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=QACollector(),
    )
    assert manifest.n_rpd_errors == 0


def test_qa_notes_build_qa_messages_appear(tmp_path):
    out = tmp_path / "appendix.xlsx"
    qa = QACollector()
    from autogis.core.common.qa import SEV_WARNING
    qa.add(SEV_WARNING, "test_category", "test warning message")
    build_report_appendix(
        _GW_RECORDS, out,
        site_id="SITE1", event_id="2026Q2",
        qa=qa,
    )
    wb = openpyxl.load_workbook(out)
    ws = wb["QA Notes"]
    all_values = [str(ws.cell(r, c).value or "")
                  for r in range(2, ws.max_row + 1)
                  for c in range(1, ws.max_column + 1)]
    assert any("test warning message" in v for v in all_values)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_build_report_appendix.py -k "qa_notes or n_rpd" -v
```

Expected: FAIL — `AssertionError: 'QA Notes' not in ...`

- [ ] **Step 3: Implement `_write_qa_notes_sheet`**

Replace the stub in `autogis/core/envmon/build_report_appendix.py`:

```python
def _write_qa_notes_sheet(wb: Workbook, qa: QACollector,
                          rpd_qa_rows: List[dict]) -> None:
    """Add 'QA Notes' sheet combining build QA and RPD QA rows."""
    headers = ["Source", "Severity", "Category", "Message"]
    rows: List[list] = []

    _sev_order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}
    for rec in sorted(qa.records, key=lambda r: _sev_order.get(r.severity, 4)):
        rows.append(["Build", rec.severity, rec.category, rec.message])

    for row in rpd_qa_rows:
        sev = str(row.get("severity", "")).upper()
        cat = str(row.get("category", "RPD_QA"))
        msg = str(row.get("message", row.get("Message", "")))
        loc = str(row.get("location_id", row.get("LocationID", "")))
        analyte = str(row.get("analyte", row.get("AnalyteName", "")))
        detail = f"[{loc}/{analyte}] {msg}" if (loc or analyte) else msg
        rows.append(["RPD_QA", sev, cat, detail])

    _sev_fill = {
        "CRITICAL": PatternFill(fill_type="solid", fgColor="FF6666"),
        "ERROR": _RED_FILL,
        "WARNING": _YELLOW_FILL,
    }

    ws = wb.create_sheet("QA Notes")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    ws.freeze_panes = "A2"

    for ri, row in enumerate(rows, start=2):
        ws.append(row)
        sev = str(row[1]).upper()
        row_fill = _sev_fill.get(sev)
        if row_fill:
            for ci in range(1, len(headers) + 1):
                ws.cell(row=ri, column=ci).fill = row_fill

    for col_cells in ws.columns:
        width = max((len(str(c.value or "")) for c in col_cells), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(
            width + 2, _MAX_COL_WIDTH
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_build_report_appendix.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

```bash
git add autogis/core/envmon/build_report_appendix.py tests/envmon/test_build_report_appendix.py
git commit -m "feat(envmon): build_report_appendix — QA Notes sheet, n_rpd_errors count"
```

---

### Task 7: CLI command `envmon build-report-appendix`

Wire `build_report_appendix()` into the `envmon` Click group in `cli.py`. The command requires `--results-csv`, `--site-id`, `--event-id`, and `--output`. All other inputs are optional. Absent optional CSV paths (file doesn't exist) are silently skipped, matching the `generate-event-report` pattern.

**Files:**
- Modify: `autogis/adapters/cli.py` — add command after `generate-event-report`
- Create: `tests/test_cli_build_report_appendix.py`

**Interfaces:**
- Consumes: `build_report_appendix` from `autogis.core.envmon.build_report_appendix`; `read_records_csv` from `autogis.core.envmon.evaluate_rpd_qa`; `_render_qa` from the local CLI module
- Produces: `autogis envmon build-report-appendix` CLI command

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli_build_report_appendix.py`:

```python
"""CLI tests for envmon build-report-appendix command."""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write_results_csv(path: Path) -> None:
    """Write a minimal valid AnalyticalResultRecord CSV."""
    fields = [
        "ImportBatchID", "SiteID", "Matrix", "LocationID", "SampleID",
        "ParentSampleID", "SampleDate", "DepthTop_ft", "DepthBottom_ft",
        "DepthIntervalText", "AnalyticalGroup", "MethodGroup",
        "AnalyteName", "AnalyteCanonicalName", "AnalyteAbbreviation",
        "ResultRawText", "ResultNumeric", "ReportingLimit", "DetectionLimit",
        "Units", "Qualifier", "IsNonDetect", "IsDetected", "IsEstimated",
        "IsDiluted", "IsNotAnalyzed", "IsNotSampled", "IsNotMeasured",
        "ScreeningLevel", "ScreeningLevelSource", "ExceedsScreeningLevel",
        "DisplayText",
    ]
    rows = [
        {
            "ImportBatchID": "B1", "SiteID": "H281", "Matrix": "GW",
            "LocationID": "MW-01", "SampleID": "S1", "ParentSampleID": "",
            "SampleDate": "2026-04-01", "DepthTop_ft": "", "DepthBottom_ft": "",
            "DepthIntervalText": "", "AnalyticalGroup": "VOC",
            "MethodGroup": "EPA8260", "AnalyteName": "TCE",
            "AnalyteCanonicalName": "TCE", "AnalyteAbbreviation": "TCE",
            "ResultRawText": "5.0", "ResultNumeric": "5.0",
            "ReportingLimit": "", "DetectionLimit": "", "Units": "ug/L",
            "Qualifier": "", "IsNonDetect": "0", "IsDetected": "1",
            "IsEstimated": "0", "IsDiluted": "0", "IsNotAnalyzed": "0",
            "IsNotSampled": "0", "IsNotMeasured": "0",
            "ScreeningLevel": "5.0", "ScreeningLevelSource": "RBSL",
            "ExceedsScreeningLevel": "0", "DisplayText": "5.0 ug/L",
        }
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_build_report_appendix_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-report-appendix" in result.output


def test_build_report_appendix_minimal_invocation_succeeds(tmp_path):
    results_csv = tmp_path / "results.csv"
    _write_results_csv(results_csv)
    out = tmp_path / "appendix.xlsx"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "build-report-appendix",
        "--results-csv", str(results_csv),
        "--site-id", "H281",
        "--event-id", "2026Q2",
        "--output", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_build_report_appendix_output_is_valid_xlsx(tmp_path):
    results_csv = tmp_path / "results.csv"
    _write_results_csv(results_csv)
    out = tmp_path / "appendix.xlsx"
    CliRunner().invoke(autogis, [
        "envmon", "build-report-appendix",
        "--results-csv", str(results_csv),
        "--site-id", "H281",
        "--event-id", "2026Q2",
        "--output", str(out),
    ])
    wb = openpyxl.load_workbook(out)
    assert "Cover" in wb.sheetnames
    assert "Current Event" in wb.sheetnames


def test_absent_optional_csv_skipped_not_errored(tmp_path):
    results_csv = tmp_path / "results.csv"
    _write_results_csv(results_csv)
    out = tmp_path / "appendix.xlsx"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "build-report-appendix",
        "--results-csv", str(results_csv),
        "--site-id", "H281",
        "--event-id", "2026Q2",
        "--output", str(out),
        "--comparison-csv", str(tmp_path / "does_not_exist.csv"),
        "--gaps-csv", str(tmp_path / "also_absent.csv"),
        "--rpd-qa-csv", str(tmp_path / "rpd_absent.csv"),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_build_report_appendix_output_shows_sheet_count(tmp_path):
    results_csv = tmp_path / "results.csv"
    _write_results_csv(results_csv)
    out = tmp_path / "appendix.xlsx"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "build-report-appendix",
        "--results-csv", str(results_csv),
        "--site-id", "H281",
        "--event-id", "2026Q2",
        "--output", str(out),
    ])
    assert "sheet(s)" in result.output
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_cli_build_report_appendix.py -v
```

Expected: FAIL — `AssertionError: 'build-report-appendix' not in result.output`

- [ ] **Step 3: Add CLI command to `autogis/adapters/cli.py`**

Find the `generate-event-report` command block in `cli.py` and add the following block immediately after it (after the function body and before the next `@envmon.command`):

```python
@envmon.command("build-report-appendix")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--site-id", required=True, help="Site ID.")
@click.option("--event-id", required=True,
              help="Event identifier (e.g. 2026Q2).")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path for the appendix workbook.")
@click.option("--comparison-csv", default=None, type=click.Path(),
              help="CSV from compare-events (adds Trend Summary sheet).")
@click.option("--gaps-csv", default=None, type=click.Path(),
              help="CSV from identify-data-gaps (adds Data Gaps sheet).")
@click.option("--rpd-qa-csv", default=None, type=click.Path(),
              help="CSV from evaluate-rpd-qa (adds rows to QA Notes sheet).")
@click.option("--report", default=None, type=click.Path(),
              help="Write build QA report to this path (.json/.csv/.md).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error", show_default=True)
def build_report_appendix_cmd(results_csv, site_id, event_id, output,
                               comparison_csv, gaps_csv, rpd_qa_csv,
                               report, fail_on):
    """Tool 9.2: compile the monitoring report appendix into one XLSX bundle (headless).

    Assembles analytical summary tables (Current Event / GW by Event /
    Soil by Depth), exceedance summary, optional trend and data-gap sheets,
    and QA notes into a single multi-sheet workbook ready for report delivery.

    Optional CSV inputs are skipped silently when the file is absent — the
    appendix builds successfully with only --results-csv provided.
    """
    import csv as _csv
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.build_report_appendix import build_report_appendix
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)

    comparison_records = None
    if comparison_csv and Path(comparison_csv).exists():
        from autogis.core.envmon.compare_events import ComparisonRecord
        comparison_records = read_records_csv(Path(comparison_csv), ComparisonRecord)

    gap_records = None
    if gaps_csv and Path(gaps_csv).exists():
        from autogis.core.envmon.data_gaps import DataGapRecord
        gap_records = read_records_csv(Path(gaps_csv), DataGapRecord)

    rpd_qa_rows = None
    if rpd_qa_csv and Path(rpd_qa_csv).exists():
        with open(Path(rpd_qa_csv), newline="", encoding="utf-8") as fh:
            rpd_qa_rows = list(_csv.DictReader(fh))

    qa = QACollector()
    manifest = build_report_appendix(
        results, Path(output),
        site_id=site_id, event_id=event_id,
        comparison_records=comparison_records,
        gap_records=gap_records,
        rpd_qa_rows=rpd_qa_rows,
        qa=qa,
    )
    click.echo(
        f"Written: {manifest.output_path}  "
        f"({len(manifest.sheet_names)} sheet(s), "
        f"{manifest.n_exceedances} exceedance(s), "
        f"{manifest.n_gaps} gap(s), "
        f"{manifest.n_rpd_errors} RPD error(s))"
    )
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/test_cli_build_report_appendix.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Full suite + commit**

```
python -m pytest -q
```

Expected: all tests pass.

```bash
git add autogis/adapters/cli.py tests/test_cli_build_report_appendix.py
git commit -m "feat(cli): add build-report-appendix command (headless Tool 9.2)"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task(s) |
|---|---|
| Compile analytical summary tables | Task 2 (reuses `_build_current_event`, `_build_gw_by_event`, `_build_soil_by_depth`) |
| Exceedance summary | Task 3 |
| QA notes | Task 6 |
| Single report-ready deliverable | Task 2 (`build_report_appendix` → one `.xlsx`) |
| Headless (no arcpy) | Enforced by Global Constraints; no arcpy import anywhere |
| TDD (tests first) | Each task: failing test → implement → green |
| Reuse existing summary exporters, don't duplicate | Task 1 exposes builders; Tasks 2–6 call them |
| Scope clearly vs `export_summary_tables` / `generate_event_report` | Documented in module docstring and Global Constraints |
| Output format justified | Tech Stack section |
| CLI surface | Task 7 |
| Trend vs previous event | Task 4 |
| Data gaps | Task 5 |
| Soil by Depth sheet | Task 2 (conditional on soil records present) |
| Cover sheet with metadata | Task 2 |
| Optional inputs silently skipped | Task 7 CLI (matches `generate-event-report` pattern) |

**Placeholder scan:** No TBD / TODO / "similar to Task N" / "fill in details" present. All code blocks are complete.

**Type consistency check:**

| Symbol | Defined in | Used in |
|---|---|---|
| `AppendixManifest` | Task 2 | Tasks 2–7 (tests), Task 7 CLI |
| `build_report_appendix(records, output_path, *, site_id, event_id, comparison_records, gap_records, rpd_qa_rows, generated_date, qa)` | Task 2 | Task 7 CLI |
| `build_current_event_table` alias | Task 1 | Task 2 implementation |
| `apply_sheet_style` alias | Task 1 | Task 2 implementation |
| `_write_exceedance_sheet(wb, records)` | Task 2 stub → Task 3 impl | Task 2 `build_report_appendix` body |
| `_write_trend_sheet(wb, comparison_records)` | Task 2 stub → Task 4 impl | Task 2 `build_report_appendix` body |
| `_write_gaps_sheet(wb, gap_records)` | Task 2 stub → Task 5 impl | Task 2 `build_report_appendix` body |
| `_write_qa_notes_sheet(wb, qa, rpd_qa_rows)` | Task 2 stub → Task 6 impl | Task 2 `build_report_appendix` body |
| `ComparisonRecord` | `compare_events.py` (pre-existing) | Task 4 tests + implementation |
| `DataGapRecord` | `data_gaps.py` (pre-existing) | Task 5 tests + implementation |
| `read_records_csv` | `evaluate_rpd_qa.py` (pre-existing) | Task 7 CLI |
| `_render_qa` | `cli.py` (pre-existing local fn) | Task 7 CLI |

All cross-task names are consistent.

---

## Risks

1. **`_build_cover_sheet` uses `wb.create_sheet("Cover", 0)`.** If a future openpyxl version changes how positional sheet insertion works, the Cover may not land first. Mitigation: the `test_cover_sheet_is_first` test catches this.

2. **`apply_sheet_style` assumes 0-based `exceedance_coords` and 1-based worksheet rows.** That is the existing convention in `_apply_sheet_style`. The public alias preserves this unchanged. The Task 1 tests verify the alias returns the correct tuple shape.

3. **`read_records_csv` (from `evaluate_rpd_qa.py`) uses `typing.get_type_hints()` for type coercion.** `ComparisonRecord` and `DataGapRecord` must have type annotations compatible with `get_type_hints()` (they do — both use `Optional[float]`, `Optional[date]`, `str`). Verify with the Task 7 CLI smoke test.

4. **No `__init__.py` change needed** — `build_report_appendix` is imported explicitly. Nothing in `autogis/core/envmon/__init__.py` re-exports individual modules, so no change needed there.
