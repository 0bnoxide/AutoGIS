# CompareMonitoringEvents (Tool 4.7) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans (or
> subagent-driven-development) to implement task-by-task. Steps use checkbox
> (`- [ ]`) syntax. Locked design decisions live in **ADR-0026** — do not
> re-litigate them.

**Goal:** Add a headless `envmon compare-events` CLI command + core module that
compares the current monitoring event to the previous event per
`(LocationID, AnalyteCanonicalName)` and emits one comparison record per series
(Delta, PercentChange, TrendClass, exceedance change) for map symbology and
change-log use.

**Architecture:** A new pure-core module `autogis/core/envmon/compare_events.py`
with a `ComparisonRecord` `@dataclass` and `compare_events(results, qa, *, ...)`.
A single new `click` command on the `envmon` group loads an
`AnalyticalResultRecord` CSV with the existing `read_records_csv`, calls
`compare_events`, writes the records to CSV with `csv.DictWriter`, and renders QA
+ exit code through the existing module-level `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`datetime`,
`pytest`. Reuses: `read_records_csv` (`evaluate_rpd_qa.py`), `AnalyticalResultRecord`
(`gdb_schema.py`), `QACollector`/`SEV_*` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` must import with neither `arcpy` nor `arcgis` present.
  This command is headless — never import arcpy, never call `_guard`.
- Lazy-import core modules inside the command function body (every headless
  command in `cli.py` does this).
- Command name exactly `compare-events`. Run tests with `python -m pytest -q`.
- "Detected" means `IsDetected == 1 and ResultNumeric is not None`.

---

### Task 1: Core module `compare_events.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/compare_events.py`
- Create: `tests/test_compare_events.py`

**Interfaces:**
- Consumes (do not modify): `AnalyticalResultRecord` (`gdb_schema.py`),
  `QACollector`, `SEV_INFO`, `SEV_WARNING` (`common/qa.py`).
- Produces:
  - `ComparisonRecord` dataclass with fields:
    `SiteID, LocationID, Matrix, AnalyteCanonicalName, CurrentEventDate,
    PreviousEventDate, CurrentResultRaw, PreviousResultRaw, CurrentResultNumeric,
    PreviousResultNumeric, Delta, PercentChange, TrendClass, CurrentExceedance,
    PreviousExceedance` (all str/Optional[float]/Optional[date] as appropriate).
  - `compare_events(results: list[AnalyticalResultRecord], qa: QACollector, *,
    current_event_date: Optional[date] = None, stable_threshold: float = 10.0)
    -> list[ComparisonRecord]`.

**Locked behaviour (ADR-0026):**
- Series key `(LocationID, AnalyteCanonicalName)`. If one LocationID has results
  under two matrices, add `Matrix` to the key for that location and emit a
  `mixed_matrix` WARNING once per such location.
- Per series: current = latest `SampleDate`; previous = next-latest distinct date.
  `current_event_date`, when given, forces current to that date (series with no
  record on that date are skipped with a per-series INFO `no_current_record`).
- A series with a current event but no earlier event → `TrendClass` is
  `NEW_DETECTION` (if current detected) else `INDETERMINATE`; previous fields blank.
- `Delta`/`PercentChange` only when **both** events detected; else `None`.
  `PercentChange = (cur-prev)/prev*100` (guard `prev == 0` → `None`,
  WARNING `percent_change_zero_base`).
- `TrendClass`: both detected → `INCREASED`/`DECREASED`/`STABLE`
  (`abs(PercentChange) <= stable_threshold`); cur detected & prev nondetect →
  `NEW_DETECTION`; cur nondetect & prev detected → `NO_LONGER_DETECTED`; both
  nondetect → `NONDETECT_BOTH`; anything else → `INDETERMINATE`.
- Exceedance fields: map `ExceedsScreeningLevel` 1→"Y", 0→"N", None→"".
- Emit one `INFO compare_complete` with count, and per-series nothing noisy.

- [ ] **Step 1: Write the failing test file** `tests/test_compare_events.py`.

