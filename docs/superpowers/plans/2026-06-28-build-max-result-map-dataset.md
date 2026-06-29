# BuildMaxResultMapDataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a headless, arcpy-free tool (roadmap #4.9) that scans `AnalyticalResultRecord` rows across a date range and produces one per-location/per-analyte record of the maximum detected value or maximum exceedance-ratio for use in the figure/callout mapping pipeline.

**Architecture:** A pure-core function `build_max_result_dataset()` in `autogis/core/envmon/build_max_result.py` groups records by `(LocationID, Matrix, AnalyteCanonicalName)`, applies date-range and matrix filters, picks the max per group according to the selection mode, and returns a `List[MaxResultRecord]`. The CLI command `autogis envmon build-max-result` loads input CSV with `read_records_csv`, calls the core function, and writes output CSV with `csv.DictWriter` — identical to the pattern in `compare-events`. No arcpy, no openpyxl.

**Differentiation from `build_current_event.py`:** `build_current_event.select_samples()` picks **one sample per location** (whichever sample has the highest exceedance or highest concentration for a target analyte) and then pivots to a wide row. Tool 4.9 picks the **max per analyte independently** — each analyte's maximum can come from a different date and different sample — producing a narrow output record per group. The two tools have different output shapes and feed different pipeline stages.

**Tech Stack:** Python 3.14, `click`, `pyyaml`, stdlib `csv`/`dataclasses`, `pytest`. Reuses: `AnalyticalResultRecord` (`gdb_schema.py`), `QACollector` (`common/qa.py`), `read_records_csv` (`evaluate_rpd_qa.py`), `same_dimension`/`convert` (`common/units.py`), `_render_qa` (already in `cli.py`).

## Global Constraints

- Branch: `feat/build-max-result-4.9`
- `autogis/core/` and `autogis/adapters/` must import cleanly with neither `arcpy` nor `arcgis` present — enforced by the test suite.
- `build_max_result.py` must have zero I/O: no CSV reading, no file writing, no arcpy, no openpyxl imports anywhere in the module.
- Screening levels YAML format (analyte-first): `{canonical_name: {matrix: {"unit": str, "level": float, "source": str}}}` — same format consumed by `apply_screening_levels()`.
- TDD order: failing tests committed first, implementation added to make them pass.
- `python -m pytest -q` must stay green at every commit; no new `import arcpy` in core or adapters.
- Nondetect handling for `max_detected`: detected records win; fall back to highest `ReportingLimit` only when ALL records in a group are nondetects.
- Nondetect handling for `max_exceedance_ratio`: nondetects enter ratio competition using `ReportingLimit / sl_level` (conservative upper bound).
- Unit conversion for `max_exceedance_ratio`: convert result to screening-level unit before dividing; emit `SEV_WARNING / "unit_conversion_failed"` and exclude the record from ranking if conversion fails (incompatible dimensions or unknown unit).

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `autogis/core/envmon/build_max_result.py` | `MaxResultRecord` dataclass + `build_max_result_dataset()` core function |
| Modify | `autogis/adapters/cli.py` | Add `build-max-result` command to the `envmon` group |
| Create | `tests/envmon/test_build_max_result.py` | All unit tests (core + CLI smoke tests) |

---

## Task 1: Core Module + Tests

**Files:**
- Create: `autogis/core/envmon/build_max_result.py`
- Create: `tests/envmon/test_build_max_result.py`

**Interfaces:**
- Consumes: `AnalyticalResultRecord` from `autogis.core.envmon.gdb_schema`; `QACollector`, `SEV_INFO`, `SEV_WARNING`, `SEV_ERROR` from `autogis.core.common.qa`; `same_dimension`, `convert` from `autogis.core.common.units`
- Produces: `MaxResultRecord` dataclass (all fields listed in Step 3); `build_max_result_dataset(results, mode, date_range, qa, *, screening_levels, site_id, matrix)` returning `List[MaxResultRecord]`

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_build_max_result.py`:

```python
"""Tests for build_max_result_dataset (Tool 4.9)."""
from __future__ import annotations

import datetime
from typing import Optional

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.build_max_result import (
    MaxResultRecord,
    build_max_result_dataset,
)
from autogis.core.envmon.gdb_schema import AnalyticalResultRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt(s: Optional[str]) -> Optional[datetime.date]:
    return datetime.date.fromisoformat(s) if s else None


