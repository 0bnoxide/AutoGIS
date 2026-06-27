# Export Report-Format Summary Tables CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a headless `envmon` CLI command that wires the report-appendix exporter `export_summary_tables()` into `autogis/adapters/cli.py`.

**Architecture:** A single new `click` command on the existing `envmon` group. It loads `AnalyticalResultRecord`s from a CSV with the existing `read_records_csv` loader, calls the already-complete `export_summary_tables()` (PR #18), and renders QA + exit code through the existing `_render_qa` helper. Pure core, no arcpy, no `_guard`. Lazy imports inside the function body, matching every other headless command in the file.

**Tech Stack:** Python 3.14, `click`, `openpyxl`, `pytest`. Existing helpers: `autogis.core.envmon.evaluate_rpd_qa.read_records_csv`, `autogis.core.envmon.export_summary_tables.export_summary_tables`, `autogis.core.common.qa.QACollector`, and the module-level `_render_qa` in `cli.py`.

## Global Constraints

- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present. This command is headless (openpyxl only) — never import arcpy, never call `_guard`.
- Command name is exactly `export-report-format-summary-tables` (kebab-case, lowercase). Kept distinct from the existing `export-summary` command (which wires the *different* `export_summary.py` flat-QA module).
- Lazy-import core modules inside the command function body, as every other headless command in `cli.py` does.
- Run the test suite with `python -m pytest -q` from the repo root.

---

### Task 1: Wire `export-report-format-summary-tables` command + tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add one command in the headless section, after `export_summary_cmd` (the `export-summary` command) and before `evaluate_readiness_cmd`.
- Create: `tests/test_cli_envmon_export_report_format.py`

**Interfaces:**
- Consumes (all already exist, do not modify):
  - `read_records_csv(path: Path, record_class) -> List[record]` from `autogis.core.envmon.evaluate_rpd_qa`
  - `export_summary_tables(records, output_path, *, site_id="", include_current_event=True, include_gw_by_event=True, include_soil_by_depth=True, qa=None) -> Path` from `autogis.core.envmon.export_summary_tables`
  - `QACollector` from `autogis.core.common.qa`
  - `AnalyticalResultRecord` from `autogis.core.envmon.gdb_schema`
  - `_render_qa(qa, report, fail_on)` — module-level helper already in `cli.py` (renders records, optionally writes a report, exits 1 on FAIL)
- Produces: a click command registered on the `envmon` group as `export-report-format-summary-tables`.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_cli_envmon_export_report_format.py`:

```python
"""CLI surface for envmon export-report-format-summary-tables.

Wires export_summary_tables (report-appendix cross-tabs) into the CLI,
kept distinct from export-summary (flat QA sheets).
"""
import csv
from dataclasses import asdict, fields as dc_fields
from datetime import date

import openpyxl
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(LocationID, AnalyteCanonicalName, *, SampleDate=date(2026, 4, 1),
       DisplayText="--", ExceedsScreeningLevel=0, Matrix="GW",
       DepthIntervalText="", **kwargs):
    """Build a full AnalyticalResultRecord (all 39 fields required)."""
    defaults = {
        "ImportBatchID": "TEST_BATCH", "SiteID": "TEST_SITE", "Matrix": Matrix,
        "LocationID": LocationID,
        "SampleID": f"S_{LocationID}_{AnalyteCanonicalName}", "ParentSampleID": "",
        "SampleDate": SampleDate, "DepthTop_ft": None, "DepthBottom_ft": None,
        "DepthIntervalText": DepthIntervalText, "AnalyticalGroup": "VOC",
        "MethodGroup": "EPA8260", "AnalyteName": AnalyteCanonicalName,
        "AnalyteCanonicalName": AnalyteCanonicalName,
        "AnalyteAbbreviation": AnalyteCanonicalName[:3],
        "ResultRawText": DisplayText, "ResultNumeric": None,
        "ReportingLimit": None, "DetectionLimit": None, "Units": "ug/L",
        "Qualifier": "", "IsNonDetect": 0, "IsDetected": 1, "IsEstimated": 0,
        "IsDiluted": 0, "IsNotAnalyzed": 0, "IsNotSampled": 0,
        "IsNotMeasured": 0, "ScreeningLevel": 5.0, "ScreeningLevelSource": "RBSL",
        "ExceedsScreeningLevel": ExceedsScreeningLevel, "DisplayText": DisplayText,
        "DisplayColorClass": "EXCEED" if ExceedsScreeningLevel else "OK",
        "SourceWorkbook": "test.xlsx", "SourceSheet": "Sheet1", "SourceRow": 1,
        "SourceColumn": "A", "SourceCell": "A1",
    }
    defaults.update(kwargs)
    return AnalyticalResultRecord(**defaults)


def _write_results_csv(path, records):
    field_names = [f.name for f in dc_fields(AnalyticalResultRecord)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=field_names)
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))


GW = [
    _r("MW-1", "Benzene", DisplayText="5.5", ExceedsScreeningLevel=1),
    _r("MW-2", "Benzene", DisplayText="<1.0"),
]
SOIL = [
    _r("SB-1", "Benzene", DisplayText="10", Matrix="SOIL",
       DepthIntervalText="0-2 ft"),
]


