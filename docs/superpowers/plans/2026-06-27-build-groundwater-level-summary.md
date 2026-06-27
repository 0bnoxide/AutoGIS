# BuildGroundwaterLevelSummary (Tool 5.1) — Implementation Plan

**Goal:** Add a headless `envmon gw-level-summary` CLI command + core module that
reads `ElevationHistory` records (from Tool 8.2) and `LevelLoopRun` metadata, and
produces a groundwater level summary CSV: current water level elevation per well,
depth to water (DTW) from top-of-casing elevation (if provided), and trend vs the
previous approved survey. This is the headless precursor to the arcpy-based contour
tool (Tool 5).

**Architecture:** New pure-core module `autogis/core/envmon/gw_level_summary.py`
with `build_gw_level_summary(elevations, toc_elevations, *, event_date, qa)
-> list[GWLevelRow]`. A `click` command reads elevation CSV + optional TOC CSV,
calls the function, writes summary CSV, renders QA + exit. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`datetime`,
`pytest`. Reuses: `ElevationHistory` (`common/schema/survey.py`), `read_records_csv`
(`evaluate_rpd_qa.py`), `QACollector` (`common/qa.py`), `_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `gw-level-summary`. Register as `Runtime.CLOUD`.
- Only `approved_for_use=True` and `superseded=False` elevation records are used.
- If multiple approved non-superseded records exist for a well on the event date,
  take the latest (by `survey_date`); emit WARNING `multiple_approved_elevations`.
- DTW = TOC elevation − water level elevation. If TOC absent: DTW = None.
- Trend vs previous: compare current survey date to the most recent prior approved
  survey date per well. `RISING` if DTW decreased, `DECLINING` if DTW increased
  (water level dropped), `STABLE` if |Δ| < 0.1 ft, `INSUFFICIENT_DATA` if no prior.
- `--event-date` in `YYYY-MM-DD` format; only elevations with `survey_date ==
  event_date` are considered current. All prior dates are "historical".

---

### Task 1: Core module `gw_level_summary.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/gw_level_summary.py`
- Create: `tests/test_gw_level_summary.py`

**Complete code:**

```python
"""Groundwater level summary from ElevationHistory (Tool 5.1)."""
from __future__ import annotations
import dataclasses
from datetime import date
from typing import Dict, List, Optional
from ..common.schema.survey import ElevationHistory
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING

_STABLE_FT = 0.1


@dataclasses.dataclass
class GWLevelRow:
    location_id: str
    survey_date: date
    water_level_elevation: float
    toc_elevation: Optional[float]
    depth_to_water: Optional[float]
    trend: str
    vertical_datum: str


def build_gw_level_summary(
    elevations: List[ElevationHistory],
    toc_elevations: Dict[str, float],
    *,
    event_date: date,
    qa: QACollector,
) -> List[GWLevelRow]:
    """Compute per-well groundwater level summary for event_date."""
    # Filter to approved, non-superseded.
    active = [e for e in elevations if e.approved_for_use and not e.superseded]

    # Current event records.
    current: Dict[str, List[ElevationHistory]] = {}
    historical: Dict[str, List[ElevationHistory]] = {}
    for e in active:
        if e.survey_date == event_date:
            current.setdefault(e.location_id, []).append(e)
        elif e.survey_date < event_date:
            historical.setdefault(e.location_id, []).append(e)

    rows: List[GWLevelRow] = []
    for loc_id, recs in sorted(current.items()):
        if len(recs) > 1:
            qa.add(SEV_WARNING, "multiple_approved_elevations",
                   f"{loc_id}: {len(recs)} approved elevations for {event_date}; "
                   f"using latest survey_date",
                   location_id=loc_id)
        best = sorted(recs, key=lambda r: r.survey_date)[-1]

        toc = toc_elevations.get(loc_id)
        dtw = (toc - best.elevation) if toc is not None else None

        # Trend vs previous.
        hist = sorted(historical.get(loc_id, []), key=lambda r: r.survey_date)
        if not hist:
            trend = "INSUFFICIENT_DATA"
        else:
            prev = hist[-1]
            prev_toc = toc_elevations.get(loc_id)
            if prev_toc is not None and dtw is not None:
                prev_dtw = prev_toc - prev.elevation
                delta_dtw = dtw - prev_dtw
                if abs(delta_dtw) < _STABLE_FT:
                    trend = "STABLE"
                elif delta_dtw < 0:
                    trend = "RISING"   # DTW decreased → water rose
                else:
                    trend = "DECLINING"
            else:
                # No TOC: compare elevation directly.
                delta_elev = best.elevation - prev.elevation
                if abs(delta_elev) < _STABLE_FT:
                    trend = "STABLE"
                elif delta_elev > 0:
                    trend = "RISING"
                else:
                    trend = "DECLINING"

        rows.append(GWLevelRow(
            location_id=loc_id,
            survey_date=event_date,
            water_level_elevation=best.elevation,
            toc_elevation=toc,
            depth_to_water=dtw,
            trend=trend,
            vertical_datum=best.vertical_datum,
        ))

    qa.add(SEV_INFO, "gw_level_summary_complete",
           f"build_gw_level_summary: {len(rows)} well(s) summarised for {event_date}")
    return rows