def _make(
    analyte: str = "Benzene",
    result: Optional[float] = 1.0,
    units: str = "ug/L",
    nd: bool = False,
    rl: Optional[float] = 1.0,
    matrix: str = "GW",
    location: str = "MW-01",
    site: str = "SITE1",
    sample_date: Optional[str] = "2024-01-15",
    sl: Optional[float] = None,
    sl_src: str = "",
    exceeds: Optional[int] = None,
    sample_id: str = "S001",
) -> AnalyticalResultRecord:
    return AnalyticalResultRecord(
        ImportBatchID="B1", SiteID=site, Matrix=matrix,
        LocationID=location, SampleID=sample_id, ParentSampleID="",
        SampleDate=_dt(sample_date),
        DepthTop_ft=None, DepthBottom_ft=None, DepthIntervalText="",
        AnalyticalGroup="VOC", MethodGroup="EPA8260",
        AnalyteName=analyte, AnalyteCanonicalName=analyte,
        AnalyteAbbreviation=analyte[:3].upper(),
        ResultRawText="" if result is None else str(result),
        ResultNumeric=result,
        ReportingLimit=rl, DetectionLimit=rl,
        Units=units,
        Qualifier="U" if nd else "",
        IsNonDetect=int(nd), IsDetected=int(not nd),
        IsEstimated=0, IsDiluted=0, IsNotAnalyzed=0,
        IsNotSampled=0, IsNotMeasured=0,
        ScreeningLevel=sl, ScreeningLevelSource=sl_src,
        ExceedsScreeningLevel=exceeds,
        DisplayText="", DisplayColorClass="",
        SourceWorkbook="", SourceSheet="", SourceRow=0,
        SourceColumn="", SourceCell="",
    )


# ---------------------------------------------------------------------------
# max_detected mode
# ---------------------------------------------------------------------------

def test_max_detected_picks_higher_value():
    """Two detected results for the same group — higher ResultNumeric wins."""
    r1 = _make(result=10.0, sample_id="S001", sample_date="2024-01-10")
    r2 = _make(result=25.0, sample_id="S002", sample_date="2024-02-10")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r1, r2], mode="max_detected", date_range=None, qa=qa
    )
    assert len(rows) == 1
    assert rows[0].MaxResultNumeric == 25.0
    assert rows[0].MaxSampleID == "S002"


def test_max_detected_all_nondetects_picks_highest_rl():
    """When every record in a group is a nondetect, pick the highest RL."""
    r1 = _make(nd=True, result=None, rl=2.0, sample_id="S001")
    r2 = _make(nd=True, result=None, rl=5.0, sample_id="S002")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r1, r2], mode="max_detected", date_range=None, qa=qa
    )
    assert len(rows) == 1
    assert rows[0].IsNonDetect == 1
    assert rows[0].ReportingLimit == 5.0
    assert rows[0].MaxResultNumeric is None


def test_max_detected_detected_beats_nondetect():
    """A detected record always wins over a nondetect, even if RL is higher."""
    r_nd = _make(nd=True, result=None, rl=100.0, sample_id="S001")
    r_det = _make(result=0.5, rl=1.0, sample_id="S002")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r_nd, r_det], mode="max_detected", date_range=None, qa=qa
    )
    assert len(rows) == 1
    assert rows[0].IsNonDetect == 0
    assert rows[0].MaxResultNumeric == 0.5


def test_date_range_filter_excludes_outside():
    """Record outside the date range is not considered."""
    r_in = _make(result=5.0, sample_id="S001", sample_date="2024-03-01")
    r_out = _make(result=99.0, sample_id="S002", sample_date="2023-01-01")
    qa = QACollector()
    start = datetime.date(2024, 1, 1)
    end = datetime.date(2024, 12, 31)
    rows = build_max_result_dataset(
        [r_in, r_out], mode="max_detected",
        date_range=(start, end), qa=qa
    )
    assert len(rows) == 1
    assert rows[0].MaxResultNumeric == 5.0


def test_no_records_after_filter_produces_no_output():
    """All records filtered by date range → empty output + QA warning."""
    r = _make(result=5.0, sample_date="2020-01-01")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r], mode="max_detected",
        date_range=(datetime.date(2024, 1, 1), datetime.date(2024, 12, 31)),
        qa=qa,
    )
    assert rows == []
    assert any(rec.category == "no_records_after_filter" for rec in qa.records)


