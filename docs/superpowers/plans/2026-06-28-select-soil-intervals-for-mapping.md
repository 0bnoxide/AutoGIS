# SelectSoilIntervalsForMapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `SelectSoilIntervalsForMapping` — assign each soil sample interval a display tier (`HOTSPOT`, `DETECT`, `ND`, `NO_DATA`) and produce a filtered CSV for the cartography pipeline.
See spec: `docs/superpowers/specs/2026-06-28-select-soil-intervals-for-mapping-design.md`.

**Architecture:**
- New: `autogis/core/envmon/soil_interval_selector.py`
- Modify: `autogis/adapters/cli.py` — add `select-soil-intervals` command (CLOUD)
- New: `tests/envmon/test_soil_interval_selector.py`

## Global Constraints

- Arcpy-free. stdlib + `csv` only — no openpyxl.
- `QACollector` / `QARecord` / `SEV_INFO` / `SEV_WARNING` from `autogis.core.common.qa`.
- ND detection: `ResultQualifier` in `{"ND", "U", "BDL"}` (case-insensitive strip) OR `ResultValue` absent/blank.
- `ExceedsScreeningLevel` column in the input CSV is the canonical exceedance flag (`"True"` / `"1"` / `"yes"` case-insensitive).
- Output CSV columns: `LocationID`, `TopDepthFt`, `BottomDepthFt`, `AnalyteName`, `ResultValue`, `IsDetect`, `ExceedsScreening`, `ScreeningLevel`, `Units`, `DisplayTier`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `soil_interval_selector.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_soil_interval_selector.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.soil_interval_selector import (
    SoilInterval, IntervalTier,
    assign_tier, select_intervals, load_soil_results_csv,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _interval(
    *,
    result_value=1.0,
    is_detect=True,
    exceeds_screening=False,
    screening_level=5.0,
    analyte_name="Benzene",
    location_id="B-01",
    top_depth_ft=0.0,
    bottom_depth_ft=2.0,
    units="mg/kg",
):
    return SoilInterval(
        location_id=location_id,
        top_depth_ft=top_depth_ft,
        bottom_depth_ft=bottom_depth_ft,
        analyte_name=analyte_name,
        result_value=result_value,
        is_detect=is_detect,
        exceeds_screening=exceeds_screening,
        screening_level=screening_level,
        units=units,
    )


# ---------------------------------------------------------------------------
# assign_tier — 4 cases
# ---------------------------------------------------------------------------

def test_assign_tier_hotspot():
    iv = _interval(result_value=10.0, is_detect=True, exceeds_screening=True)
    assert assign_tier(iv) == IntervalTier.HOTSPOT


def test_assign_tier_detect():
    iv = _interval(result_value=1.0, is_detect=True, exceeds_screening=False)
    assert assign_tier(iv) == IntervalTier.DETECT


def test_assign_tier_nd():
    iv = _interval(result_value=None, is_detect=False, exceeds_screening=False,
                   screening_level=None)
    assert assign_tier(iv) == IntervalTier.ND


def test_assign_tier_no_data():
    iv = _interval(result_value=None, is_detect=False, exceeds_screening=False,
                   screening_level=5.0)
    # result_value is None → NO_DATA
    assert assign_tier(iv) == IntervalTier.NO_DATA


# ---------------------------------------------------------------------------
# select_intervals — filtering
# ---------------------------------------------------------------------------

_BASE = [
    _interval(location_id="B-01", analyte_name="Benzene",
              result_value=10.0, is_detect=True, exceeds_screening=True,
              top_depth_ft=0.0, bottom_depth_ft=2.0),
    _interval(location_id="B-01", analyte_name="TPH",
              result_value=50.0, is_detect=True, exceeds_screening=False,
              top_depth_ft=0.0, bottom_depth_ft=2.0),
    _interval(location_id="B-02", analyte_name="Benzene",
              result_value=None, is_detect=False, exceeds_screening=False,
              top_depth_ft=0.0, bottom_depth_ft=2.0, screening_level=5.0),
    _interval(location_id="B-01", analyte_name="Benzene",
              result_value=2.0, is_detect=True, exceeds_screening=False,
              top_depth_ft=10.0, bottom_depth_ft=12.0),
]


def test_select_intervals_returns_all_when_no_filters():
    out = select_intervals(_BASE)
    assert len(out) == 4


def test_select_intervals_output_has_display_tier():
    out = select_intervals(_BASE)
    assert all("display_tier" in row for row in out)


def test_select_intervals_filter_by_tier_hotspot():
    out = select_intervals(_BASE, tiers=["HOTSPOT"])
    assert all(row["display_tier"] == "HOTSPOT" for row in out)
    assert len(out) == 1


def test_select_intervals_filter_by_analyte():
    out = select_intervals(_BASE, analytes=["Benzene"])
    analytes = {row["analyte_name"] for row in out}
    assert analytes == {"Benzene"}
    assert len(out) == 3


def test_select_intervals_filter_by_max_depth():
    out = select_intervals(_BASE, max_depth_ft=5.0)
    # Only intervals with top_depth_ft <= 5.0
    assert all(row["top_depth_ft"] <= 5.0 for row in out)
    assert len(out) == 3


def test_select_intervals_output_fields():
    out = select_intervals(_BASE[:1])
    row = out[0]
    required = {
        "location_id", "top_depth_ft", "bottom_depth_ft", "analyte_name",
        "result_value", "is_detect", "exceeds_screening", "screening_level",
        "units", "display_tier",
    }
    assert required.issubset(row.keys())


# ---------------------------------------------------------------------------
# load_soil_results_csv
# ---------------------------------------------------------------------------

def test_load_soil_results_csv_basic(tmp_path):
    csv_path = tmp_path / "soil.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "LocationID", "TopDepthFt", "BottomDepthFt",
            "AnalyteName", "ResultValue", "ResultQualifier",
            "ReportedUnits", "ScreeningLevel", "ExceedsScreeningLevel",
        ])
        w.writeheader()
        w.writerow({
            "LocationID": "B-01", "TopDepthFt": "0", "BottomDepthFt": "2",
            "AnalyteName": "Benzene", "ResultValue": "10.5",
            "ResultQualifier": "", "ReportedUnits": "mg/kg",
            "ScreeningLevel": "5.0", "ExceedsScreeningLevel": "True",
        })
        w.writerow({
            "LocationID": "B-02", "TopDepthFt": "2", "BottomDepthFt": "4",
            "AnalyteName": "Benzene", "ResultValue": "",
            "ResultQualifier": "ND", "ReportedUnits": "mg/kg",
            "ScreeningLevel": "5.0", "ExceedsScreeningLevel": "False",
        })
    intervals = load_soil_results_csv(csv_path)
    assert len(intervals) == 2
    assert intervals[0].exceeds_screening is True
    assert intervals[0].is_detect is True
    assert intervals[0].result_value == pytest.approx(10.5)


def test_load_soil_results_csv_nd_qualifier(tmp_path):
    csv_path = tmp_path / "soil.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "LocationID", "TopDepthFt", "BottomDepthFt",
            "AnalyteName", "ResultValue", "ResultQualifier",
            "ReportedUnits", "ScreeningLevel", "ExceedsScreeningLevel",
        ])
        w.writeheader()
        w.writerow({
            "LocationID": "B-03", "TopDepthFt": "0", "BottomDepthFt": "2",
            "AnalyteName": "TPH", "ResultValue": "50",
            "ResultQualifier": "U", "ReportedUnits": "mg/kg",
            "ScreeningLevel": "", "ExceedsScreeningLevel": "False",
        })
    intervals = load_soil_results_csv(csv_path)
    assert intervals[0].is_detect is False
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_soil_interval_selector.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/soil_interval_selector.py`**

