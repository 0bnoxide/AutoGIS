# BuildMonitoringReportAppendix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `BuildMonitoringReportAppendix` — multi-sheet openpyxl Excel appendix with one sheet per analyte group, well × event columns, and conditional formatting for detections and exceedances.
See spec: `docs/superpowers/specs/2026-06-28-build-monitoring-report-appendix-design.md`.

**Architecture:**
- New: `autogis/core/envmon/report_appendix_builder.py`
- Modify: `autogis/adapters/cli.py` — add `build-report-appendix` command (headless)
- New: `tests/envmon/test_report_appendix_builder.py`

## Global Constraints

- Arcpy-free. openpyxl only (already a core dependency).
- Conditional formatting via `openpyxl.styles.PatternFill`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `report_appendix_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_report_appendix_builder.py`:

```python
from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.report_appendix_builder import (
    AppendixSheetSpec, build_appendix_sheet_specs,
    write_appendix_workbook,
)

_SL = {"Benzene": 5.0, "Toluene": 100.0}
_GROUP_MAP = {"Benzene": "VOC", "Toluene": "VOC", "Arsenic": "Metals"}

_ROWS = [
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "12.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "3.0",  "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-06-15"},
    {"LocationID": "MW-02", "AnalyteName": "Benzene",
     "ResultValue": "ND",   "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
    {"LocationID": "MW-01", "AnalyteName": "Arsenic",
     "ResultValue": "8.0",  "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
]


def test_build_specs_groups_analytes():
    specs = build_appendix_sheet_specs(_ROWS, group_map=_GROUP_MAP)
    sheet_names = [s.sheet_name for s in specs]
    assert "VOC" in sheet_names
    assert "Metals" in sheet_names


def test_build_specs_no_group_map():
    specs = build_appendix_sheet_specs(_ROWS)
    assert len(specs) == 1  # all analytes in default group


def test_write_workbook_produces_xlsx(tmp_path):
    specs = build_appendix_sheet_specs(_ROWS, group_map=_GROUP_MAP)
    out = tmp_path / "appendix.xlsx"
    result = write_appendix_workbook(_ROWS, specs, out,
                                      screening_levels=_SL)
    assert out.exists()
    wb = openpyxl.load_workbook(str(out))
    assert "VOC" in wb.sheetnames


def test_nd_cell_value(tmp_path):
    specs = build_appendix_sheet_specs(_ROWS, group_map=_GROUP_MAP)
    out = tmp_path / "appendix.xlsx"
    write_appendix_workbook(_ROWS, specs, out, screening_levels=_SL)
    wb = openpyxl.load_workbook(str(out))
    ws = wb["VOC"]
    # Find a cell with ND value
    found_nd = any(
        cell.value == "ND"
        for row in ws.iter_rows()
        for cell in row
    )
    assert found_nd


def test_well_count_and_event_count(tmp_path):
    specs = build_appendix_sheet_specs(_ROWS, group_map=_GROUP_MAP)
    out = tmp_path / "appendix.xlsx"
    result = write_appendix_workbook(_ROWS, specs, out)
    assert result.well_count == 2
    assert result.event_count == 2
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_report_appendix_builder.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/report_appendix_builder.py`**