def test_multiple_locations_are_independent():
    """Records at two locations produce two output rows."""
    r1 = _make(location="MW-01", result=10.0)
    r2 = _make(location="MW-02", result=20.0)
    qa = QACollector()
    rows = build_max_result_dataset(
        [r1, r2], mode="max_detected", date_range=None, qa=qa
    )
    assert len(rows) == 2
    locs = {r.LocationID for r in rows}
    assert locs == {"MW-01", "MW-02"}


def test_multiple_analytes_per_location():
    """Two analytes at same location produce two independent output rows."""
    r1 = _make(analyte="Benzene", result=10.0)
    r2 = _make(analyte="Toluene", result=5.0)
    qa = QACollector()
    rows = build_max_result_dataset(
        [r1, r2], mode="max_detected", date_range=None, qa=qa
    )
    assert len(rows) == 2
    analytes = {r.AnalyteCanonicalName for r in rows}
    assert analytes == {"Benzene", "Toluene"}


def test_matrix_filter():
    """Records with non-matching matrix are excluded when matrix filter set."""
    r_gw = _make(matrix="GW", result=10.0)
    r_soil = _make(matrix="SOIL", result=99.0)
    qa = QACollector()
    rows = build_max_result_dataset(
        [r_gw, r_soil], mode="max_detected", date_range=None, qa=qa,
        matrix="GW",
    )
    assert len(rows) == 1
    assert rows[0].Matrix == "GW"


# ---------------------------------------------------------------------------
# max_exceedance_ratio mode
# ---------------------------------------------------------------------------

SL_BENZENE_GW = {"Benzene": {"GW": {"unit": "ug/L", "level": 5.0, "source": "RBSL"}}}


def test_max_exceedance_ratio_selects_highest():
    """Record with higher ratio (result/sl) is selected."""
    r1 = _make(result=10.0, sample_id="S001", sample_date="2024-01-01")  # ratio 2.0
    r2 = _make(result=30.0, sample_id="S002", sample_date="2024-02-01")  # ratio 6.0
    qa = QACollector()
    rows = build_max_result_dataset(
        [r1, r2], mode="max_exceedance_ratio", date_range=None, qa=qa,
        screening_levels=SL_BENZENE_GW,
    )
    assert len(rows) == 1
    assert rows[0].MaxSampleID == "S002"
    assert rows[0].MaxExceedanceRatio == pytest.approx(6.0)


def test_max_exceedance_ratio_nondetect_uses_rl():
    """Nondetects participate in ratio ranking using ReportingLimit / sl_level."""
    # RL=20 ug/L, sl=5 ug/L -> conservative ratio = 4.0
    # Detected result=10 ug/L -> ratio = 2.0
    # Nondetect wins because 4.0 > 2.0
    r_det = _make(result=10.0, nd=False, rl=1.0, sample_id="S001")
    r_nd = _make(result=None, nd=True, rl=20.0, sample_id="S002")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r_det, r_nd], mode="max_exceedance_ratio", date_range=None, qa=qa,
        screening_levels=SL_BENZENE_GW,
    )
    assert len(rows) == 1
    assert rows[0].MaxSampleID == "S002"
    assert rows[0].MaxExceedanceRatio == pytest.approx(4.0)


def test_max_exceedance_ratio_no_screening_emits_warning():
    """Analyte with no screening level emits a QA warning, produces no row."""
    r = _make(analyte="Toluene", result=99.0)  # not in SL_BENZENE_GW
    qa = QACollector()
    rows = build_max_result_dataset(
        [r], mode="max_exceedance_ratio", date_range=None, qa=qa,
        screening_levels=SL_BENZENE_GW,
    )
    assert rows == []
    assert any(rec.category == "no_screening_level" for rec in qa.records)


def test_max_exceedance_ratio_unit_conversion():
    """Result in mg/L, screening in ug/L — converts before computing ratio."""
    # 0.001 mg/L = 1.0 ug/L; ratio = 1.0 / 5.0 = 0.2
    r = _make(result=0.001, units="mg/L")
    qa = QACollector()
    rows = build_max_result_dataset(
        [r], mode="max_exceedance_ratio", date_range=None, qa=qa,
        screening_levels=SL_BENZENE_GW,
    )
    assert len(rows) == 1
    assert rows[0].MaxExceedanceRatio == pytest.approx(0.2, rel=1e-6)


