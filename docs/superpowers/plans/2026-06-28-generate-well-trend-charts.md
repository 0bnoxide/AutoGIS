# GenerateWellTrendCharts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Add `envmon generate-trend-charts` CLI command that reads a per-location/analyte history CSV (produced by `run-history-report` or the history harvester) and writes an Excel workbook with one `LineChart` per location/analyte pair, grouped into analyte-named sheets — headless, openpyxl only, no arcpy.

**Architecture:**
- New: `autogis/core/envmon/well_trend_charts.py`
- Modify: `autogis/adapters/cli.py` — add `generate-trend-charts` command (CLOUD)
- Modify: `autogis/runtime/capabilities.py` — register `"generate-trend-charts": Runtime.CLOUD`
- New: `tests/envmon/test_well_trend_charts.py`

## Global Constraints

- Arcpy-free. openpyxl is a required project dependency (ADR-008) — no try/except ImportError.
- Use `openpyxl.chart.LineChart`, `Reference` from `openpyxl.chart`.
- `QACollector` / `QARecord` / `SEV_INFO` / `SEV_WARNING` from `autogis.core.common.qa`.
- CLI command name exactly `generate-trend-charts`. Register as `Runtime.CLOUD`.
- History CSV columns: `LocationID`, `AnalyteName`, `SampleDate`, `ResultValue`, `ReportedUnits`, `ScreeningLevel`.
- ND rows: skip any row where `ResultValue` is empty, `"ND"`, or cannot be parsed as float.
- Chart layout: one sheet per analyte (name truncated to 31 chars); one chart per location, stacked vertically. Each series block occupies exactly `_BLOCK_ROWS = 20` rows so charts never overlap.
- Pagination: if a single analyte has more than `max_per_sheet` locations, overflow to a new sheet suffixed `(2)`, `(3)`, etc.
- Screening level: when present, written as a constant column alongside values and added as a second named series on the same chart.
- `write_trend_charts` returns the total chart count (int).
- Run tests with `python -m pytest -q`.

---

### Task 1: Core module `well_trend_charts.py`

**Files:**
- Create: `autogis/core/envmon/well_trend_charts.py`

- [ ] **Step 1: Create `autogis/core/envmon/well_trend_charts.py`**