```python
"""soil_interval_selector.py — display-tier assignment for soil sample intervals.

Assigns each location/analyte/depth interval a display tier used by the
cartography pipeline:

  HOTSPOT  — result detected and exceeds screening level
  DETECT   — result detected, below screening level
  ND       — non-detect (qualifier-flagged or blank result)
  NO_DATA  — result_value absent, no qualifier supplied

Produces a filtered list of dicts (one per interval) with a ``display_tier``
column added; downstream steps write this to CSV for the figure builder.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

_ND_QUALIFIERS = frozenset({"ND", "U", "BDL"})


class IntervalTier:
    HOTSPOT = "HOTSPOT"
    DETECT = "DETECT"
    ND = "ND"
    NO_DATA = "NO_DATA"


@dataclass
class SoilInterval:
    location_id: str
    top_depth_ft: float
    bottom_depth_ft: float
    analyte_name: str
    result_value: Optional[float]
    is_detect: bool
    exceeds_screening: bool
    screening_level: Optional[float]
    units: str


def assign_tier(interval: SoilInterval) -> str:
    """Return the display tier string for a single SoilInterval.

    Priority order:
      1. result_value is None and not is_detect → NO_DATA
      2. exceeds_screening → HOTSPOT
      3. is_detect and not exceeds_screening → DETECT
      4. not is_detect → ND
    """
    if interval.result_value is None:
        return IntervalTier.NO_DATA
    if interval.exceeds_screening:
        return IntervalTier.HOTSPOT
    if interval.is_detect:
        return IntervalTier.DETECT
    return IntervalTier.ND


def select_intervals(
    intervals: list,
    *,
    analytes: Optional[list] = None,
    tiers: Optional[list] = None,
    max_depth_ft: Optional[float] = None,
    qa: Optional[QACollector] = None,
) -> list:
    """Filter intervals and assign display tiers.

    Args:
        intervals: List of SoilInterval objects.
        analytes:  If provided, only include these analyte names.
        tiers:     If provided, only include rows whose assigned tier is in this list.
        max_depth_ft: If provided, only include intervals with top_depth_ft <= max_depth_ft.
        qa:        Optional QACollector; a new one is created if not supplied.

    Returns:
        List of dicts — all SoilInterval fields plus ``display_tier``.
    """
    if qa is None:
        qa = QACollector()

    rows = []
    skipped = 0
    for iv in intervals:
        if analytes and iv.analyte_name not in analytes:
            continue
        if max_depth_ft is not None and iv.top_depth_ft > max_depth_ft:
            continue
        tier = assign_tier(iv)
        if tiers and tier not in tiers:
            continue
        row = asdict(iv)
        row["display_tier"] = tier
        rows.append(row)

    qa.add(QARecord(SEV_INFO, "select_intervals",
                    f"{len(rows)} interval(s) selected; "
                    f"filters — analytes={analytes}, tiers={tiers}, "
                    f"max_depth_ft={max_depth_ft}"))
    return rows


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_bool_flag(value: str) -> bool:
    """Parse Excel / CSV boolean representations."""
    return value.strip().lower() in {"true", "1", "yes"}


def load_soil_results_csv(path) -> list:
    """Read a soil results CSV and return a list of SoilInterval objects.

    Expected columns:
        LocationID, TopDepthFt, BottomDepthFt, AnalyteName,
        ResultValue, ResultQualifier, ReportedUnits,
        ScreeningLevel, ExceedsScreeningLevel
    """
    path = Path(path)
    intervals = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            qualifier = row.get("ResultQualifier", "").strip().upper()
            raw_value = row.get("ResultValue", "").strip()
            result_value = _parse_float(raw_value)
            # ND if qualifier in set OR result is blank with no numeric value
            is_detect = (
                qualifier not in _ND_QUALIFIERS
                and result_value is not None
            )
            exceeds_screening = _parse_bool_flag(
                row.get("ExceedsScreeningLevel", "False")
            )
            intervals.append(SoilInterval(
                location_id=row.get("LocationID", ""),
                top_depth_ft=_parse_float(row.get("TopDepthFt", "")) or 0.0,
                bottom_depth_ft=_parse_float(row.get("BottomDepthFt", "")) or 0.0,
                analyte_name=row.get("AnalyteName", ""),
                result_value=result_value,
                is_detect=is_detect,
                exceeds_screening=exceeds_screening,
                screening_level=_parse_float(row.get("ScreeningLevel", "")),
                units=row.get("ReportedUnits", ""),
            ))
    return intervals


def write_intervals_csv(rows: list, out_path: Path) -> None:
    """Write select_intervals output to CSV."""
    if not rows:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            fh.write("")
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_soil_interval_selector.py -v
```