def test_max_exceedance_ratio_incompatible_units_warns_and_skips():
    """Unit-conversion failure emits a warning; group is excluded from output."""
    r = _make(result=10.0, units="mg/kg")  # soil unit vs GW ug/L — incompatible
    qa = QACollector()
    rows = build_max_result_dataset(
        [r], mode="max_exceedance_ratio", date_range=None, qa=qa,
        screening_levels=SL_BENZENE_GW,
    )
    assert rows == []
    assert any(rec.category == "unit_conversion_failed" for rec in qa.records)


# ---------------------------------------------------------------------------
# QA / summary record
# ---------------------------------------------------------------------------

def test_summary_info_record_emitted():
    """A build_max_result_complete INFO record is always emitted."""
    r = _make(result=5.0)
    qa = QACollector()
    build_max_result_dataset([r], mode="max_detected", date_range=None, qa=qa)
    assert any(rec.category == "build_max_result_complete" for rec in qa.records)
```

- [ ] **Step 2: Run tests to verify they fail (ImportError expected)**

```
python -m pytest tests/envmon/test_build_max_result.py -q
```

Expected: `ImportError: cannot import name 'MaxResultRecord' from 'autogis.core.envmon.build_max_result'` (or `ModuleNotFoundError`). All tests should fail — none should pass.

- [ ] **Step 3: Implement the core module**

Create `autogis/core/envmon/build_max_result.py`:

```python
"""Build max-result map dataset (Tool 4.9).

Headless, arcpy-free. Scans AnalyticalResultRecords over a date range and
produces one MaxResultRecord per (LocationID, Matrix, AnalyteCanonicalName)
group, selecting either the maximum detected value or the maximum exceedance
ratio (result / screening_level).

Differentiation from build_current_event.py: build_current_event picks ONE
sample per location (max of target analytes) and pivots to a wide row. This
module picks the max per analyte independently — each analyte's maximum can
come from a different date and different sample — and produces narrow records.
"""
from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .gdb_schema import AnalyticalResultRecord
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING
from ..common.units import same_dimension, convert


@dataclass
class MaxResultRecord:
    SiteID: str
    LocationID: str
    Matrix: str
    AnalyteCanonicalName: str
    AnalyteAbbreviation: str
    SelectionMode: str                   # "max_detected" | "max_exceedance_ratio"
    DateRangeStart: Optional[datetime.date]
    DateRangeEnd: Optional[datetime.date]
    MaxSampleDate: Optional[datetime.date]
    MaxSampleID: str
    MaxResultRawText: str
    MaxResultNumeric: Optional[float]
    MaxResultUnits: str
    IsNonDetect: int
    ReportingLimit: Optional[float]
    ExceedsScreening: Optional[int]
    ScreeningLevel: Optional[float]
    ScreeningLevelSource: str
    ScreeningLevelUnit: str              # unit used for ratio computation; "" when N/A
    MaxExceedanceRatio: Optional[float]


def _in_range(
    r: AnalyticalResultRecord,
    date_range: Optional[Tuple[datetime.date, datetime.date]],
) -> bool:
    if date_range is None:
        return True
    if r.SampleDate is None:
        return False
    start, end = date_range
    return start <= r.SampleDate <= end


def _ratio(
    r: AnalyticalResultRecord,
    sl_entry: dict,
    qa: QACollector,
) -> Optional[float]:
    """Compute (converted_result_or_rl) / sl_level.

    For detected records: uses ResultNumeric.
    For nondetects: uses ReportingLimit as a conservative upper bound.
    Returns None if unit conversion fails or required values are missing.
    Emits SEV_WARNING / "unit_conversion_failed" on conversion failure.
    """
    sl_val: Optional[float] = sl_entry.get("level")
    sl_unit: str = sl_entry.get("unit", r.Units) or r.Units
    if sl_val is None or sl_val == 0:
        return None

    numerator: Optional[float]
    if r.IsNonDetect:
        numerator = r.ReportingLimit
    else:
        numerator = r.ResultNumeric
    if numerator is None:
        return None

    if r.Units and sl_unit and r.Units != sl_unit:
        try:
            if not same_dimension(r.Units, sl_unit):
                raise ValueError(
                    f"incompatible dimensions: {r.Units!r} vs {sl_unit!r}")
            numerator = convert(numerator, r.Units, sl_unit)
        except Exception as exc:
            qa.add(SEV_WARNING, "unit_conversion_failed",
                   f"{r.LocationID}/{r.AnalyteCanonicalName}: {exc}",
                   location_id=r.LocationID,
                   analyte_name=r.AnalyteCanonicalName)
            return None

    return numerator / sl_val