```python
"""Generate per-location/analyte trend charts in Excel (Tool 4.6).

Reads a history CSV (columns: LocationID, AnalyteName, SampleDate,
ResultValue, ReportedUnits, ScreeningLevel) and writes an openpyxl
workbook with one LineChart per location/analyte pair, grouped by
analyte into named sheets.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.chart import LineChart, Reference
from openpyxl.utils import get_column_letter

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

# Each series block occupies this many rows so charts (≈10 cm ≈ 15 rows
# at default row height) never overlap with the next block.
_BLOCK_ROWS = 20

# Data columns within each block:
#   Col A (1): SampleDate
#   Col B (2): ResultValue
#   Col C (3): ScreeningLevel  (present only when series.screening_level is not None)
# Charts are anchored at Col E (5) of the block start row.
_COL_DATE = 1
_COL_VALUE = 2
_COL_SL = 3
_COL_CHART_ANCHOR = 5


@dataclass
class TrendSeries:
    location_id: str
    analyte_name: str
    dates: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    screening_level: Optional[float] = None
    units: str = ""


def load_history_csv(path: Path) -> list[TrendSeries]:
    """Read history CSV; group by (LocationID, AnalyteName); skip ND rows; sort by date.

    Rows are skipped when ResultValue is empty, 'ND', 'NONE', or non-numeric.
    ScreeningLevel is taken from the first detected row for each key (subsequent
    rows with a non-empty value overwrite only if the first was missing).
    """
    path = Path(path)
    groups: dict[tuple[str, str], TrendSeries] = {}

    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            loc = row.get("LocationID", "").strip()
            analyte = row.get("AnalyteName", "").strip()
            raw_val = row.get("ResultValue", "").strip()
            sample_date = row.get("SampleDate", "").strip()
            units = row.get("ReportedUnits", "").strip()
            screening_raw = row.get("ScreeningLevel", "").strip()

            # Skip non-detects and unparseable values
            if not raw_val or raw_val.upper() in ("ND", "NONE", "N/A"):
                continue
            try:
                val = float(raw_val)
            except ValueError:
                continue

            key = (loc, analyte)
            if key not in groups:
                sl: Optional[float] = None
                try:
                    sl = float(screening_raw) if screening_raw else None
                except ValueError:
                    sl = None
                groups[key] = TrendSeries(
                    location_id=loc,
                    analyte_name=analyte,
                    units=units,
                    screening_level=sl,
                )
            else:
                # Back-fill screening level if first row lacked it
                if groups[key].screening_level is None and screening_raw:
                    try:
                        groups[key].screening_level = float(screening_raw)
                    except ValueError:
                        pass

            groups[key].dates.append(sample_date)
            groups[key].values.append(val)

    # Sort each series chronologically
    result: list[TrendSeries] = []
    for series in groups.values():
        if series.dates:
            paired = sorted(zip(series.dates, series.values))
            dates, values = zip(*paired)
            series.dates = list(dates)
            series.values = list(values)
        result.append(series)

    return result


def _safe_sheet_name(name: str, suffix: str = "") -> str:
    """Produce a valid Excel sheet name (max 31 chars, no forbidden chars)."""
    for ch in r"/\?*[]:'":
        name = name.replace(ch, "_")
    return (name + suffix)[:31]


def write_trend_charts(
    series_list: list[TrendSeries],
    out_path: Path,
    *,
    max_per_sheet: int = 20,
) -> int:
    """Write one Excel workbook with one LineChart per location/analyte pair.

    Sheets are named after analytes. More than *max_per_sheet* locations
    for one analyte spill into additional sheets suffixed "(2)", "(3)", etc.

    Each series occupies a fixed block of _BLOCK_ROWS rows so stacked charts
    do not overlap. Data layout per block (starting at *data_start_row*):

        Row data_start_row        — header: "Date" | location_id | "Screening Level"
        Rows data_start_row+1 ..  — one row per sample: date | value | sl_constant
        Rows beyond n+1           — blank (chart anchor area)

    The LineChart is anchored at column E of *data_start_row*.

    Returns:
        Total number of charts written to the workbook.
    """
    out_path = Path(out_path)

    wb = openpyxl.Workbook()
    # Remove the default blank sheet
    wb.remove(wb.active)

    # Group by analyte
    by_analyte: dict[str, list[TrendSeries]] = defaultdict(list)
    for series in series_list:
        by_analyte[series.analyte_name].append(series)

    chart_count = 0

    for analyte, analyte_series in sorted(by_analyte.items()):
        # Paginate into sheets of max_per_sheet locations
        pages = [
            analyte_series[i : i + max_per_sheet]
            for i in range(0, max(1, len(analyte_series)), max_per_sheet)
        ]
        for page_idx, page_series in enumerate(pages):
            suffix = f" ({page_idx + 1})" if len(pages) > 1 else ""
            ws = wb.create_sheet(title=_safe_sheet_name(analyte, suffix))

            data_start_row = 1

            for series in page_series:
                n = len(series.dates)

                # --- Write data block ---
                # Header row
                ws.cell(data_start_row, _COL_DATE, "Date")
                ws.cell(data_start_row, _COL_VALUE, series.location_id)
                has_sl = series.screening_level is not None
                if has_sl:
                    ws.cell(data_start_row, _COL_SL, "Screening Level")

                # Data rows
                for i, (d, v) in enumerate(zip(series.dates, series.values)):
                    r = data_start_row + 1 + i
                    ws.cell(r, _COL_DATE, d)
                    ws.cell(r, _COL_VALUE, v)
                    if has_sl:
                        ws.cell(r, _COL_SL, series.screening_level)

                # --- Build LineChart ---
                chart = LineChart()
                chart.title = f"{series.location_id} — {analyte}"
                chart.y_axis.title = series.units or "Concentration"
                chart.x_axis.title = "Sample Date"
                chart.style = 10
                chart.grouping = "standard"
                chart.width = 18   # cm
                chart.height = 10  # cm (~15 rows at default height)

                # Values series (col B, includes header for title)
                values_ref = Reference(
                    ws,
                    min_col=_COL_VALUE, max_col=_COL_VALUE,
                    min_row=data_start_row,
                    max_row=data_start_row + n,
                )
                chart.add_data(values_ref, titles_from_data=True)

                # Categorical x-axis (dates, col A, skip header)
                cats_ref = Reference(
                    ws,
                    min_col=_COL_DATE,
                    min_row=data_start_row + 1,
                    max_row=data_start_row + n,
                )
                chart.set_categories(cats_ref)

                # Optional screening level reference line
                if has_sl:
                    sl_ref = Reference(
                        ws,
                        min_col=_COL_SL, max_col=_COL_SL,
                        min_row=data_start_row,
                        max_row=data_start_row + n,
                    )
                    chart.add_data(sl_ref, titles_from_data=True)

                # Anchor chart to the right of the data columns
                anchor = (
                    f"{get_column_letter(_COL_CHART_ANCHOR)}{data_start_row}"
                )
                ws.add_chart(chart, anchor)
                chart_count += 1

                # Advance past this block (fixed height prevents overlap)
                data_start_row += _BLOCK_ROWS

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return chart_count
```

