# IdentifyMonitoringDataGaps (Tool 4.10) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans to
> implement task-by-task. Steps use checkbox (`- [ ]`) syntax. Locked design
> decisions live in **ADR-0026** — do not re-litigate them.

**Goal:** Add a headless `envmon identify-data-gaps` CLI command + core module
that compares an expected sampling schedule (well network + required analytes)
against actual analytical results for an event window and reports gaps: missing
wells, missed analytes, dry/inaccessible wells (suppressed), and unexpected wells.

**Architecture:** New pure-core module `autogis/core/envmon/data_gaps.py` with a
`DataGapRecord` `@dataclass` and `identify_data_gaps(results, schedule, *,
event_date, window_days, dry_wells, qa) -> list[DataGapRecord]`. A single new
`click` command on the `envmon` group loads the `AnalyticalResultRecord` CSV
(`read_records_csv`), parses the schedule YAML (`yaml.safe_load`, already a
dependency), optionally loads a dry-wells CSV, calls the function, writes gap
records to CSV, and renders QA + exit through `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, `pyyaml`, stdlib `csv`/`dataclasses`/`datetime`,
`pytest`. Reuses: `AnalyticalResultRecord` (`gdb_schema.py`), `read_records_csv`
(`evaluate_rpd_qa.py`), `QACollector`/`SEV_*` (`common/qa.py`), `_render_qa`
(`cli.py`).

## Global constraints

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present.
  Headless — never import arcpy, never call `_guard`.
- Lazy-import core modules inside the command body.
- Command name exactly `identify-data-gaps`. Tests via `python -m pytest -q`.
- The core function takes already-parsed Python structures (a `schedule` dict and
  a `dry_wells` dict) so it is independently unit-testable without file I/O; the
  CLI command does the YAML/CSV parsing.

---

### Schedule YAML shape (new config contract)

```yaml
# expected sampling schedule for one event
site_id: H281
event_label: 2026Q2
wells:                       # the monitoring network expected this event
  - MW-1
  - MW-2
  - MW-3
required_analytes:           # canonical names every sampled well must report
  - Benzene
  - Toluene
  - Ethylbenzene
# optional per-well overrides (e.g. a well that only needs metals)
well_analytes:
  MW-3: [Benzene]
```

`required_analytes` is the default list; `well_analytes[well]` overrides it for
that well. (This contract is recorded in ADR-0026; wiring it into
`ValidateEnvConfig` is a future task, out of scope here.)

---

### Task 1: Core module `data_gaps.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/data_gaps.py`
- Create: `tests/test_data_gaps.py`

**Interfaces:**
- Consumes (do not modify): `AnalyticalResultRecord` (`gdb_schema.py`),
  `QACollector`, `SEV_INFO/SEV_WARNING/SEV_ERROR`.
- Produces:
  - `DataGapRecord` dataclass: `SiteID, LocationID, AnalyteCanonicalName,
    GapType, Severity, EventLabel, Detail` (AnalyteCanonicalName is "" for
    well-level gaps).
  - `identify_data_gaps(results: list[AnalyticalResultRecord], schedule: dict, *,
    event_date: Optional[date], window_days: int, dry_wells: dict[str, str],
    qa: QACollector) -> list[DataGapRecord]` where `dry_wells` maps LocationID ->
    reason.

**Locked behaviour (ADR-0026):**
- A result "counts" for the event iff `event_date is None` (use all results) or
  `abs((SampleDate - event_date).days) <= window_days`.
- `GapType` values + severity:
  - `MISSING_WELL` (ERROR): a `schedule.wells` entry with **zero** counting
    results — unless it is in `dry_wells` (then downgraded, see below).
  - `MISSED_ANALYTE` (ERROR): a well with ≥1 counting result, but a required
    analyte (per `well_analytes.get(well, required_analytes)`) has **no**
    counting result for that well.
  - `DRY_OR_INACCESSIBLE` (INFO): a `dry_wells` well — emitted instead of
    `MISSING_WELL`; `Detail` carries the reason.
  - `UNEXPECTED_WELL` (WARNING): a LocationID with counting results that is not in
    `schedule.wells`.
- Required-analyte comparison is on `AnalyteCanonicalName` (canonical, not raw).
- Emit one `INFO data_gaps_complete` with total gap count by type.
- Each gap also adds a matching QA record (category = lowercased GapType) at the
  mapped severity, so `_render_qa` exit codes work via `--fail-on`.

- [ ] **Step 1: Write the failing test file** `tests/test_data_gaps.py`.

```python
"""Unit tests for identify_data_gaps (Tool 4.10)."""
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, d=date(2026, 4, 1)):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="H281", Matrix="GW", LocationID=loc,
        SampleID=f"{loc}-{analyte}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText="1.0", ResultNumeric=1.0, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="", IsNonDetect=0,
        IsDetected=1, IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=0, DisplayText="1.0",
        DisplayColorClass="OK", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


