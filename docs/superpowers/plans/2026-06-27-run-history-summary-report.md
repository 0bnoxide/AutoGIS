# RunHistorySummaryReport (Tool 10.1) — Implementation Plan

**Goal:** Add a headless `envmon run-history-report` CLI command + core module that
reads `AnalyticalResultRecord`s spanning multiple events and produces a per-location
per-analyte history table: min, max, mean, n-detects, n-non-detects, latest result,
trend vs previous event. Output is a single CSV. Enables one-page review of all
monitoring history for a site.

**Architecture:** New pure-core module `autogis/core/envmon/history_report.py` with
`build_history_report(results, *, qa) -> list[HistorySummaryRow]`. Each output row
is a `HistorySummaryRow` dataclass. A `click` command reads results CSV, calls the
function, writes CSV, renders QA. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`statistics`,
`pytest`. Reuses: `AnalyticalResultRecord` (`gdb_schema.py`), `read_records_csv`
(`evaluate_rpd_qa.py`), `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `run-history-report`. Register as `Runtime.CLOUD`.
- Group by `(SiteID, LocationID, AnalyteCanonicalName, Matrix)`.
- Stats computed over `ResultNumeric` for detected results only (`IsNonDetect == 0`
  and `ResultNumeric is not None`).
- `TrendVsPrevious`: compare latest two event dates; `INCREASE`/`DECREASE`/`STABLE`
  (< ±10 % = STABLE) / `ND_BOTH` / `INSUFFICIENT_DATA`.
- Records with `IsNotAnalyzed == 1` excluded from all counts.

---

### Task 1: Core module `history_report.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/history_report.py`
- Create: `tests/test_history_report.py`

**Complete code:**

```python
"""Summarise per-location per-analyte history across events (Tool 10.1)."""
from __future__ import annotations
import dataclasses
import statistics
from datetime import date
from typing import List, Optional
from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO

_STABLE_PCT = 10.0


@dataclasses.dataclass
class HistorySummaryRow:
    SiteID: str
    LocationID: str
    AnalyteCanonicalName: str
    Matrix: str
    NTotal: int
    NDetects: int
    NNonDetects: int
    MinResult: Optional[float]
    MaxResult: Optional[float]
    MeanResult: Optional[float]
    LatestDate: Optional[date]
    LatestResult: str
    LatestExceedance: Optional[int]
    TrendVsPrevious: str
    Units: str


def build_history_report(
    results: List[AnalyticalResultRecord],
    *,
    qa: QACollector,
) -> List[HistorySummaryRow]:
    """Summarise monitoring history by location / analyte / matrix."""
    from collections import defaultdict

    # Group.
    groups: dict[tuple, list[AnalyticalResultRecord]] = defaultdict(list)
    for r in results:
        if r.IsNotAnalyzed:
            continue
        key = (r.SiteID, r.LocationID, r.AnalyteCanonicalName, r.Matrix)
        groups[key].append(r)

    rows: List[HistorySummaryRow] = []
    for (site, loc, analyte, matrix), recs in sorted(groups.items()):
        recs_sorted = sorted(recs, key=lambda r: r.SampleDate or date.min)
        n_total = len(recs_sorted)
        detected = [r for r in recs_sorted
                    if not r.IsNonDetect and r.ResultNumeric is not None]
        non_detects = [r for r in recs_sorted if r.IsNonDetect]
        n_det = len(detected)
        n_nd = len(non_detects)

        nums = [r.ResultNumeric for r in detected]
        min_r = min(nums) if nums else None
        max_r = max(nums) if nums else None
        mean_r = statistics.mean(nums) if nums else None

        latest = recs_sorted[-1]
        units = latest.Units or ""

        # Trend vs previous event.
        dates = sorted({r.SampleDate for r in recs_sorted if r.SampleDate})
        trend = "INSUFFICIENT_DATA"
        if len(dates) >= 2:
            cur_date, prev_date = dates[-1], dates[-2]
            cur_recs = [r for r in recs_sorted if r.SampleDate == cur_date]
            prv_recs = [r for r in recs_sorted if r.SampleDate == prev_date]
            cur_det = [r.ResultNumeric for r in cur_recs
                       if not r.IsNonDetect and r.ResultNumeric is not None]
            prv_det = [r.ResultNumeric for r in prv_recs
                       if not r.IsNonDetect and r.ResultNumeric is not None]
            if not cur_det and not prv_det:
                trend = "ND_BOTH"
            elif cur_det and prv_det:
                cur_mean = statistics.mean(cur_det)
                prv_mean = statistics.mean(prv_det)
                if prv_mean == 0:
                    trend = "INCREASE" if cur_mean > 0 else "STABLE"
                else:
                    pct = (cur_mean - prv_mean) / abs(prv_mean) * 100
                    trend = ("STABLE" if abs(pct) <= _STABLE_PCT
                             else ("INCREASE" if pct > 0 else "DECREASE"))
            else:
                trend = "INSUFFICIENT_DATA"

        rows.append(HistorySummaryRow(
            SiteID=site, LocationID=loc, AnalyteCanonicalName=analyte,
            Matrix=matrix, NTotal=n_total, NDetects=n_det, NNonDetects=n_nd,
            MinResult=min_r, MaxResult=max_r, MeanResult=mean_r,
            LatestDate=latest.SampleDate, LatestResult=latest.DisplayText or "",
            LatestExceedance=latest.ExceedsScreeningLevel,
            TrendVsPrevious=trend, Units=units))

    qa.add(SEV_INFO, "history_report_complete",
           f"build_history_report: {len(rows)} summary row(s) from "
           f"{sum(g for g in [len(v) for v in groups.values()])} records")
    return rows