def test_happy_path_writes_three_sheets(tmp_path):
    csv_path = tmp_path / "results.csv"
    out = tmp_path / "report.xlsx"
    _write_results_csv(csv_path, GW + SOIL)
    result = CliRunner().invoke(autogis, [
        "envmon", "export-report-format-summary-tables",
        "--results-csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    assert set(wb.sheetnames) == {"Current Event", "GW by Event", "Soil by Depth"}


def test_no_soil_flag_drops_sheet(tmp_path):
    csv_path = tmp_path / "results.csv"
    out = tmp_path / "report.xlsx"
    _write_results_csv(csv_path, GW + SOIL)
    result = CliRunner().invoke(autogis, [
        "envmon", "export-report-format-summary-tables",
        "--results-csv", str(csv_path), "--output", str(out),
        "--no-soil-by-depth"])
    assert result.exit_code == 0, result.output
    wb = openpyxl.load_workbook(out)
    assert "Soil by Depth" not in wb.sheetnames
    assert set(wb.sheetnames) == {"Current Event", "GW by Event"}


def test_fail_on_warning_escalates_for_missing_soil(tmp_path):
    csv_path = tmp_path / "results.csv"
    out = tmp_path / "report.xlsx"
    _write_results_csv(csv_path, GW)   # GW only -> soil_records_absent warning
    result = CliRunner().invoke(autogis, [
        "envmon", "export-report-format-summary-tables",
        "--results-csv", str(csv_path), "--output", str(out),
        "--fail-on", "warning"])
    assert result.exit_code != 0
    assert "soil_records_absent" in result.output


def test_command_registered_help():
    result = CliRunner().invoke(autogis, [
        "envmon", "export-report-format-summary-tables", "--help"])
    assert result.exit_code == 0
    assert "--results-csv" in result.output
    assert "--output" in result.output
    assert "--fail-on" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli_envmon_export_report_format.py -q`
Expected: FAIL — all four tests error. `CliRunner` returns a non-zero `exit_code` with output containing `No such command 'export-report-format-summary-tables'` (the command is not registered yet).

- [ ] **Step 3: Add the command to `cli.py`**

In `autogis/adapters/cli.py`, insert this command immediately after the `export_summary_cmd` function (the one decorated `@envmon.command("export-summary")`, ending at `click.echo(f"Written: {out}  ...")`) and before `@envmon.command("evaluate-readiness")`:

```python
@envmon.command("export-report-format-summary-tables")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--output", required=True, type=click.Path(),
              help="Output .xlsx path.")
@click.option("--site-id", default="",
              help="Site ID filter + label (default: first record's SiteID).")
@click.option("--no-current-event", is_flag=True, default=False,
              help="Drop the 'Current Event' sheet.")
@click.option("--no-gw-by-event", is_flag=True, default=False,
              help="Drop the 'GW by Event' sheet.")
@click.option("--no-soil-by-depth", is_flag=True, default=False,
              help="Drop the 'Soil by Depth' sheet.")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def export_report_format_summary_tables_cmd(
        results_csv, output, site_id, no_current_event, no_gw_by_event,
        no_soil_by_depth, report, fail_on):
    """Tool: export Env_AnalyticalResults to formatted report-appendix tables.

    Produces the three cross-tab sheets (Current Event / GW by Event /
    Soil by Depth). Distinct from ``export-summary`` (flat QA sheets).
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.export_summary_tables import export_summary_tables

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    if not site_id and results:
        site_id = results[0].SiteID
    qa = QACollector()
    out = export_summary_tables(
        results, Path(output), site_id=site_id,
        include_current_event=not no_current_event,
        include_gw_by_event=not no_gw_by_event,
        include_soil_by_depth=not no_soil_by_depth,
        qa=qa)
    click.echo(f"Written: {out}")
    _render_qa(qa, report, fail_on)
```

(`_render_qa` is a module-level function defined later in the file; Python resolves it at call time, so defining the command above its definition is fine — `evaluate_rpd_qa_cmd` already does the same.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cli_envmon_export_report_format.py -q`
Expected: PASS — 4 passed.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `python -m pytest -q`
Expected: PASS — all previously-passing tests still pass (151 + 4 new = 155, assuming the baseline of 151).

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/test_cli_envmon_export_report_format.py
git commit -m "feat(envmon): export-report-format-summary-tables CLI command

Wires export_summary_tables (report-appendix cross-tabs) into the envmon
CLI group, kept distinct from export-summary (flat QA sheets). Reuses
read_records_csv + _render_qa. 4 tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Command name `export-report-format-summary-tables` → Task 1, Step 3 decorator. ✓
- All options (`--results-csv`, `--output`, `--site-id`, three `--no-*` flags, `--report`, `--fail-on`) → Step 3. ✓
- Data flow (read_records_csv → site-id default → QACollector → export_summary_tables → echo → _render_qa) → Step 3. ✓
- Error handling (fail-on escalation, exists=True guard) → tested in `test_fail_on_warning_escalates_for_missing_soil`; `exists=True` is on the `--results-csv` option. ✓
- Tests: happy path / sheet toggle / warning escalation / help → all four present in Step 1. ✓
- Out-of-scope items (no `--samples-csv`, no module changes, no `.pyt`) → respected; Task 1 modifies only `cli.py` + new test file. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — all code is complete and literal. ✓

**Type consistency:** `export_summary_tables` keyword args (`site_id`, `include_current_event`, `include_gw_by_event`, `include_soil_by_depth`, `qa`) match its signature in `export_summary_tables.py:132`. `read_records_csv(path, record_class)` matches `evaluate_rpd_qa.py:152`. `_render_qa(qa, report, fail_on)` matches `cli.py:336`. ✓