SCHEDULE = {
    "site_id": "H281", "event_label": "2026Q2",
    "wells": ["MW-1", "MW-2", "MW-3"],
    "required_analytes": ["Benzene", "Toluene", "Ethylbenzene"],
    "well_analytes": {"MW-3": ["Benzene"]},
}


def _types(gaps):
    out = {}
    for g in gaps:
        out.setdefault(g.GapType, set()).add((g.LocationID, g.AnalyteCanonicalName))
    return out


def test_missing_well():
    # MW-2 has no results at all
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-2", "") in t["MISSING_WELL"]
    assert any(r.severity == "ERROR" and r.category == "missing_well"
               for r in qa.records)


def test_missed_analyte_respects_per_well_override():
    # MW-1 missing Toluene; MW-3 only needs Benzene (override) -> no miss
    results = [_r("MW-1", "Benzene"), _r("MW-1", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-1", "Toluene") in t["MISSED_ANALYTE"]
    # MW-3 override means Toluene/Ethylbenzene are NOT required there
    assert all(loc != "MW-3" for (loc, _a) in t.get("MISSED_ANALYTE", set()))


def test_dry_well_suppresses_missing_well():
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={"MW-2": "dry"}, qa=qa)
    t = _types(gaps)
    assert "MISSING_WELL" not in t or ("MW-2", "") not in t["MISSING_WELL"]
    assert ("MW-2", "") in t["DRY_OR_INACCESSIBLE"]


def test_unexpected_well_warns():
    results = [_r("MW-1", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    results += [_r("MW-99", "Benzene")]   # not in network
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    t = _types(gaps)
    assert ("MW-99", "") in t["UNEXPECTED_WELL"]
    assert any(r.category == "unexpected_well" and r.severity == "WARNING"
               for r in qa.records)


def test_event_window_filters_old_results():
    # MW-1 only has a result far outside the window -> treated as missing
    results = [_r("MW-1", a, d=date(2025, 1, 1))
               for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-2", a) for a in ("Benzene", "Toluene", "Ethylbenzene")]
    results += [_r("MW-3", "Benzene")]
    qa = QACollector()
    gaps = identify_data_gaps(results, SCHEDULE, event_date=date(2026, 4, 1),
                              window_days=30, dry_wells={}, qa=qa)
    assert ("MW-1", "") in _types(gaps)["MISSING_WELL"]
```

- [ ] **Step 2: Run, verify fail** (`ImportError`).
  `python -m pytest tests/test_data_gaps.py -q`

- [ ] **Step 3: Implement `autogis/core/envmon/data_gaps.py`.**

```python
"""Identify monitoring data gaps vs an expected schedule (Tool 4.10).

Headless, arcpy-free. Compares a schedule (well network + required analytes)
against actual AnalyticalResultRecords for an event window. See ADR-0026.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR

_SEV = {"MISSING_WELL": SEV_ERROR, "MISSED_ANALYTE": SEV_ERROR,
        "UNEXPECTED_WELL": SEV_WARNING, "DRY_OR_INACCESSIBLE": SEV_INFO}


@dataclass
class DataGapRecord:
    SiteID: str
    LocationID: str
    AnalyteCanonicalName: str
    GapType: str
    Severity: str
    EventLabel: str
    Detail: str


def _in_window(r, event_date, window_days):
    if event_date is None or r.SampleDate is None:
        return event_date is None
    return abs((r.SampleDate - event_date).days) <= window_days


def identify_data_gaps(results, schedule, *, event_date, window_days,
                       dry_wells, qa):
    # 1. filter results into the window
    # 2. index counting results by LocationID -> set(AnalyteCanonicalName)
    # 3. for each scheduled well: dry? -> DRY_OR_INACCESSIBLE; no results ->
    #    MISSING_WELL; else per required analyte (well_analytes override) missing
    #    -> MISSED_ANALYTE
    # 4. results for a LocationID not in schedule.wells -> UNEXPECTED_WELL (once)
    # 5. each gap -> DataGapRecord + qa.add(_SEV[type], type.lower(), detail,...)
    # 6. INFO data_gaps_complete with per-type counts
    ...
```

- [ ] **Step 4: Run unit tests, verify pass.**

---

### Task 2: Wire `envmon identify-data-gaps` CLI + CLI tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add one headless command.
- Create: `tests/test_cli_identify_data_gaps.py`

- [ ] **Step 1: Write failing CLI tests.** Write an `AnalyticalResultRecord` CSV
  (full-field helper as in `tests/test_cli_envmon_export_report_format.py`), a
  schedule YAML, and an optional dry-wells CSV (`location_id,reason`). Assert
  happy path exits per `--fail-on`, the gap CSV is written with `DataGapRecord`
  headers, and `--help` lists `--results-csv`, `--schedule`, `--output`,
  `--event-date`, `--event-window-days`, `--dry-wells`, `--report`, `--fail-on`.

```python
def test_help_lists_options():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    r = CliRunner().invoke(autogis, ["envmon", "identify-data-gaps", "--help"])
    assert r.exit_code == 0
    for opt in ("--results-csv", "--schedule", "--output", "--event-date",
                "--event-window-days", "--dry-wells"):
        assert opt in r.output
```

- [ ] **Step 2: Run, verify fail** (`No such command`).

- [ ] **Step 3: Add the command to `cli.py`.**

```python
@envmon.command("identify-data-gaps")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--schedule", required=True, type=click.Path(exists=True),
              help="Expected-schedule YAML (wells + required_analytes).")
@click.option("--output", required=True, type=click.Path(),
              help="Output data-gap CSV path.")
@click.option("--event-date", default=None, help="ISO date YYYY-MM-DD.")
@click.option("--event-window-days", default=30, type=int)
@click.option("--dry-wells", default=None, type=click.Path(exists=True),
              help="Optional CSV: location_id,reason.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def identify_data_gaps_cmd(results_csv, schedule, output, event_date,
                           event_window_days, dry_wells, report, fail_on):
    """Tool 4.10: report missing wells/analytes vs an expected schedule."""
    import csv as _csv
    from dataclasses import asdict, fields as _fields
    from datetime import date as _date
    import yaml as _yaml
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.data_gaps import identify_data_gaps, DataGapRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    sched = _yaml.safe_load(Path(schedule).read_text(encoding="utf-8"))
    dry = {}
    if dry_wells:
        with Path(dry_wells).open(newline="", encoding="utf-8") as fh:
            for row in _csv.DictReader(fh):
                dry[row["location_id"]] = row.get("reason", "")
    qa = QACollector()
    gaps = identify_data_gaps(
        results, sched,
        event_date=_date.fromisoformat(event_date) if event_date else None,
        window_days=event_window_days, dry_wells=dry, qa=qa)
    cols = [f.name for f in _fields(DataGapRecord)]
    out = Path(output); out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for g in gaps:
            w.writerow(asdict(g))
    click.echo(f"Written: {out}  ({len(gaps)} gap rows)")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests, verify pass.**
- [ ] **Step 5: Full suite** `python -m pytest -q` — no regressions.
- [ ] **Step 6: Commit.**

```
feat(envmon): identify-data-gaps — missing wells/analytes vs schedule (Tool 4.10)

Headless data_gaps core (MISSING_WELL / MISSED_ANALYTE / DRY_OR_INACCESSIBLE /
UNEXPECTED_WELL with per-well analyte overrides + event window) and envmon
identify-data-gaps CLI. New schedule-YAML contract recorded in ADR-0026.
```

---

## Self-review

- Gap types, severities, dry-well suppression, per-well analyte override, event
  window, canonical-name comparison → ADR-0026; covered by Task 1 tests. ✓
- Core takes parsed dicts (testable without I/O); CLI parses YAML/CSV. ✓
- Reuses `read_records_csv` / `QACollector` / `_render_qa`; `yaml` already a dep. ✓
- arcpy-free: stdlib + `yaml` + existing core imports only. ✓
- Schedule-YAML-not-yet-validated-by-ValidateEnvConfig limitation noted in
  ADR-0026. ✓