- [ ] **Step 2: Verify arcpy-free import**

```bash
python -c "from autogis.core.envmon.well_trend_charts import TrendSeries, load_history_csv, write_trend_charts; print('OK')"
```

Expected: `OK` with no ImportError.

---

### Task 2: Tests

**Files:**
- Create: `tests/envmon/test_well_trend_charts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_well_trend_charts.py`:

```python
"""Tests for well_trend_charts (Tool 4.6)."""
from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
import pytest

from autogis.core.envmon.well_trend_charts import (
    TrendSeries,
    load_history_csv,
    write_trend_charts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_history_csv(path: Path, rows: list[dict]) -> Path:
    """Write a minimal history CSV with all expected columns."""
    fieldnames = [
        "LocationID", "AnalyteName", "SampleDate",
        "ResultValue", "ReportedUnits", "ScreeningLevel",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


# ---------------------------------------------------------------------------
# load_history_csv
# ---------------------------------------------------------------------------

def test_load_basic(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0",
         "ReportedUnits": "ug/L", "ScreeningLevel": "1.0"},
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-04-01", "ResultValue": "8.0",
         "ReportedUnits": "ug/L", "ScreeningLevel": "1.0"},
    ])
    result = load_history_csv(csv_path)
    assert len(result) == 1
    s = result[0]
    assert s.location_id == "MW-1"
    assert s.analyte_name == "Benzene"
    assert s.values == [5.0, 8.0]
    assert s.dates == ["2026-01-01", "2026-04-01"]
    assert s.units == "ug/L"
    assert s.screening_level == pytest.approx(1.0)


def test_load_nd_rows_excluded(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "ND"},
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-04-01", "ResultValue": ""},
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-07-01", "ResultValue": "3.5"},
    ])
    result = load_history_csv(csv_path)
    assert len(result) == 1
    assert result[0].values == [3.5]


def test_load_multiple_analytes(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0"},
        {"LocationID": "MW-1", "AnalyteName": "Toluene",
         "SampleDate": "2026-01-01", "ResultValue": "2.0"},
    ])
    result = load_history_csv(csv_path)
    assert len(result) == 2
    analytes = {s.analyte_name for s in result}
    assert analytes == {"Benzene", "Toluene"}


def test_load_multiple_locations(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0"},
        {"LocationID": "MW-2", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "3.0"},
    ])
    result = load_history_csv(csv_path)
    assert len(result) == 2
    locs = {s.location_id for s in result}
    assert locs == {"MW-1", "MW-2"}


def test_load_sorted_by_date(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-07-01", "ResultValue": "9.0"},
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0"},
    ])
    result = load_history_csv(csv_path)
    assert result[0].dates[0] == "2026-01-01"
    assert result[0].dates[1] == "2026-07-01"


def test_load_no_screening_level(tmp_path):
    csv_path = _write_history_csv(tmp_path / "h.csv", [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0",
         "ScreeningLevel": ""},
    ])
    result = load_history_csv(csv_path)
    assert result[0].screening_level is None


# ---------------------------------------------------------------------------
# write_trend_charts
# ---------------------------------------------------------------------------

def _make_series(loc="MW-1", analyte="Benzene", n=3, sl=None) -> TrendSeries:
    dates = [f"2026-0{i+1}-01" for i in range(n)]
    values = [float(i + 1) for i in range(n)]
    return TrendSeries(
        location_id=loc,
        analyte_name=analyte,
        dates=dates,
        values=values,
        screening_level=sl,
        units="ug/L",
    )


def test_write_creates_xlsx(tmp_path):
    out = tmp_path / "charts.xlsx"
    series = [_make_series()]
    count = write_trend_charts(series, out)
    assert out.exists()
    assert count == 1


def test_write_sheet_named_after_analyte(tmp_path):
    out = tmp_path / "charts.xlsx"
    series = [_make_series(analyte="Benzene")]
    write_trend_charts(series, out)
    wb = openpyxl.load_workbook(str(out))
    assert "Benzene" in wb.sheetnames


def test_write_chart_count_multiple_locations(tmp_path):
    out = tmp_path / "charts.xlsx"
    series = [
        _make_series(loc="MW-1", analyte="Benzene"),
        _make_series(loc="MW-2", analyte="Benzene"),
    ]
    count = write_trend_charts(series, out)
    assert count == 2


def test_write_multiple_analytes_multiple_sheets(tmp_path):
    out = tmp_path / "charts.xlsx"
    series = [
        _make_series(loc="MW-1", analyte="Benzene"),
        _make_series(loc="MW-1", analyte="Toluene"),
    ]
    write_trend_charts(series, out)
    wb = openpyxl.load_workbook(str(out))
    assert "Benzene" in wb.sheetnames
    assert "Toluene" in wb.sheetnames


def test_write_single_point_series_no_crash(tmp_path):
    """A series with a single data point must not raise."""
    out = tmp_path / "charts.xlsx"
    s = TrendSeries(
        location_id="MW-1", analyte_name="Benzene",
        dates=["2026-01-01"], values=[5.0],
        screening_level=None, units="ug/L",
    )
    count = write_trend_charts([s], out)
    assert out.exists()
    assert count == 1


def test_write_pagination(tmp_path):
    """More than max_per_sheet locations create additional sheets."""
    out = tmp_path / "charts.xlsx"
    series = [_make_series(loc=f"MW-{i}", analyte="Benzene") for i in range(5)]
    write_trend_charts(series, out, max_per_sheet=3)
    wb = openpyxl.load_workbook(str(out))
    sheet_names = wb.sheetnames
    # Expect "Benzene" and "Benzene (2)"
    assert any("Benzene" in n for n in sheet_names)
    assert len(sheet_names) == 2


def test_write_chart_present_in_sheet(tmp_path):
    """At least one chart must be embedded in the first sheet."""
    out = tmp_path / "charts.xlsx"
    series = [_make_series()]
    write_trend_charts(series, out)
    wb = openpyxl.load_workbook(str(out))
    ws = wb.active
    assert len(ws._charts) >= 1


def test_write_empty_series_list(tmp_path):
    """Empty input must write a valid (empty) workbook without crashing."""
    out = tmp_path / "charts.xlsx"
    count = write_trend_charts([], out)
    # Workbook is created with no sheets; openpyxl allows this
    assert count == 0
```