```python
"""Unit tests for compare_events (Tool 4.7)."""
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.envmon.compare_events import compare_events, ComparisonRecord
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, d, *, raw="1.0", num=1.0, detected=1, nondetect=0,
       exceed=0, matrix="GW"):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix=matrix, LocationID=loc,
        SampleID=f"{loc}-{analyte}-{d}", ParentSampleID="", SampleDate=d,
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260", AnalyteName=analyte,
        AnalyteCanonicalName=analyte, AnalyteAbbreviation=analyte[:3],
        ResultRawText=raw, ResultNumeric=num, ReportingLimit=None,
        DetectionLimit=None, Units="ug/L", Qualifier="",
        IsNonDetect=nondetect, IsDetected=detected, IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=0, IsNotSampled=0, IsNotMeasured=0, ScreeningLevel=5.0,
        ScreeningLevelSource="RBSL", ExceedsScreeningLevel=exceed,
        DisplayText=raw, DisplayColorClass="OK", SourceWorkbook="t.xlsx",
        SourceSheet="S1", SourceRow=1, SourceColumn="A", SourceCell="A1")


def test_increase_decrease_stable():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="20", num=20.0),  # +100% up
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="20", num=20.0),
        _r("MW-2", "Benzene", date(2026, 4, 1), raw="10", num=10.0),  # -50% down
        _r("MW-3", "Benzene", date(2026, 1, 1), raw="10", num=10.0),
        _r("MW-3", "Benzene", date(2026, 4, 1), raw="10.5", num=10.5),  # +5% stable
    ]
    qa = QACollector()
    out = {(c.LocationID): c for c in compare_events(recs, qa)}
    assert out["MW-1"].TrendClass == "INCREASED"
    assert out["MW-1"].PercentChange == 100.0
    assert out["MW-2"].TrendClass == "DECREASED"
    assert out["MW-3"].TrendClass == "STABLE"


def test_new_and_no_longer_detected():
    recs = [
        # prev nondetect, current detected -> NEW_DETECTION
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="<1", num=None,
           detected=0, nondetect=1),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="3", num=3.0),
        # prev detected, current nondetect -> NO_LONGER_DETECTED
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="3", num=3.0),
        _r("MW-2", "Benzene", date(2026, 4, 1), raw="<1", num=None,
           detected=0, nondetect=1),
    ]
    qa = QACollector()
    out = {c.LocationID: c for c in compare_events(recs, qa)}
    assert out["MW-1"].TrendClass == "NEW_DETECTION"
    assert out["MW-1"].Delta is None
    assert out["MW-2"].TrendClass == "NO_LONGER_DETECTED"


def test_single_event_is_new_detection_no_previous():
    recs = [_r("MW-1", "Benzene", date(2026, 4, 1), raw="3", num=3.0)]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.PreviousEventDate is None
    assert c.TrendClass == "NEW_DETECTION"


def test_exceedance_flags_mapping():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0, exceed=0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0, exceed=1),
    ]
    qa = QACollector()
    [c] = compare_events(recs, qa)
    assert c.CurrentExceedance == "Y"
    assert c.PreviousExceedance == "N"


def test_current_event_date_override_skips_series_without_record():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0),
        _r("MW-2", "Benzene", date(2026, 1, 1), raw="3", num=3.0),  # no Apr record
    ]
    qa = QACollector()
    out = compare_events(recs, qa, current_event_date=date(2026, 4, 1))
    locs = {c.LocationID for c in out}
    assert locs == {"MW-1"}
    assert any(r.category == "no_current_record" for r in qa.records)


def test_mixed_matrix_warns_and_splits():
    recs = [
        _r("MW-1", "Benzene", date(2026, 1, 1), raw="3", num=3.0, matrix="GW"),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="9", num=9.0, matrix="GW"),
        _r("MW-1", "Benzene", date(2026, 4, 1), raw="2", num=2.0, matrix="SOIL"),
    ]
    qa = QACollector()
    out = compare_events(recs, qa)
    assert any(r.category == "mixed_matrix" for r in qa.records)
    assert {c.Matrix for c in out} == {"GW", "SOIL"}
```

- [ ] **Step 2: Run the tests, verify they fail** (`ImportError`/no module).
  `python -m pytest tests/test_compare_events.py -q`

- [ ] **Step 3: Implement `autogis/core/envmon/compare_events.py`.**

Implement exactly the locked behaviour above. Skeleton:

```python
"""Compare current vs previous monitoring event per location/analyte (Tool 4.7).

Headless, arcpy-free. Keys series on (LocationID, AnalyteCanonicalName); adds
Matrix to the key only for locations that appear under more than one matrix.
See ADR-0026 for locked design decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING


@dataclass
class ComparisonRecord:
    SiteID: str
    LocationID: str
    Matrix: str
    AnalyteCanonicalName: str
    CurrentEventDate: Optional[date]
    PreviousEventDate: Optional[date]
    CurrentResultRaw: str
    PreviousResultRaw: str
    CurrentResultNumeric: Optional[float]
    PreviousResultNumeric: Optional[float]
    Delta: Optional[float]
    PercentChange: Optional[float]
    TrendClass: str
    CurrentExceedance: str
    PreviousExceedance: str


def _detected(r: AnalyticalResultRecord) -> bool:
    return r.IsDetected == 1 and r.ResultNumeric is not None


def _exc(v: Optional[int]) -> str:
    return {1: "Y", 0: "N"}.get(v, "")


def compare_events(results, qa, *, current_event_date=None,
                   stable_threshold=10.0):
    # 1. detect mixed-matrix locations -> WARNING + per-location key augmentation
    # 2. group by (LocationID[,Matrix], AnalyteCanonicalName)
    # 3. per group pick current/previous records by SampleDate (honor override)
    # 4. classify + build ComparisonRecord
    # 5. INFO compare_complete with count
    ...
```