def build_max_result_dataset(
    results: List[AnalyticalResultRecord],
    mode: str,
    date_range: Optional[Tuple[datetime.date, datetime.date]],
    qa: QACollector,
    *,
    screening_levels: Optional[dict] = None,
    site_id: Optional[str] = None,
    matrix: Optional[str] = None,
) -> List[MaxResultRecord]:
    """Build per-location/per-analyte max-result records.

    Args:
        results: Analytical result records (all dates, all analytes).
        mode: "max_detected" — pick highest ResultNumeric (falls back to
              highest ReportingLimit if all records are nondetects).
              "max_exceedance_ratio" — pick highest result/sl ratio;
              nondetects participate using RL/sl.
        date_range: Optional (start, end) inclusive filter on SampleDate.
        qa: QA collector.
        screening_levels: Required for max_exceedance_ratio.
              Format: {canonical_name: {matrix: {"unit": str, "level": float,
              "source": str}}}. Groups with no matching entry emit a QA warning
              and are omitted from output.
        site_id: Optional filter; if set, only records with matching SiteID
              are included.
        matrix: Optional filter; if set, only records with matching Matrix
              are included.

    Returns:
        List[MaxResultRecord], one per (LocationID, Matrix,
        AnalyteCanonicalName) group.
    """
    if mode not in ("max_detected", "max_exceedance_ratio"):
        raise ValueError(f"Invalid mode {mode!r}; "
                         "expected 'max_detected' or 'max_exceedance_ratio'")

    sl = screening_levels or {}

    # 1. Filter
    filtered = [
        r for r in results
        if _in_range(r, date_range)
        and (site_id is None or r.SiteID == site_id)
        and (matrix is None or r.Matrix == matrix)
    ]
    if not filtered:
        qa.add(SEV_WARNING, "no_records_after_filter",
               "build_max_result_dataset: no records remain after filtering")
        qa.add(SEV_INFO, "build_max_result_complete",
               "build_max_result_dataset: 0 max-result record(s) produced")
        return []

    # 2. Group by (LocationID, Matrix, AnalyteCanonicalName)
    groups: Dict[tuple, List[AnalyticalResultRecord]] = defaultdict(list)
    for r in filtered:
        groups[(r.LocationID, r.Matrix, r.AnalyteCanonicalName)].append(r)

    output: List[MaxResultRecord] = []

    for (loc_id, mat, analyte), recs in groups.items():
        sl_entry: dict = sl.get(analyte, {}).get(mat, {})

        if mode == "max_detected":
            winner = _pick_max_detected(recs)
            ratio: Optional[float] = None
            sl_level: Optional[float] = sl_entry.get("level") if sl_entry else None
            sl_src: str = sl_entry.get("source", "") if sl_entry else ""
            sl_unit_str: str = sl_entry.get("unit", "") if sl_entry else ""

        else:  # max_exceedance_ratio
            if not sl_entry:
                qa.add(SEV_WARNING, "no_screening_level",
                       f"No screening level for {analyte!r}/{mat!r}; group skipped",
                       location_id=loc_id, analyte_name=analyte)
                continue
            winner, ratio = _pick_max_ratio(recs, sl_entry, qa)
            if winner is None:
                # All records failed unit conversion — already warned in _ratio()
                continue
            sl_level = sl_entry.get("level")
            sl_src = sl_entry.get("source", "")
            sl_unit_str = sl_entry.get("unit", "")

        output.append(MaxResultRecord(
            SiteID=winner.SiteID,
            LocationID=loc_id,
            Matrix=mat,
            AnalyteCanonicalName=analyte,
            AnalyteAbbreviation=winner.AnalyteAbbreviation,
            SelectionMode=mode,
            DateRangeStart=date_range[0] if date_range else None,
            DateRangeEnd=date_range[1] if date_range else None,
            MaxSampleDate=winner.SampleDate,
            MaxSampleID=winner.SampleID,
            MaxResultRawText=winner.ResultRawText or "",
            MaxResultNumeric=winner.ResultNumeric,
            MaxResultUnits=winner.Units,
            IsNonDetect=winner.IsNonDetect,
            ReportingLimit=winner.ReportingLimit,
            ExceedsScreening=winner.ExceedsScreeningLevel,
            ScreeningLevel=sl_level,
            ScreeningLevelSource=sl_src,
            ScreeningLevelUnit=sl_unit_str,
            MaxExceedanceRatio=ratio,
        ))

    qa.add(SEV_INFO, "build_max_result_complete",
           f"build_max_result_dataset: {len(output)} max-result record(s) produced")
    return output


