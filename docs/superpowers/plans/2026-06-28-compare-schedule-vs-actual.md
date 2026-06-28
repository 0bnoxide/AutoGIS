# CompareScheduleVsActual — Implementation Plan

**Goal:** Add `envmon compare-schedule-vs-actual` CLI command that takes a schedule YAML and a results CSV, and produces a structured gap-and-excess report: wells and analytes in the schedule but absent from results (MISSING), wells and analytes in results but not in the schedule (UNEXPECTED), and successfully sampled items (SAMPLED). Output: CSV with columns `location_id, analyte, status, detail`. Enables quick pre-report QC without opening spreadsheets. CLOUD runtime.

**Architecture:** New module `autogis/core/envmon/schedule_vs_actual.py`. Core function `compare_schedule_vs_actual(results, schedule, *, event_date, window_days, qa) -> list[ScheduleGapRecord]`. Reads schedule from a YAML file (`site_id`, `wells`, `required_analytes`, `well_analytes` dict for per-well extras). Reuses the `identify_data_gaps.py` grouping pattern but adds UNEXPECTED detection. CLOUD runtime — no arcpy.

**Tech stack:** Python 3.14, click, stdlib csv/datetime/dataclasses, PyYAML (already a project dependency). Reuses: `AnalyticalResultRecord` from `autogis/core/envmon/gdb_schema.py`, `QACollector` from `autogis/core/common/qa.py`.

## Global constraints
- `core/` and `adapters/` import without arcpy or arcgis present
- Use openpyxl for Excel (ADR-008) — this plan uses no Excel
- New CLI command added to TOOLS in `autogis/runtime/capabilities.py` as `Runtime.CLOUD`
- Run tests with: `python -m pytest -q`
- CLI command goes in `autogis/adapters/cli.py` under the `envmon` group

---

### Task 1: Create `autogis/core/envmon/schedule_vs_actual.py`

**Files:**
- Create: `autogis/core/envmon/schedule_vs_actual.py`

**Complete code:**

```python
"""Compare expected monitoring schedule vs actual results (headless).

Schedule format (YAML):
    site_id: H281
    wells:
      - MW-1
      - MW-2
    required_analytes:
      - Benzene
      - Toluene
    well_analytes:       # optional per-well extras
      MW-2:
        - Arsenic

No arcpy dependency.
"""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


@dataclasses.dataclass
class ScheduleGapRecord:
    SiteID: str
    LocationID: str
    AnalyteName: str
    Status: str          # "MISSING" | "UNEXPECTED" | "SAMPLED"
    Detail: str
    EventDate: Optional[date]


def load_schedule_yaml(path: Path) -> dict:
    """Load schedule dict from a YAML file."""
    import yaml  # PyYAML
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def compare_schedule_vs_actual(
    results: List[AnalyticalResultRecord],
    schedule: dict,
    *,
    event_date: Optional[date] = None,
    window_days: int = 30,
    qa: QACollector,
) -> List[ScheduleGapRecord]:
    """Compare schedule definition against actual results.

    Args:
        results: Parsed AnalyticalResultRecord list (arcpy-free).
        schedule: Dict loaded from schedule YAML.
        event_date: Latest date to consider; inferred from results if None.
        window_days: Include results within this many days before event_date.
        qa: QACollector for status messages.

    Returns:
        List of ScheduleGapRecord with Status in {MISSING, UNEXPECTED, SAMPLED}.
    """
    site_id = schedule.get("site_id", "")
    wells: List[str] = list(schedule.get("wells") or [])
    required: set = set(schedule.get("required_analytes") or [])
    well_analytes: Dict[str, List[str]] = schedule.get("well_analytes") or {}

    # Determine event date from results if not provided
    if event_date is None and results:
        dates = [r.SampleDate for r in results if r.SampleDate]
        event_date = max(dates) if dates else None

    # Filter results to the event window
    filtered = results
    if event_date:
        start = event_date - timedelta(days=window_days)
        filtered = [
            r for r in results
            if r.SampleDate and start <= r.SampleDate <= event_date
        ]

    # Build lookup: location -> set of analyte canonical names sampled
    sampled: Dict[str, set] = defaultdict(set)
    for r in filtered:
        if not r.IsNotAnalyzed:
            sampled[r.LocationID].add(r.AnalyteCanonicalName)

    out_rows: List[ScheduleGapRecord] = []
    well_set = set(wells)

    # Check each scheduled well against required analytes
    for well in wells:
        expected = required | set(well_analytes.get(well) or [])
        got = sampled.get(well, set())
        for analyte in sorted(expected):
            if analyte not in got:
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=well, AnalyteName=analyte,
                    Status="MISSING",
                    Detail="Required by schedule but not found in results",
                    EventDate=event_date,
                ))
            else:
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=well, AnalyteName=analyte,
                    Status="SAMPLED", Detail="",
                    EventDate=event_date,
                ))

    # Detect unexpected wells (in results but not in the schedule)
    for loc, analytes in sorted(sampled.items()):
        if loc not in well_set:
            for analyte in sorted(analytes):
                out_rows.append(ScheduleGapRecord(
                    SiteID=site_id, LocationID=loc, AnalyteName=analyte,
                    Status="UNEXPECTED",
                    Detail="Location not in schedule wells list",
                    EventDate=event_date,
                ))

    n_missing = sum(1 for r in out_rows if r.Status == "MISSING")
    n_unexpected = sum(1 for r in out_rows if r.Status == "UNEXPECTED")
    n_sampled = sum(1 for r in out_rows if r.Status == "SAMPLED")

    if n_missing:
        qa.add(
            SEV_WARNING, "schedule_gaps_found",
            f"{n_missing} scheduled analyte(s) missing from results",
        )
    qa.add(
        SEV_INFO, "schedule_vs_actual_complete",
        f"compare_schedule_vs_actual: {n_sampled} sampled, "
        f"{n_missing} missing, {n_unexpected} unexpected "
        f"out of {len(out_rows)} total records",
    )
    return out_rows


def write_gap_csv(rows: List[ScheduleGapRecord], output_path: Path) -> None:
    """Write ScheduleGapRecord list to CSV."""
    import csv

    fields = [f.name for f in dataclasses.fields(ScheduleGapRecord)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            d = dataclasses.asdict(row)
            if d["EventDate"] and hasattr(d["EventDate"], "isoformat"):
                d["EventDate"] = d["EventDate"].isoformat()
            writer.writerow(d)
```

