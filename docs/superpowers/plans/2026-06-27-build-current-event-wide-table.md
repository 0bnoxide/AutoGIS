# BuildCurrentEventWideTable (Tool 3.7) — Implementation Plan

**Goal:** Add a headless `envmon build-wide-table` CLI command + core module that pivots
`AnalyticalResultRecord`s from long format (one row per analyte result) to wide format
(one row per location × sample, analytes as columns). Output is a single CSV suitable
for tabular display or hand-off to other tools. Each analyte column contains the
`DisplayText` value; an optional `_exceed` suffix column carries the `ExceedsScreeningLevel`
flag (0/1/None).

**Architecture:** New pure-core module `autogis/core/envmon/wide_table.py` with
`build_wide_table(results, *, analytes, include_exceedance, qa) -> list[dict]`.
A single `click` command reads results CSV, calls the function, writes wide CSV,
renders QA + exit via `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`, `pytest`.
Reuses: `AnalyticalResultRecord` (`gdb_schema.py`), `read_records_csv`
(`evaluate_rpd_qa.py`), `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `build-wide-table`. Register as `Runtime.CLOUD`.
- Pivot key: `(SiteID, LocationID, SampleID, SampleDate, Matrix)`.
- Column order: pivot key fields first, then analyte columns sorted alphabetically.
- If a location has multiple results for the same analyte (e.g. duplicate rows),
  emit WARNING `duplicate_analyte_result` and use the first result encountered.
- `--analytes` option: comma-separated allow-list of canonical names; default is all.
- `--include-exceedance` flag: append `{Analyte}_exceed` columns for each analyte column.

---

### Task 1: Core module `wide_table.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/wide_table.py`
- Create: `tests/test_wide_table.py`

**Complete code:**

```python
"""Pivot AnalyticalResultRecords from long to wide format (Tool 3.7)."""
from __future__ import annotations
from typing import Dict, List, Optional, Set
from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

_PIVOT_KEY = ("SiteID", "LocationID", "SampleID", "SampleDate", "Matrix")


def build_wide_table(
    results: List[AnalyticalResultRecord],
    *,
    analytes: Optional[Set[str]] = None,
    include_exceedance: bool = False,
    qa: QACollector,
) -> List[Dict]:
    """Pivot long-format results to wide format; one row per location/sample."""
    # Group by pivot key.
    groups: Dict[tuple, Dict[str, AnalyticalResultRecord]] = {}
    for r in results:
        if analytes and r.AnalyteCanonicalName not in analytes:
            continue
        key = tuple(str(getattr(r, f, "") or "") for f in _PIVOT_KEY)
        if key not in groups:
            groups[key] = {}
        analyte = r.AnalyteCanonicalName
        if analyte in groups[key]:
            qa.add(SEV_WARNING, "duplicate_analyte_result",
                   f"Duplicate result for {analyte} at key={key}; using first",
                   location_id=r.LocationID, analyte_name=analyte)
        else:
            groups[key][analyte] = r

    # Collect all analyte names for column ordering.
    all_analytes = sorted({a for ana_map in groups.values() for a in ana_map})

    rows = []
    for key_vals, ana_map in groups.items():
        row: Dict = {f: v for f, v in zip(_PIVOT_KEY, key_vals)}
        for analyte in all_analytes:
            rec = ana_map.get(analyte)
            row[analyte] = rec.DisplayText if rec else ""
            if include_exceedance:
                row[f"{analyte}_exceed"] = (
                    rec.ExceedsScreeningLevel if rec is not None else None)
        rows.append(row)

    qa.add(SEV_INFO, "wide_table_complete",
           f"build_wide_table: {len(rows)} wide row(s), "
           f"{len(all_analytes)} analyte column(s)")
    return rows
```

**Test file `tests/test_wide_table.py`:**

```python
"""Unit tests for wide_table (Tool 3.7)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.envmon.wide_table import build_wide_table
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, display, exceed=None):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=date(2026, 4, 1), DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=display,
        ResultNumeric=None, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=0, IsDetected=1,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0, IsNotSampled=0,
        IsNotMeasured=0, ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=exceed, DisplayText=display,
        DisplayColorClass="", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


def test_basic_pivot():
    results = [_r("MW-1", "Benzene", "5.0"), _r("MW-1", "Toluene", "ND")]
    qa = QACollector()
    rows = build_wide_table(results, qa=qa)
    assert len(rows) == 1
    assert rows[0]["Benzene"] == "5.0"
    assert rows[0]["Toluene"] == "ND"


def test_multiple_locations():
    results = [_r("MW-1", "Benzene", "5.0"), _r("MW-2", "Benzene", "ND")]
    qa = QACollector()
    rows = build_wide_table(results, qa=qa)
    assert len(rows) == 2


def test_analyte_filter():
    results = [_r("MW-1", "Benzene", "5.0"), _r("MW-1", "Toluene", "ND")]
    qa = QACollector()
    rows = build_wide_table(results, analytes={"Benzene"}, qa=qa)
    assert "Toluene" not in rows[0]
    assert "Benzene" in rows[0]


def test_include_exceedance():
    results = [_r("MW-1", "Benzene", "10.0", exceed=1)]
    qa = QACollector()
    rows = build_wide_table(results, include_exceedance=True, qa=qa)
    assert rows[0]["Benzene_exceed"] == 1


def test_duplicate_warns():
    results = [_r("MW-1", "Benzene", "5.0"), _r("MW-1", "Benzene", "6.0")]
    # Both rows have same pivot key (SiteID/LocationID/SampleID/SampleDate/Matrix)
    qa = QACollector()
    build_wide_table(results, qa=qa)
    assert any(r.category == "duplicate_analyte_result" for r in qa.records)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `wide_table.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("build-wide-table")
@click.option("--results-csv", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--analytes", default=None,
              help="Comma-separated canonical names to include (default: all).")
@click.option("--include-exceedance", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def build_wide_table_cmd(results_csv, output, analytes, include_exceedance,
                         report, fail_on):
    """Tool 3.7: pivot long results to wide table (one row per location/sample)."""
    ...
```

`capabilities.py`: `"build-wide-table": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): build-wide-table — pivot results long→wide (Tool 3.7)`