def _pick_max_detected(
    recs: List[AnalyticalResultRecord],
) -> AnalyticalResultRecord:
    """Select record with max ResultNumeric; fall back to highest RL if all nondetects."""
    detected = [r for r in recs if r.IsDetected and r.ResultNumeric is not None]
    if detected:
        return max(detected, key=lambda r: r.ResultNumeric)  # type: ignore[return-value]
    # All nondetects: pick highest ReportingLimit as a conservative bound.
    with_rl = [r for r in recs if r.ReportingLimit is not None]
    pool = with_rl if with_rl else recs
    return max(pool, key=lambda r: (r.ReportingLimit or 0.0))


def _pick_max_ratio(
    recs: List[AnalyticalResultRecord],
    sl_entry: dict,
    qa: QACollector,
) -> Tuple[Optional[AnalyticalResultRecord], Optional[float]]:
    """Select record with max exceedance ratio. Returns (winner, ratio) or (None, None)."""
    best: Optional[AnalyticalResultRecord] = None
    best_ratio: Optional[float] = None
    for r in recs:
        r_ratio = _ratio(r, sl_entry, qa)
        if r_ratio is None:
            continue
        if best_ratio is None or r_ratio > best_ratio:
            best = r
            best_ratio = r_ratio
    return best, best_ratio
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/envmon/test_build_max_result.py -v
```

Expected: all 15 tests pass. If any fail, read the traceback and fix the implementation — do NOT modify tests to make them pass.

- [ ] **Step 5: Run the full suite to ensure no regressions**

```
python -m pytest -q
```

Expected: all tests pass (560+ passing, 0 failed). Fix any regressions before committing.

- [ ] **Step 6: Commit Task 1**

```bash
git add autogis/core/envmon/build_max_result.py tests/envmon/test_build_max_result.py
git commit -m "feat(envmon): add build_max_result_dataset core module (Tool 4.9)

Headless, arcpy-free. Groups AnalyticalResultRecord rows by (LocationID,
Matrix, AnalyteCanonicalName) and selects the maximum detected value or
maximum exceedance ratio per group. Ratio mode unit-converts before dividing
using same_dimension/convert from common.units. 15 tests."
```

---

## Task 2: CLI Command + CLI Tests

**Files:**
- Modify: `autogis/adapters/cli.py` (add `build-max-result` command to the `envmon` group)
- Modify: `tests/envmon/test_build_max_result.py` (append CLI tests)

**Interfaces:**
- Consumes: `build_max_result_dataset` + `MaxResultRecord` from Task 1; `read_records_csv` from `autogis.core.envmon.evaluate_rpd_qa`; `_render_qa` already in `cli.py` at line ~865; `AnalyticalResultRecord` from `gdb_schema`; `yaml.safe_load` (already imported at top of cli.py).
- Produces: CLI command `autogis envmon build-max-result --results-csv PATH --out PATH [options]`

**CLI surface:**

```
autogis envmon build-max-result
  --results-csv PATH   (required) Input CSV of AnalyticalResultRecord rows
  --out PATH           (required) Output CSV path
  --mode [max_detected|max_exceedance_ratio]  (default: max_detected)
  --date-from DATE     (optional) Start date YYYY-MM-DD, inclusive
  --date-to DATE       (optional) End date YYYY-MM-DD, inclusive
  --matrix TEXT        (optional) Filter to one matrix (e.g. GW, SOIL)
  --site TEXT          (optional) Filter to one SiteID
  --screening PATH     (optional) Screening levels YAML; required for
                         max_exceedance_ratio mode
  --report PATH        (optional) Write QA report CSV to this path
  --fail-on [error|warning]  (default: error) Exit non-zero threshold
```

**Output CSV columns** (in order): all fields of `MaxResultRecord` in dataclass definition order.

- [ ] **Step 1: Append CLI tests to the test file**

Append to `tests/envmon/test_build_max_result.py`:

```python
# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------
import csv
import os
import tempfile

from click.testing import CliRunner

from autogis.adapters.cli import cli


