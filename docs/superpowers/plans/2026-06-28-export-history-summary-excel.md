# ExportHistorySummaryExcel (Tool 10.4) — Implementation Plan

**Goal:** Add `envmon export-history-excel` CLI command that reads the CSV output of
`run-history-report` (Tool 10.1) and produces a formatted Excel workbook with trend
color coding. INCREASE rows are highlighted light red, DECREASE light green, STABLE
white, ND_BOTH light grey, INSUFFICIENT_DATA light yellow. Enables one-click handoff
to reviewers who work in Excel.

**Architecture:** New pure-core module `autogis/core/envmon/export_history_excel.py`
with `export_history_excel(rows, output_path, *, qa) -> Path`. Input is a list of
`HistorySummaryRow` objects (from `history_report.py`). Uses openpyxl for output.
Column headers bold, row 1 frozen, auto-width applied. CLOUD runtime.

**Tech stack:** Python 3.14, click, openpyxl (ADR-008), stdlib csv/dataclasses, pytest.
Reuses: `HistorySummaryRow` (`history_report.py`), `read_records_csv` pattern,
`QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `export-history-excel`. Register as `Runtime.CLOUD`.
- openpyxl is a required dependency (ADR-008); no try/except ImportError.
- Trend fill colors:
  - `INCREASE`: `"FFCCCC"` (light red)
  - `DECREASE`: `"CCFFCC"` (light green)
  - `STABLE`: `"FFFFFF"` (white — no fill)
  - `ND_BOTH`: `"E0E0E0"` (light grey)
  - `INSUFFICIENT_DATA`: `"FFFF99"` (light yellow)
  - Any other/missing trend: `"FFFFFF"` (white)
- Date values in `LatestDate` are serialized as ISO strings in the cell.
- Sheet name: `"History Summary"`.
- Freeze panes at `A2`.

---

### Task 1: Core module `export_history_excel.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/export_history_excel.py`
- Create: `tests/test_export_history_excel.py`

**Complete code — `export_history_excel.py`:**

```python
"""Export history summary rows to Excel with trend color coding (Tool 10.4)."""
from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import List
from ..common.qa import QACollector, SEV_INFO

import openpyxl
from openpyxl.styles import PatternFill, Font
from openpyxl.utils import get_column_letter

_TREND_FILL = {
    "INCREASE": "FFCCCC",
    "DECREASE": "CCFFCC",
    "STABLE": "FFFFFF",
    "ND_BOTH": "E0E0E0",
    "INSUFFICIENT_DATA": "FFFF99",
}
_DEFAULT_FILL = "FFFFFF"


def export_history_excel(
    rows: list,
    output_path: Path,
    *,
    qa: QACollector,
) -> Path:
    """Write HistorySummaryRow list to a trend-colored Excel workbook."""
    output_path = Path(output_path)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "History Summary"

    if not rows:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(output_path)
        qa.add(SEV_INFO, "export_history_excel_complete",
               f"export_history_excel: 0 row(s) written (empty input)")
        return output_path

    fields = [f.name for f in dataclasses.fields(rows[0])]
    bold_font = Font(bold=True)

    # Header row.
    for col_idx, name in enumerate(fields, 1):
        cell = ws.cell(row=1, column=col_idx, value=name)
        cell.font = bold_font

    # Data rows.
    for row_idx, row in enumerate(rows, 2):
        trend = getattr(row, "TrendVsPrevious", "")
        hex_color = _TREND_FILL.get(trend, _DEFAULT_FILL)
        row_fill = PatternFill("solid", fgColor=hex_color)
        row_dict = dataclasses.asdict(row)
        for col_idx, field_name in enumerate(fields, 1):
            val = row_dict[field_name]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = row_fill

    ws.freeze_panes = ws["A2"]
    for col_idx in range(1, len(fields) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].auto_size = True

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    qa.add(SEV_INFO, "export_history_excel_complete",
           f"export_history_excel: {len(rows)} row(s) written to {output_path.name}")
    return output_path
