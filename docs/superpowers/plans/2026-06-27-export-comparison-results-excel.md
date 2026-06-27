# ExportComparisonResultsToExcel (Tool 4.8) — Implementation Plan

**Goal:** Add a headless `envmon export-comparison-excel` CLI command + core module
that reads a `ComparisonRecord` CSV (output of Tool 4.7 `compare-events`) and writes
a formatted Excel workbook with conditional formatting on the `TrendClass` column and
a separate `EXCEED` sheet for exceedances. The only Excel library used is `openpyxl`
(ADR-008).

**Architecture:** New pure-core module `autogis/core/envmon/export_comparison_excel.py`
with `export_comparison_excel(records, output_path, *, qa) -> Path`. A `click` command
reads the CSV, calls the function, renders QA + exit. Uses `openpyxl` for workbook
creation — imported lazily inside the function to preserve the arcpy-free invariant.

**Tech stack:** Python 3.14, `click`, `openpyxl`, stdlib `csv`/`dataclasses`, `pytest`.
Reuses: `ComparisonRecord` (`compare_events.py`), `read_records_csv`
(`evaluate_rpd_qa.py`), `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `export-comparison-excel`. Register as `Runtime.CLOUD`.
- Only `openpyxl` for Excel (ADR-008). Import openpyxl lazily inside the function.
- Sheet 1 `AllResults`: all comparison records. Column header row bold + frozen.
  - `TrendClass` cell fill: `INCREASE` → red, `DECREASE` → blue, `STABLE` → green,
    `NEW` / `LOST` / `BOTH_ND` / `INSUFFICIENT_DATA` → yellow.
- Sheet 2 `Exceedances`: rows where `CurrentExceedance == "1"`.
- `--overwrite` flag: error if output exists and flag not set.

---

### Task 1: Core module `export_comparison_excel.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/export_comparison_excel.py`
- Create: `tests/test_export_comparison_excel.py`

**Complete code:**

```python
"""Export ComparisonRecord CSV to formatted Excel workbook (Tool 4.8)."""
from __future__ import annotations
from pathlib import Path
from typing import List
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR

_TREND_FILLS: dict  # populated lazily

_TREND_HEX = {
    "INCREASE":          "FFCCCC",  # red tint
    "DECREASE":          "CCE5FF",  # blue tint
    "STABLE":            "CCFFCC",  # green tint
    "NEW":               "FFFF99",
    "LOST":              "FFFF99",
    "BOTH_ND":           "FFFF99",
    "INSUFFICIENT_DATA": "FFFF99",
}


def export_comparison_excel(
    records: List[dict],
    output_path: Path,
    *,
    overwrite: bool = False,
    qa: QACollector,
) -> Path:
    """Write comparison records to a two-sheet Excel workbook."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError as exc:
        qa.add(SEV_ERROR, "openpyxl_missing",
               f"openpyxl not installed: {exc}")
        return Path(output_path)

    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        qa.add(SEV_ERROR, "output_exists",
               f"Output already exists: {output_path}. Use overwrite=True.")
        return output_path

    if not records:
        qa.add(SEV_WARNING, "no_records", "No comparison records to export.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()

    def _write_sheet(ws, rows, bold_header=True):
        if not rows:
            return
        headers = list(rows[0].keys())
        ws.append(headers)
        if bold_header:
            for cell in ws[1]:
                cell.font = Font(bold=True)
        ws.freeze_panes = ws["A2"]
        trend_col = (headers.index("TrendClass") + 1) if "TrendClass" in headers else None
        exceed_col = (headers.index("CurrentExceedance") + 1) if "CurrentExceedance" in headers else None
        for row_dict in rows:
            row_vals = [row_dict.get(h, "") for h in headers]
            ws.append(row_vals)
            row_idx = ws.max_row
            if trend_col:
                trend = str(row_dict.get("TrendClass", ""))
                hex_col = _TREND_HEX.get(trend)
                if hex_col:
                    ws.cell(row=row_idx, column=trend_col).fill = PatternFill(
                        fill_type="solid", fgColor=hex_col)

    ws_all = wb.active
    ws_all.title = "AllResults"
    _write_sheet(ws_all, records)

    ws_exc = wb.create_sheet("Exceedances")
    exceed_rows = [r for r in records if str(r.get("CurrentExceedance", "")) == "1"]
    _write_sheet(ws_exc, exceed_rows)

    wb.save(output_path)
    qa.add(SEV_INFO, "export_complete",
           f"Wrote {len(records)} row(s) to {output_path} "
           f"({len(exceed_rows)} exceedance(s))")
    return output_path
```

**Test file `tests/test_export_comparison_excel.py`:**

```python
"""Unit tests for export_comparison_excel (Tool 4.8)."""
import zipfile
from pathlib import Path
import pytest
from autogis.core.common.qa import QACollector
from autogis.core.envmon.export_comparison_excel import export_comparison_excel


def _row(trend="STABLE", exceed="0"):
    return {
        "SiteID": "S", "LocationID": "MW-1", "AnalyteCanonicalName": "Benzene",
        "Matrix": "GW", "TrendClass": trend, "CurrentExceedance": exceed,
        "PreviousExceedance": "0", "CurrentResultRaw": "5.0",
        "PreviousResultRaw": "5.0", "Delta": "0", "PercentChange": "0",
    }


def test_basic_export(tmp_path):
    out = tmp_path / "result.xlsx"
    qa = QACollector()
    result = export_comparison_excel([_row()], out, qa=qa)
    assert result == out
    assert out.exists()
    # XLSX is a ZIP; check for sheet files.
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("sheet1" in n.lower() or "AllResults" in n for n in names)


def test_exceedance_sheet(tmp_path):
    rows = [_row("INCREASE", "1"), _row("STABLE", "0")]
    out = tmp_path / "r.xlsx"
    qa = QACollector()
    export_comparison_excel(rows, out, qa=qa)
    assert any(r.category == "export_complete" for r in qa.records)


def test_overwrite_false_errors(tmp_path):
    out = tmp_path / "r.xlsx"
    out.write_bytes(b"existing")
    qa = QACollector()
    export_comparison_excel([_row()], out, overwrite=False, qa=qa)
    assert any(r.category == "output_exists" for r in qa.records)


def test_no_records_warns(tmp_path):
    out = tmp_path / "r.xlsx"
    qa = QACollector()
    export_comparison_excel([], out, qa=qa)
    assert any(r.category == "no_records" for r in qa.records)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `export_comparison_excel.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("export-comparison-excel")
@click.option("--comparison-csv", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--overwrite", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def export_comparison_excel_cmd(comparison_csv, output, overwrite, report, fail_on):
    """Tool 4.8: export comparison results to formatted Excel workbook."""
    ...
```

`capabilities.py`: `"export-comparison-excel": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): export-comparison-excel — trend/exceedance Excel export (Tool 4.8)`