- [ ] **Step 2: Run tests to confirm ImportError (TDD red)**

```bash
python -m pytest tests/envmon/test_well_trend_charts.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 3: Run tests after Task 1 is complete (TDD green)**

```bash
python -m pytest tests/envmon/test_well_trend_charts.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Full suite**

```bash
python -m pytest -q
```

Expected: no regressions.

- [ ] **Step 5: Commit core module + tests**

```bash
git add autogis/core/envmon/well_trend_charts.py \
        tests/envmon/test_well_trend_charts.py
git commit -m "feat(envmon): well_trend_charts — openpyxl LineChart per-location/analyte trend workbook (Tool 4.6)"
```

---

### Task 3: CLI command + capabilities registration

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `autogis/runtime/capabilities.py`

- [ ] **Step 1: Write failing CLI smoke test**

Add to `tests/envmon/test_well_trend_charts.py`:

```python
from click.testing import CliRunner
from autogis.adapters.cli import autogis as cli_root


def test_generate_trend_charts_in_help():
    result = CliRunner().invoke(cli_root, ["envmon", "--help"])
    assert "generate-trend-charts" in result.output
```

Run: `python -m pytest tests/envmon/test_well_trend_charts.py::test_generate_trend_charts_in_help -v`
Expected: FAIL (command not registered yet).

- [ ] **Step 2: Add CLI command to `autogis/adapters/cli.py`**

Insert the following command under the `envmon` group (alongside other CLOUD commands):