Be precise on `PercentChange`: round to a sensible precision only if a test
requires it (tests above use exact 100.0/-50.0/5.0% → keep full float; 5% is
`(10.5-10)/10*100 = 5.0`). Guard `prev == 0` → `None` + WARNING.

- [ ] **Step 4: Run unit tests, verify pass.**
  `python -m pytest tests/test_compare_events.py -q`

---

### Task 2: Wire `envmon compare-events` CLI command + CLI tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add one headless command after the other
  record-emitting headless commands (e.g. near `evaluate-rpd-qa`), before the
  LOCAL-tools section.
- Create: `tests/test_cli_compare_events.py`

- [ ] **Step 1: Write failing CLI tests** `tests/test_cli_compare_events.py`.

Mirror the helper in `tests/test_cli_envmon_export_report_format.py` to write a
full `AnalyticalResultRecord` CSV (all fields, via `dataclasses.asdict` +
`csv.DictWriter`). Assert:
- happy path: `--results-csv IN --output OUT` exits 0, `OUT` exists, and the CSV
  has a header row of `ComparisonRecord` field names + one row per series.
- `--current-event-date 2026-04-01` filters series.
- `--help` lists `--results-csv`, `--output`, `--current-event-date`,
  `--stable-threshold`, `--report`, `--fail-on`.

```python
def test_help_lists_options():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    r = CliRunner().invoke(autogis, ["envmon", "compare-events", "--help"])
    assert r.exit_code == 0
    for opt in ("--results-csv", "--output", "--current-event-date",
                "--stable-threshold", "--report", "--fail-on"):
        assert opt in r.output
```

- [ ] **Step 2: Run, verify fail** (`No such command 'compare-events'`).

- [ ] **Step 3: Add the command to `cli.py`.**

```python
@envmon.command("compare-events")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="CSV export of Env_AnalyticalResults.")
@click.option("--output", required=True, type=click.Path(),
              help="Output comparison CSV path.")
@click.option("--current-event-date", default=None,
              help="ISO date (YYYY-MM-DD) to force as the current event.")
@click.option("--stable-threshold", default=10.0, type=float,
              help="abs(%% change) <= this is STABLE (default 10).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report to PATH (.md/.json/.csv by extension).")
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def compare_events_cmd(results_csv, output, current_event_date,
                       stable_threshold, report, fail_on):
    """Tool 4.7: compare current vs previous monitoring event per location/analyte."""
    import csv as _csv
    from dataclasses import asdict, fields as _fields
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.compare_events import compare_events, ComparisonRecord

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)
    ced = _date.fromisoformat(current_event_date) if current_event_date else None
    qa = QACollector()
    rows = compare_events(results, qa, current_event_date=ced,
                          stable_threshold=stable_threshold)
    cols = [f.name for f in _fields(ComparisonRecord)]
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for rec in rows:
            w.writerow(asdict(rec))
    click.echo(f"Written: {out}  ({len(rows)} comparison rows)")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests, verify pass.**
- [ ] **Step 5: Run full suite** `python -m pytest -q` — no regressions.
- [ ] **Step 6: Commit.**

```
feat(envmon): compare-events — current-vs-previous event delta/trend (Tool 4.7)

Headless compare_events core + envmon compare-events CLI. Keys series on
(LocationID, AnalyteCanonicalName), per-location current/previous selection,
TrendClass + exceedance-change output. Reuses read_records_csv + _render_qa.
Decisions locked in ADR-0026.
```

---

## Self-review

- Series key, per-location event selection, TrendClass enum, nondetect handling,
  exceedance mapping → all from ADR-0026, covered by Task 1 tests. ✓
- Reuses `read_records_csv` / `QACollector` / `_render_qa` — no new infra. ✓
- arcpy-free: only stdlib + existing core imports. ✓
- No `ElevationHistory`/openpyxl/AGOL coupling. ✓
- Placeholder scan: skeleton `...` blocks are intentional implement-here markers
  in Task 1 Step 3 only; everything else is literal. ✓