Expected: all 13 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/soil_interval_selector.py \
        tests/envmon/test_soil_interval_selector.py
git commit -m "feat(envmon): soil_interval_selector — display-tier assignment for mapping CSV"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("select-soil-intervals")
@click.option("--results-csv", "results_csv", required=True,
              type=click.Path(exists=True),
              help="Soil results CSV (LocationID, TopDepthFt, BottomDepthFt, "
                   "AnalyteName, ResultValue, ResultQualifier, ReportedUnits, "
                   "ScreeningLevel, ExceedsScreeningLevel).")
@click.option("--out", required=True, type=click.Path(),
              help="Output CSV path for tiered intervals.")
@click.option("--analytes", default=None,
              help="Comma-separated analyte names to include (default: all).")
@click.option("--tiers", default=None,
              help="Comma-separated tiers to include: HOTSPOT,DETECT,ND,NO_DATA "
                   "(default: all).")
@click.option("--max-depth-ft", "max_depth_ft", type=float, default=None,
              help="Exclude intervals with top_depth_ft greater than this value.")
@click.option("--report", default=None, type=click.Path())
def select_soil_intervals_cmd(results_csv, out, analytes, tiers, max_depth_ft, report):
    """Assign display tiers to soil sample intervals and write mapping CSV (CLOUD)."""
    from autogis.core.envmon.soil_interval_selector import (
        load_soil_results_csv, select_intervals, write_intervals_csv,
    )
    from autogis.core.common.qa import QACollector

    analyte_list = [a.strip() for a in analytes.split(",")] if analytes else None
    tier_list = [t.strip().upper() for t in tiers.split(",")] if tiers else None

    qa = QACollector()
    intervals = load_soil_results_csv(results_csv)
    rows = select_intervals(
        intervals,
        analytes=analyte_list,
        tiers=tier_list,
        max_depth_ft=max_depth_ft,
        qa=qa,
    )
    write_intervals_csv(rows, Path(out))
    click.echo(f"Intervals selected: {len(rows)}  Output: {out}")
    _render_qa(qa, report, "error")
```

- [ ] **Step 2: Help test + commit**

```python
def test_select_soil_intervals_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "select-soil-intervals" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_soil_interval_selector.py
git commit -m "feat(cli): add select-soil-intervals command (CLOUD)"
```