**Steps:**
- [ ] Create module file as shown above
- [ ] Verify `import yaml` works in the project environment (PyYAML must be installed)

---

### Task 2: Write `tests/test_schedule_vs_actual.py`

**Files:**
- Create: `tests/test_schedule_vs_actual.py`

**Complete code:**

```python
"""Tests for schedule vs actual comparison module."""
from datetime import date

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
from autogis.core.envmon.schedule_vs_actual import (
    ScheduleGapRecord,
    compare_schedule_vs_actual,
    load_schedule_yaml,
    write_gap_csv,
)


def _r(loc, analyte, dt=date(2026, 4, 15)):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=dt, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText="5.0",
        ResultNumeric=5.0, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=0, IsDetected=1,
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0, IsNotSampled=0,
        IsNotMeasured=0, ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText="5.0", DisplayColorClass="",
        SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1",
    )


SCHEDULE = {
    "site_id": "H281",
    "wells": ["MW-1", "MW-2"],
    "required_analytes": ["Benzene", "Toluene"],
    "well_analytes": {"MW-2": ["Arsenic"]},
}


def test_all_sampled():
    results = [
        _r("MW-1", "Benzene"), _r("MW-1", "Toluene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    statuses = {r.Status for r in rows}
    assert "MISSING" not in statuses
    assert "SAMPLED" in statuses


def test_missing_analyte():
    # MW-1 missing Toluene
    results = [
        _r("MW-1", "Benzene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    missing = [r for r in rows if r.Status == "MISSING"]
    assert len(missing) == 1
    assert missing[0].LocationID == "MW-1"
    assert missing[0].AnalyteName == "Toluene"


def test_unexpected_well():
    results = [
        _r("MW-1", "Benzene"), _r("MW-1", "Toluene"),
        _r("MW-2", "Benzene"), _r("MW-2", "Toluene"), _r("MW-2", "Arsenic"),
        _r("MW-99", "Benzene"),  # unexpected
    ]
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        results, SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    unexpected = [r for r in rows if r.Status == "UNEXPECTED"]
    assert len(unexpected) == 1
    assert unexpected[0].LocationID == "MW-99"


def test_event_date_inferred_from_results():
    results = [_r("MW-1", "Benzene", dt=date(2026, 4, 15))]
    qa = QACollector()
    rows = compare_schedule_vs_actual(results, SCHEDULE, qa=qa)
    # Should not crash; event_date inferred
    assert rows


def test_window_filters_old_results():
    old = _r("MW-1", "Benzene", dt=date(2025, 1, 1))
    new = _r("MW-2", "Benzene", dt=date(2026, 4, 15))
    qa = QACollector()
    rows = compare_schedule_vs_actual(
        [old, new], SCHEDULE,
        event_date=date(2026, 4, 15), window_days=30, qa=qa)
    # MW-1 old result outside window: Benzene+Toluene MISSING for MW-1
    mw1_missing = [r for r in rows if r.LocationID == "MW-1" and r.Status == "MISSING"]
    assert any(r.AnalyteName == "Benzene" for r in mw1_missing)


def test_write_gap_csv(tmp_path):
    rows = [
        ScheduleGapRecord("H281", "MW-1", "Benzene", "MISSING",
                          "Not found", date(2026, 4, 15))
    ]
    out = tmp_path / "gaps.csv"
    write_gap_csv(rows, out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "SiteID" in text
    assert "MISSING" in text


def test_load_schedule_yaml(tmp_path):
    yaml_path = tmp_path / "schedule.yaml"
    yaml_path.write_text(
        "site_id: H281\nwells:\n  - MW-1\nrequired_analytes:\n  - Benzene\n",
        encoding="utf-8",
    )
    sched = load_schedule_yaml(yaml_path)
    assert sched["site_id"] == "H281"
    assert "MW-1" in sched["wells"]


def test_qa_info_emitted():
    qa = QACollector()
    compare_schedule_vs_actual([], SCHEDULE, event_date=date(2026, 4, 15), qa=qa)
    assert any(r.category == "schedule_vs_actual_complete" for r in qa.records)
```