```

**Test file `tests/test_history_report.py`:**

```python
"""Unit tests for history_report (Tool 10.1)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.envmon.history_report import build_history_report, HistorySummaryRow
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


def _r(loc, analyte, num, sample_date, nd=False, not_analyzed=False):
    return AnalyticalResultRecord(
        ImportBatchID="B", SiteID="S", Matrix="GW",
        LocationID=loc, SampleID="S1", ParentSampleID="",
        SampleDate=sample_date, DepthTop_ft=None, DepthBottom_ft=None,
        DepthIntervalText="", AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3], ResultRawText=str(num or "ND"),
        ResultNumeric=num, ReportingLimit=None, DetectionLimit=None,
        Units="ug/L", Qualifier="", IsNonDetect=int(nd),
        IsDetected=int(not nd), IsEstimated=0, IsDiluted=0,
        IsNotAnalyzed=int(not_analyzed), IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=None, ScreeningLevelSource="",
        ExceedsScreeningLevel=None, DisplayText=str(num or "ND"),
        DisplayColorClass="", SourceWorkbook="t.xlsx", SourceSheet="S1",
        SourceRow=1, SourceColumn="A", SourceCell="A1")


D1, D2 = date(2026, 1, 1), date(2026, 4, 1)


def test_basic_summary():
    results = [_r("MW-1", "Benzene", 5.0, D1), _r("MW-1", "Benzene", 10.0, D2)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert len(rows) == 1
    r = rows[0]
    assert r.NTotal == 2 and r.NDetects == 2 and r.NNonDetects == 0
    assert r.MinResult == 5.0 and r.MaxResult == 10.0
    assert r.TrendVsPrevious == "INCREASE"


def test_nondetect_counted():
    results = [_r("MW-1", "Benzene", None, D1, nd=True),
               _r("MW-1", "Benzene", None, D2, nd=True)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].NNonDetects == 2
    assert rows[0].TrendVsPrevious == "ND_BOTH"


def test_not_analyzed_excluded():
    results = [_r("MW-1", "Benzene", 5.0, D1),
               _r("MW-1", "Benzene", 5.0, D2, not_analyzed=True)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].NTotal == 1


def test_stable_trend():
    results = [_r("MW-1", "Benzene", 10.0, D1), _r("MW-1", "Benzene", 10.5, D2)]
    qa = QACollector()
    rows = build_history_report(results, qa=qa)
    assert rows[0].TrendVsPrevious == "STABLE"
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `history_report.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("run-history-report")
@click.option("--results-csv", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def run_history_report_cmd(results_csv, output, report, fail_on):
    """Tool 10.1: per-location per-analyte history summary across events."""
    ...
```

`capabilities.py`: `"run-history-report": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): run-history-report — multi-event history summary (Tool 10.1)`