```python
"""report_appendix_builder.py — multi-sheet analytical data appendix (openpyxl)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment

from ..common.qa import QACollector, QARecord, SEV_INFO

ND_QUALIFIERS = {"ND", "U", "BDL"}
_FILL_DETECTED  = PatternFill(fill_type="solid", fgColor="FFFF99")
_FILL_EXCEED    = PatternFill(fill_type="solid", fgColor="FF9999")
_FONT_HEADER    = Font(bold=True)


@dataclass
class AppendixSheetSpec:
    sheet_name: str
    analyte_group: str
    analytes: list
    screening_levels: dict
    units: str = ""


@dataclass
class AppendixBuildResult:
    workbook_path: Path
    sheet_count: int
    well_count: int
    event_count: int
    qa: QACollector


def build_appendix_sheet_specs(
    result_rows: list,
    screening_levels: Optional[dict] = None,
    group_map: Optional[dict] = None,
) -> list:
    sl = screening_levels or {}
    gm = group_map or {}
    # Partition analytes into groups
    by_group: dict[str, list] = defaultdict(list)
    for r in result_rows:
        analyte = r.get("AnalyteName", "")
        group = gm.get(analyte, "All Analytes")
        if analyte and analyte not in by_group[group]:
            by_group[group].append(analyte)

    specs = []
    for group, analytes in sorted(by_group.items()):
        specs.append(AppendixSheetSpec(
            sheet_name=group[:31],
            analyte_group=group,
            analytes=sorted(analytes),
            screening_levels={a: sl[a] for a in analytes if a in sl},
        ))
    return specs


def write_appendix_workbook(
    result_rows: list,
    specs: list,
    out_path: Path,
    *,
    site_id: str = "",
    screening_levels: Optional[dict] = None,
    event_dates: Optional[list] = None,
    nd_qualifier: str = "ND",
) -> AppendixBuildResult:
    sl = screening_levels or {}
    qa = QACollector()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # Index data: {(loc, analyte, date): row}
    data: dict[tuple, dict] = {}
    for r in result_rows:
        key = (r.get("LocationID", ""), r.get("AnalyteName", ""),
               r.get("SampleDate", ""))
        data[key] = r

    all_wells  = sorted({r.get("LocationID", "") for r in result_rows})
    all_dates  = sorted({r.get("SampleDate", "") for r in result_rows})
    if event_dates:
        all_dates = [d for d in all_dates if d in event_dates]

    for spec in specs:
        ws = wb.create_sheet(spec.sheet_name)
        # Header row 1: units
        ws.cell(1, 1, "Analyte")
        ws.cell(1, 2, "Units")
        col = 3
        for well in all_wells:
            for _ in all_dates:
                ws.cell(1, col, well)
                ws.cell(1, col).font = _FONT_HEADER
                col += 1

        # Header row 2: dates
        ws.cell(2, 1, "")
        ws.cell(2, 2, "")
        col = 3
        for _ in all_wells:
            for date in all_dates:
                ws.cell(2, col, date)
                ws.cell(2, col).font = _FONT_HEADER
                col += 1

        # Data rows
        row_num = 3
        detect_counts: dict[tuple, int] = defaultdict(int)
        total_counts: dict[tuple, int] = defaultdict(int)

        for analyte in spec.analytes:
            ws.cell(row_num, 1, analyte)
            ws.cell(row_num, 1).font = Font(bold=True)
            ws.cell(row_num, 2, "ug/L")  # default; override if units available
            col = 3
            for well in all_wells:
                for date in all_dates:
                    key = (well, analyte, date)
                    total_counts[(well, analyte)] += 1
                    cell = ws.cell(row_num, col)
                    if key in data:
                        r = data[key]
                        qual = r.get("ResultQualifier", "").upper().strip()
                        val_str = r.get("ResultValue", "")
                        is_nd = qual in ND_QUALIFIERS

                        if is_nd:
                            cell.value = "ND"
                        else:
                            try:
                                cell.value = float(val_str)
                                detect_counts[(well, analyte)] += 1
                                # Conditional fill
                                screening = sl.get(analyte)
                                if screening and float(val_str) >= screening:
                                    cell.fill = _FILL_EXCEED
                                else:
                                    cell.fill = _FILL_DETECTED
                            except (ValueError, TypeError):
                                cell.value = val_str
                    else:
                        cell.value = "—"
                    col += 1
            row_num += 1

        # Summary row
        ws.cell(row_num, 1, "Detects")
        ws.cell(row_num, 1).font = Font(italic=True)
        col = 3
        for well in all_wells:
            for analyte in spec.analytes:
                det = detect_counts.get((well, analyte), 0)
                tot = total_counts.get((well, analyte), 0)
                ws.cell(row_num, col, f"{det}/{tot}")
                col += 1
            break  # summary per well (simplified: use first analyte counts)
        # (Full per-analyte-per-well summary is an enhancement)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    qa.add(QARecord(SEV_INFO, "appendix_built",
                    f"{len(specs)} sheets, {len(all_wells)} wells, "
                    f"{len(all_dates)} events → {out_path}"))

    return AppendixBuildResult(
        workbook_path=out_path,
        sheet_count=len(specs),
        well_count=len(all_wells),
        event_count=len(all_dates),
        qa=qa,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_report_appendix_builder.py -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/report_appendix_builder.py \
        tests/envmon/test_report_appendix_builder.py
git commit -m "feat(envmon): report_appendix_builder — multi-sheet analytical appendix with exceedance formatting"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("build-report-appendix")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--group-map", "gm_path", default=None, type=click.Path(exists=True))
@click.option("--site", "site_id", default="")
@click.option("--event-dates", default=None, help="Comma-separated ISO dates.")
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def build_report_appendix_cmd(results_path, sl_path, gm_path, site_id,
                               event_dates, out, report):
    """Build multi-sheet analytical data appendix workbook (headless, openpyxl)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.report_appendix_builder import (
        build_appendix_sheet_specs, write_appendix_workbook)

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text()) if sl_path else None
    gm = _yaml.safe_load(Path(gm_path).read_text()) if gm_path else None
    dates = [d.strip() for d in event_dates.split(",")] if event_dates else None
    specs = build_appendix_sheet_specs(rows, screening_levels=sl, group_map=gm)
    result = write_appendix_workbook(rows, specs, Path(out), site_id=site_id,
                                      screening_levels=sl, event_dates=dates)
    click.echo(f"Sheets: {result.sheet_count}  Wells: {result.well_count}  "
               f"Events: {result.event_count}  Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_build_report_appendix_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "build-report-appendix" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_report_appendix_builder.py
git commit -m "feat(cli): add build-report-appendix command"
```