**Steps:**
- [ ] Write test file
- [ ] Run `python -m pytest tests/test_schedule_vs_actual.py -q` — expect ImportError
- [ ] Create `schedule_vs_actual.py` (Task 1)
- [ ] Run tests again — expect all pass

---

### Task 3: Wire CLI command in `autogis/adapters/cli.py`

**Files:**
- Modify: `autogis/adapters/cli.py`

**Complete command code:**

```python
@envmon.command("compare-schedule-vs-actual")
@click.option("--schedule", "schedule_path", required=True,
              type=click.Path(exists=True),
              help="Schedule YAML file (site_id, wells, required_analytes).")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV of AnalyticalResultRecord rows.")
@click.option("--output", required=True, type=click.Path(),
              help="Output CSV path for gap/excess report.")
@click.option("--event-date", default=None,
              help="Event date ISO (YYYY-MM-DD); inferred from results if omitted.")
@click.option("--window-days", type=int, default=30, show_default=True,
              help="Include results within this many days before event-date.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error",
              show_default=True)
def compare_schedule_vs_actual_cmd(
    schedule_path, results_csv, output, event_date, window_days, report, fail_on
):
    """Compare scheduled monitoring wells/analytes vs actual results (headless)."""
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.schedule_vs_actual import (
        compare_schedule_vs_actual,
        load_schedule_yaml,
        write_gap_csv,
    )

    schedule = load_schedule_yaml(Path(schedule_path))
    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    event_dt = _date.fromisoformat(event_date) if event_date else None
    qa = QACollector()

    rows = compare_schedule_vs_actual(
        results, schedule,
        event_date=event_dt,
        window_days=window_days,
        qa=qa,
    )
    write_gap_csv(rows, Path(output))
    click.echo(f"Written: {output}  ({len(rows)} record(s))")

    n_missing = sum(1 for r in rows if r.Status == "MISSING")
    n_unexpected = sum(1 for r in rows if r.Status == "UNEXPECTED")
    click.echo(f"  MISSING: {n_missing}  UNEXPECTED: {n_unexpected}")

    _render_qa(qa, report, fail_on)
```

**Steps:**
- [ ] Add command to `autogis/adapters/cli.py`
- [ ] Add `"compare-schedule-vs-actual": Runtime.CLOUD` to `TOOLS` in `autogis/runtime/capabilities.py`
- [ ] Run `python -m pytest -q` — expect all pass
- [ ] Commit: `feat(envmon): compare-schedule-vs-actual — schedule gap + excess analysis (headless)`

---

## Run commands

```bash
# TDD step 1: verify tests fail before module exists
python -m pytest tests/test_schedule_vs_actual.py -q

# TDD step 2: after creating schedule_vs_actual.py
python -m pytest tests/test_schedule_vs_actual.py -q

# TDD step 3: full suite
python -m pytest -q
```