```

**Test file `tests/test_gw_level_summary.py`:**

```python
"""Unit tests for gw_level_summary (Tool 5.1)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.common.schema.survey import ElevationHistory
from autogis.core.envmon.gw_level_summary import build_gw_level_summary

D1, D2 = date(2026, 1, 1), date(2026, 4, 1)

def _elev(loc, elev, survey_date, approved=True, superseded=False):
    return ElevationHistory(
        location_id=loc, elevation_type="surveyed", elevation=elev,
        vertical_datum="NAVD88", survey_date=survey_date,
        survey_method="differential", source_run_id="L1",
        approved_for_use=approved, superseded=superseded)

def test_basic_summary():
    elevs = [_elev("MW-1", 100.0, D2), _elev("MW-1", 100.5, D1)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {"MW-1": 105.0}, event_date=D2, qa=qa)
    assert len(rows) == 1
    r = rows[0]
    assert r.depth_to_water == pytest.approx(5.0)
    assert r.trend == "DECLINING"  # DTW increased (water dropped)

def test_no_toc_no_dtw():
    elevs = [_elev("MW-1", 100.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert rows[0].depth_to_water is None

def test_superseded_excluded():
    elevs = [_elev("MW-1", 99.0, D2, superseded=True)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert len(rows) == 0

def test_multiple_approved_warns():
    elevs = [_elev("MW-1", 100.0, D2), _elev("MW-1", 100.1, D2)]
    qa = QACollector()
    build_gw_level_summary(elevs, {}, event_date=D2, qa=qa)
    assert any(r.category == "multiple_approved_elevations" for r in qa.records)

import pytest
def test_rising_trend():
    elevs = [_elev("MW-1", 99.0, D1), _elev("MW-1", 100.0, D2)]
    qa = QACollector()
    rows = build_gw_level_summary(elevs, {"MW-1": 105.0}, event_date=D2, qa=qa)
    assert rows[0].trend == "RISING"  # water level rose (DTW decreased)
```

**Steps:**
- [ ] Write test file, verify ImportError.
- [ ] Implement `gw_level_summary.py`.
- [ ] Run unit tests, verify pass.

---

### Task 2: Wire CLI + register

```python
@envmon.command("gw-level-summary")
@click.option("--elevations-csv", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--event-date", required=True, help="YYYY-MM-DD survey date.")
@click.option("--toc-csv", default=None, type=click.Path(exists=True),
              help="CSV with location_id,toc_elevation columns.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def gw_level_summary_cmd(elevations_csv, output, event_date, toc_csv,
                         report, fail_on):
    """Tool 5.1: compute per-well GW level summary from elevation history."""
    ...
```

`capabilities.py`: `"gw-level-summary": Runtime.CLOUD`

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command, update capabilities.
- [ ] Full suite, commit: `feat(envmon): gw-level-summary — per-well GW level from elevation history (Tool 5.1)`