```python
@envmon.command("generate-trend-charts")
@click.option(
    "--history-csv", required=True, type=click.Path(exists=True),
    help="History CSV (columns: LocationID, AnalyteName, SampleDate, ResultValue, ReportedUnits, ScreeningLevel).",
)
@click.option(
    "--out", required=True, type=click.Path(),
    help="Output .xlsx workbook path.",
)
@click.option(
    "--analytes", default=None,
    help="Comma-separated list of analytes to include (default: all).",
)
@click.option(
    "--wells", default=None,
    help="Comma-separated list of location IDs to include (default: all).",
)
@click.option(
    "--screening-levels", default=None, type=click.Path(exists=True),
    help="Optional YAML file mapping AnalyteName → screening level float "
         "(overrides values in the CSV).",
)
@click.option(
    "--max-per-sheet", type=int, default=20, show_default=True,
    help="Maximum location charts per analyte sheet before creating overflow sheets.",
)
@click.option("--report", default=None, type=click.Path())
@click.option(
    "--fail-on", type=click.Choice(["error", "warning"]), default="error",
    show_default=True,
)
def generate_trend_charts_cmd(
    history_csv, out, analytes, wells, screening_levels,
    max_per_sheet, report, fail_on,
):
    """Tool 4.6: generate Excel trend chart workbook from history CSV (headless)."""
    import yaml  # stdlib-compatible; fall back to json if unavailable
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.well_trend_charts import load_history_csv, write_trend_charts

    qa = QACollector()
    series_list = load_history_csv(Path(history_csv))

    # Apply optional filters
    if analytes:
        keep = {a.strip() for a in analytes.split(",")}
        series_list = [s for s in series_list if s.analyte_name in keep]
    if wells:
        keep_wells = {w.strip() for w in wells.split(",")}
        series_list = [s for s in series_list if s.location_id in keep_wells]

    # Apply optional YAML screening level overrides
    if screening_levels:
        try:
            import yaml as _yaml  # type: ignore
            with open(screening_levels, encoding="utf-8") as fh:
                sl_map: dict = _yaml.safe_load(fh) or {}
        except ImportError:
            import json as _json
            with open(screening_levels, encoding="utf-8") as fh:
                sl_map = _json.load(fh)
        for s in series_list:
            if s.analyte_name in sl_map:
                try:
                    s.screening_level = float(sl_map[s.analyte_name])
                except (TypeError, ValueError):
                    pass

    out_path = Path(out)
    chart_count = write_trend_charts(series_list, out_path, max_per_sheet=max_per_sheet)
    click.echo(
        f"Written: {out_path}  "
        f"({len(series_list)} series, {chart_count} chart(s))"
    )
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 3: Register in `autogis/runtime/capabilities.py`**

Add to the `TOOLS` dict:

```python
"generate-trend-charts": Runtime.CLOUD,  # tool 4.6
```

- [ ] **Step 4: Run help smoke test**

```bash
python -m pytest tests/envmon/test_well_trend_charts.py::test_generate_trend_charts_in_help -v
```

Expected: PASS.

- [ ] **Step 5: End-to-end CLI integration test**

Add to `tests/envmon/test_well_trend_charts.py`:

```python
def test_cli_end_to_end(tmp_path):
    """CLI produces a valid workbook from a minimal history CSV."""
    csv_path = tmp_path / "history.csv"
    _write_history_csv(csv_path, [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0",
         "ReportedUnits": "ug/L", "ScreeningLevel": "1.0"},
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-04-01", "ResultValue": "8.0",
         "ReportedUnits": "ug/L", "ScreeningLevel": "1.0"},
    ])
    out_path = tmp_path / "trends.xlsx"
    result = CliRunner().invoke(cli_root, [
        "envmon", "generate-trend-charts",
        "--history-csv", str(csv_path),
        "--out", str(out_path),
    ])
    assert result.exit_code == 0, result.output
    assert out_path.exists()
    wb = openpyxl.load_workbook(str(out_path))
    assert "Benzene" in wb.sheetnames


def test_cli_analyte_filter(tmp_path):
    """--analytes flag excludes non-matching analytes."""
    csv_path = tmp_path / "history.csv"
    _write_history_csv(csv_path, [
        {"LocationID": "MW-1", "AnalyteName": "Benzene",
         "SampleDate": "2026-01-01", "ResultValue": "5.0"},
        {"LocationID": "MW-1", "AnalyteName": "Toluene",
         "SampleDate": "2026-01-01", "ResultValue": "2.0"},
    ])
    out_path = tmp_path / "trends.xlsx"
    result = CliRunner().invoke(cli_root, [
        "envmon", "generate-trend-charts",
        "--history-csv", str(csv_path),
        "--out", str(out_path),
        "--analytes", "Benzene",
    ])
    assert result.exit_code == 0, result.output
    wb = openpyxl.load_workbook(str(out_path))
    assert "Benzene" in wb.sheetnames
    assert "Toluene" not in wb.sheetnames
```

- [ ] **Step 6: Full suite + commit**

```bash
python -m pytest -q
```

Expected: all pass.

```bash
git add autogis/adapters/cli.py autogis/runtime/capabilities.py \
        tests/envmon/test_well_trend_charts.py
git commit -m "feat(cli): generate-trend-charts — register CLI command and capabilities entry (Tool 4.6)"
```

---

## Run commands

```bash
# TDD step 1: confirm tests fail before module exists
python -m pytest tests/envmon/test_well_trend_charts.py -v

# TDD step 2: after creating well_trend_charts.py
python -m pytest tests/envmon/test_well_trend_charts.py -v

# TDD step 3: after wiring CLI
python -m pytest tests/envmon/test_well_trend_charts.py -v

# Full suite
python -m pytest -q
```