def _write_results_csv(path: str, records: list) -> None:
    """Write AnalyticalResultRecord list to CSV (all fields)."""
    import dataclasses
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    cols = [f.name for f in dataclasses.fields(AnalyticalResultRecord)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for rec in records:
            row = dataclasses.asdict(rec)
            # dates need string form
            for k, v in row.items():
                if isinstance(v, datetime.date):
                    row[k] = v.isoformat()
                elif v is None:
                    row[k] = ""
            w.writerow(row)


def test_build_max_result_in_help():
    """build-max-result appears in envmon --help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["envmon", "--help"])
    assert result.exit_code == 0, result.output
    assert "build-max-result" in result.output


def test_build_max_result_cli_max_detected():
    """CLI runs end-to-end in max_detected mode and writes output CSV."""
    runner = CliRunner()
    rec = _make(result=7.5, sample_id="S-CLITEST", sample_date="2024-05-01")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "results.csv")
        out = os.path.join(td, "max_result.csv")
        _write_results_csv(inp, [rec])
        result = runner.invoke(cli, [
            "envmon", "build-max-result",
            "--results-csv", inp,
            "--out", out,
            "--mode", "max_detected",
        ])
        assert result.exit_code == 0, result.output
        assert os.path.exists(out)
        with open(out, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["MaxResultNumeric"] == "7.5"
        assert rows[0]["MaxSampleID"] == "S-CLITEST"


def test_build_max_result_cli_date_filter():
    """CLI --date-from / --date-to filter excludes records outside range."""
    runner = CliRunner()
    r_in = _make(result=5.0, sample_id="S-IN", sample_date="2024-06-01")
    r_out = _make(result=99.0, sample_id="S-OUT", sample_date="2020-01-01")
    with tempfile.TemporaryDirectory() as td:
        inp = os.path.join(td, "results.csv")
        out = os.path.join(td, "max_result.csv")
        _write_results_csv(inp, [r_in, r_out])
        result = runner.invoke(cli, [
            "envmon", "build-max-result",
            "--results-csv", inp,
            "--out", out,
            "--date-from", "2024-01-01",
            "--date-to", "2024-12-31",
        ])
        assert result.exit_code == 0, result.output
        with open(out, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["MaxSampleID"] == "S-IN"
```

- [ ] **Step 2: Run CLI tests to verify they fail**

```
python -m pytest tests/envmon/test_build_max_result.py::test_build_max_result_in_help tests/envmon/test_build_max_result.py::test_build_max_result_cli_max_detected tests/envmon/test_build_max_result.py::test_build_max_result_cli_date_filter -v
```

Expected: `test_build_max_result_in_help` fails with `AssertionError: 'build-max-result' not found in output`. The other two fail with the same assertion. None should pass.

- [ ] **Step 3: Add the CLI command to cli.py**

Open `autogis/adapters/cli.py`. Find the `envmon` Click group. Locate the block of `@envmon.command(...)` definitions. Add the following command — place it after the existing `compare-events` command (search for `@envmon.command("compare-events")` and append after its closing `_render_qa` call):

```python
@envmon.command("build-max-result")
@click.option("--results-csv", required=True, type=click.Path(exists=True),
              help="Input CSV of AnalyticalResultRecord rows.")
@click.option("--out", required=True, type=click.Path(),
              help="Output CSV path.")
@click.option("--mode",
              type=click.Choice(["max_detected", "max_exceedance_ratio"]),
              default="max_detected", show_default=True,
              help="Selection mode.")
@click.option("--date-from", "date_from", default=None,
              help="Start date filter (YYYY-MM-DD, inclusive).")
@click.option("--date-to", "date_to", default=None,
              help="End date filter (YYYY-MM-DD, inclusive).")
@click.option("--matrix", default=None,
              help="Filter to one matrix value (e.g. GW, SOIL).")
@click.option("--site", "site_id", default=None,
              help="Filter to one SiteID.")
@click.option("--screening", "screening_path", default=None,
              type=click.Path(exists=True),
              help="Screening levels YAML (required for max_exceedance_ratio).")
@click.option("--report", default=None, type=click.Path(),
              help="Write QA report CSV to this path.")
@click.option("--fail-on",
              type=click.Choice(["error", "warning"]), default="error",
              show_default=True,
              help="Exit non-zero when QA records at this severity or higher exist.")
def build_max_result_cmd(results_csv, out, mode, date_from, date_to,
                          matrix, site_id, screening_path, report, fail_on):
    """Build per-location/per-analyte maximum result records for map datasets."""
    import csv as _csv
    import datetime as _dt
    import yaml as _yaml
    from dataclasses import asdict, fields as _fields
    from pathlib import Path

    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.gdb_schema import AnalyticalResultRecord
    from autogis.core.envmon.build_max_result import (
        build_max_result_dataset,
        MaxResultRecord,
    )

    if mode == "max_exceedance_ratio" and screening_path is None:
        raise click.UsageError(
            "--screening is required when --mode is max_exceedance_ratio"
        )

    results = read_records_csv(Path(results_csv), AnalyticalResultRecord)

    screening_levels = None
    if screening_path:
        screening_levels = _yaml.safe_load(
            Path(screening_path).read_text(encoding="utf-8")
        )

    date_range = None
    if date_from or date_to:
        start = _dt.date.fromisoformat(date_from) if date_from else _dt.date.min
        end = _dt.date.fromisoformat(date_to) if date_to else _dt.date.max
        date_range = (start, end)

    qa = QACollector()
    rows = build_max_result_dataset(
        results, mode=mode, date_range=date_range, qa=qa,
        screening_levels=screening_levels,
        site_id=site_id,
        matrix=matrix,
    )

    cols = [f.name for f in _fields(MaxResultRecord)]
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for rec in rows:
            w.writerow(asdict(rec))

    click.echo(f"Written: {out_path}  ({len(rows)} max-result row(s))")
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests to verify they pass**

```
python -m pytest tests/envmon/test_build_max_result.py::test_build_max_result_in_help tests/envmon/test_build_max_result.py::test_build_max_result_cli_max_detected tests/envmon/test_build_max_result.py::test_build_max_result_cli_date_filter -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Run the full suite**

```
python -m pytest -q
```

Expected: all tests pass (563+ passing, 0 failed). Fix any regressions before committing.

- [ ] **Step 6: Commit Task 2**

```bash
git add autogis/adapters/cli.py tests/envmon/test_build_max_result.py
git commit -m "feat(envmon): add build-max-result CLI command (Tool 4.9)

Wires build_max_result_dataset into 'autogis envmon build-max-result'.
Supports max_detected and max_exceedance_ratio modes, date-range filter,
matrix filter, site filter, and optional screening-levels YAML.
3 CLI smoke tests."
```

---

## Risks and Assumptions

### Nondetect handling (max_detected mode)

**Assumption:** when ALL records in a group are nondetects, picking the highest `ReportingLimit` is the appropriate conservative output. The produced row has `IsNonDetect=1` and `MaxResultNumeric=None`. Downstream map code must treat this differently from a detected value.

**Risk:** if a site uses different RLs for different sampling rounds (because MDL changed), the selected RL may not be representative. Mitigation: the output carries `MaxSampleDate` and `MaxSampleID`, so the analyst can trace the provenance.

### Mixed units (max_exceedance_ratio mode)

**Assumption:** the UNIT_REGISTRY in `common/units.py` covers all units used in screening level YAMLs (ng/L, ug/L, mg/L, g/L for aqueous; ug/kg, mg/kg, g/kg for soil). Units not in the registry (e.g. `CFU/100mL`, `pCi/L`) will fail `normalize_unit`, causing a `UnitError` in `convert`. The group is excluded from output with a `SEV_WARNING / "unit_conversion_failed"` QA record.

**Risk:** ppb/ppm are explicitly excluded from the registry (see module docstring in units.py) because they are dimension-ambiguous. Screening levels files that use ppb instead of ug/L will silently fail unit conversion. The QA warning surface this, but the output gap may not be obvious. Mitigation: `--fail-on warning` will fail the CLI run, forcing the analyst to review.

### Date range open-endedness

**Assumption:** when `--date-from` is set but `--date-to` is absent (or vice versa), the open end defaults to `datetime.date.min` / `datetime.date.max`. Records with `SampleDate=None` are always excluded from a date-filtered run.

### Screening levels file format

**Assumption:** the screening levels YAML uses the analyte-first nested format consumed by `apply_screening_levels()`:
```yaml
Benzene:
  GW:
    unit: "ug/L"
    level: 5.0
    source: "RBSL"
```
This is the format produced by the `manage-screening-levels` workflow and confirmed in `tests/test_apply_screening.py`. If a YAML uses the matrix-first format (as used internally by `manage_screening_levels.load_screening_entries`), all lookups will miss and every group will emit `"no_screening_level"` warnings. The analyst must pass a correctly formatted file.

### Arcpy-free invariant

The core module imports only stdlib + intra-package modules. The `envmon-spec-checker` agent should be run before merging to verify no arcpy/arcgis imports have crept in.