```

**Complete code — `tests/test_export_history_excel.py`:**

```python
"""Tests for export_history_excel (Tool 10.4)."""
from datetime import date
import openpyxl
from autogis.core.common.qa import QACollector
from autogis.core.envmon.history_report import HistorySummaryRow
from autogis.core.envmon.export_history_excel import export_history_excel


def _row(trend="INCREASE", latest_date=None):
    return HistorySummaryRow(
        SiteID="S", LocationID="MW-1", AnalyteCanonicalName="Benzene",
        Matrix="GW", NTotal=2, NDetects=2, NNonDetects=0,
        MinResult=5.0, MaxResult=10.0, MeanResult=7.5,
        LatestDate=latest_date or date(2026, 4, 1),
        LatestResult="10.0",
        LatestExceedance=None, TrendVsPrevious=trend, Units="ug/L")


def test_writes_xlsx(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    result = export_history_excel([_row()], out, qa=qa)
    assert result == out
    assert out.exists()


def test_sheet_name(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    export_history_excel([_row()], out, qa=qa)
    wb = openpyxl.load_workbook(out)
    assert wb.active.title == "History Summary"


def test_header_row_bold(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    export_history_excel([_row()], out, qa=qa)
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    assert ws.cell(row=1, column=1).font.bold is True


def test_data_row_count(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    export_history_excel([_row("INCREASE"), _row("DECREASE")], out, qa=qa)
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    assert ws.max_row == 3  # 1 header + 2 data


def test_trend_fill_increase(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    export_history_excel([_row("INCREASE")], out, qa=qa)
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    rgb = ws.cell(row=2, column=1).fill.fgColor.rgb
    assert "FFCCCC" in rgb or "CC" in rgb


def test_empty_input_no_crash(tmp_path):
    out = tmp_path / "empty.xlsx"
    qa = QACollector()
    export_history_excel([], out, qa=qa)
    assert out.exists()


def test_qa_info_emitted(tmp_path):
    out = tmp_path / "history.xlsx"
    qa = QACollector()
    export_history_excel([_row()], out, qa=qa)
    assert any(r.category == "export_history_excel_complete" for r in qa.records)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `export_history_excel.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

**CLI command (insert before `_render_qa` in `cli.py`):**

```python
@envmon.command("export-history-excel")
@click.option("--history-csv", required=True, type=click.Path(exists=True),
              help="CSV output from run-history-report.")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def export_history_excel_cmd(history_csv, output, report, fail_on):
    """Tool 10.4: export run-history-report CSV to trend-colored Excel (headless)."""
    import csv as _csv
    import dataclasses
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.history_report import HistorySummaryRow
    from autogis.core.envmon.export_history_excel import export_history_excel

    rows = []
    fields = [f for f in dataclasses.fields(HistorySummaryRow)]
    field_names = [f.name for f in fields]
    with Path(history_csv).open(newline="", encoding="utf-8") as fh:
        for raw in _csv.DictReader(fh):
            kwargs = {}
            for f in fields:
                val = raw.get(f.name, "")
                if f.type in (float, "Optional[float]") or "float" in str(f.type):
                    kwargs[f.name] = float(val) if val not in ("", "None") else None
                elif f.type in (int, "Optional[int]") or "int" in str(f.type):
                    kwargs[f.name] = int(val) if val not in ("", "None") else None
                elif "date" in str(f.type).lower():
                    kwargs[f.name] = _date.fromisoformat(val) if val else None
                else:
                    kwargs[f.name] = val
            rows.append(HistorySummaryRow(**kwargs))
    qa = QACollector()
    out = export_history_excel(rows, Path(output), qa=qa)
    click.echo(f"Written: {out}  ({len(rows)} row(s))")
    _render_qa(qa, report, fail_on)
```

**`capabilities.py` entry:** `"export-history-excel": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test in `tests/test_cli_export_history_excel.py`.
- [ ] Add command, update capabilities.
- [ ] Run `python -m pytest -q`, verify all pass.
- [ ] Commit: `feat(envmon): export-history-excel — trend-highlighted Excel history (Tool 10.4)`
