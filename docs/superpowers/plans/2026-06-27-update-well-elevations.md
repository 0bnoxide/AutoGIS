# UpdateWellElevationsFromLevelLoop (Tool 8.2) — Implementation Plan

**Goal:** Add a headless `envmon update-well-elevations` CLI command + core module
that reads an approved `LevelLoopRun` + adjusted `LevelLoopObservation` CSV (from
Tool 8.1) and writes `ElevationHistory` records — one per turning/side-shot point
that corresponds to a known well LocationID. Elevation history is append-only; a
`--dry-run` flag previews without writing.

**Architecture:** New pure-core module `autogis/core/envmon/update_well_elevations.py`
with `build_elevation_history(run, observations, well_ids, *, approved_by, datum,
survey_method, qa) -> list[ElevationHistory]`. A single `click` command on the
`envmon` group reads the two CSVs (via `read_records_csv`), optionally reads a
well-ID list CSV, calls the function, writes `ElevationHistory` records to CSV, and
renders QA + exit via `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`datetime`, `pytest`.
Reuses: `LevelLoopRun`, `LevelLoopObservation`, `ElevationHistory` (`schema/survey.py`),
`read_records_csv` (`evaluate_rpd_qa.py`), `QACollector` (`common/qa.py`),
`_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import without arcpy. Headless — no `_guard`.
- Command name exactly `update-well-elevations`. Register as `Runtime.CLOUD`.
- `ElevationHistory.approved_for_use` = True (the flag gates Tool 8.2; if not
  approved, use Tool 8.1 and do not call 8.2). `superseded` = False (new record).
- This tool APPENDS records to the output CSV; it does not manage supersession.
  Supersession is a future tool (8.3). Document this limitation in the ADR log.

---

### Task 1: Core module `update_well_elevations.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/update_well_elevations.py`
- Create: `tests/test_update_well_elevations.py`

**Interfaces:**
- Consumes: `LevelLoopRun`, `LevelLoopObservation` (from Tool 8.1 output),
  `ElevationHistory` (output), `QACollector`, `SEV_INFO/SEV_WARNING/SEV_ERROR`.
- `build_elevation_history(run, observations, well_ids, *, approved_by, datum,
  survey_method, qa) -> list[ElevationHistory]`
  - `well_ids`: set of LocationIDs (from well list CSV or all unique point_ids if not
    provided). Points not in `well_ids` are skipped (emit INFO `non_well_point`).
  - Only observations with a non-None `elevation` are included.
  - The benchmark itself (`run.benchmark_id`) is skipped unless it appears in
    `well_ids` (it usually does not).
  - One `ElevationHistory` per point_id × run_id. If a point appears multiple times
    (e.g. a turning point and a side-shot), take the average elevation and emit a
    WARNING `multiple_readings`.

**Complete code:**

```python
"""Write ElevationHistory from an approved LevelLoopRun (Tool 8.2)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Set
from ..common.schema.survey import LevelLoopRun, LevelLoopObservation, ElevationHistory
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def build_elevation_history(
    run: LevelLoopRun,
    observations: List[LevelLoopObservation],
    well_ids: Optional[Set[str]],
    *,
    approved_by: str,
    datum: str,
    survey_method: str,
    qa: QACollector,
) -> List[ElevationHistory]:
    """Build ElevationHistory records from adjusted level-loop observations."""
    # Group by point_id, collect elevations.
    from collections import defaultdict
    elev_groups: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        if obs.elevation is None:
            continue
        if obs.point_id == run.benchmark_id and (
                well_ids is None or obs.point_id not in well_ids):
            continue
        if well_ids is not None and obs.point_id not in well_ids:
            qa.add(SEV_INFO, "non_well_point",
                   f"Point {obs.point_id!r} not in well list; skipped",
                   site_id=run.site_id)
            continue
        elev_groups[obs.point_id].append(obs.elevation)

    records: List[ElevationHistory] = []
    for pt_id, elevs in sorted(elev_groups.items()):
        if len(elevs) > 1:
            qa.add(SEV_WARNING, "multiple_readings",
                   f"Point {pt_id!r} has {len(elevs)} elevation readings; "
                   f"using mean",
                   site_id=run.site_id, location_id=pt_id)
        elev = sum(elevs) / len(elevs)
        records.append(ElevationHistory(
            location_id=pt_id,
            elevation_type="surveyed",
            elevation=elev,
            vertical_datum=datum,
            survey_date=run.survey_date,
            survey_method=survey_method,
            source_run_id=run.run_id,
            approved_for_use=True,
            superseded=False,
        ))

    qa.add(SEV_INFO, "elevation_history_built",
           f"Built {len(records)} ElevationHistory record(s) from run {run.run_id!r}",
           site_id=run.site_id)
    return records
```

**Test file `tests/test_update_well_elevations.py`:**

```python
"""Unit tests for update_well_elevations (Tool 8.2)."""
from datetime import date
from autogis.core.common.qa import QACollector
from autogis.core.common.schema.survey import (
    LevelLoopRun, LevelLoopObservation, ElevationHistory)
from autogis.core.envmon.update_well_elevations import build_elevation_history


def _run():
    return LevelLoopRun(run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
                        benchmark_id="BM", known_elevation=100.0)


def _obs(pt, elev):
    return LevelLoopObservation(run_id="L1", setup_id="1", point_id=pt,
                                elevation=elev)


def test_basic_elevation_history():
    run = _run()
    obs = [_obs("MW-1", 99.0), _obs("MW-2", 101.0), _obs("BM", 100.0)]
    qa = QACollector()
    recs = build_elevation_history(run, obs, {"MW-1", "MW-2"},
                                   approved_by="Surveyor",
                                   datum="NAVD88", survey_method="differential",
                                   qa=qa)
    assert len(recs) == 2
    ids = {r.location_id for r in recs}
    assert ids == {"MW-1", "MW-2"}
    assert all(r.approved_for_use for r in recs)
    assert all(not r.superseded for r in recs)


def test_non_well_point_skipped_with_info():
    run = _run()
    obs = [_obs("MW-1", 99.0), _obs("TP1", 98.0)]
    qa = QACollector()
    recs = build_elevation_history(run, obs, {"MW-1"},
                                   approved_by="x", datum="NAVD88",
                                   survey_method="differential", qa=qa)
    assert len(recs) == 1
    assert any(r.category == "non_well_point" for r in qa.records)


def test_multiple_readings_averaged_and_warns():
    run = _run()
    obs = [_obs("MW-1", 99.0), _obs("MW-1", 99.2)]
    qa = QACollector()
    recs = build_elevation_history(run, obs, None,
                                   approved_by="x", datum="NAVD88",
                                   survey_method="differential", qa=qa)
    assert abs(recs[0].elevation - 99.1) < 1e-9
    assert any(r.category == "multiple_readings" for r in qa.records)


def test_none_elevation_skipped():
    run = _run()
    obs = [_obs("MW-1", None), _obs("MW-2", 99.0)]
    qa = QACollector()
    recs = build_elevation_history(run, obs, None,
                                   approved_by="x", datum="NAVD88",
                                   survey_method="differential", qa=qa)
    # MW-1 has no elevation; BM is benchmark and no well_ids filter -> included
    # Actually with well_ids=None all non-None points are included except benchmark
    ids = {r.location_id for r in recs}
    assert "MW-1" not in ids
    assert "MW-2" in ids
```

**Steps:**
- [ ] Write test file, run `python -m pytest tests/test_update_well_elevations.py -q` — verify ImportError.
- [ ] Implement `update_well_elevations.py`.
- [ ] Run tests, verify pass.

---

### Task 2: Wire `envmon update-well-elevations` CLI + tests

**Files:**
- Modify: `autogis/adapters/cli.py`
- Modify: `autogis/runtime/capabilities.py` — add `"update-well-elevations": Runtime.CLOUD`
- Create: `tests/test_cli_update_well_elevations.py`

**Command:**

```python
@envmon.command("update-well-elevations")
@click.option("--run-csv", required=True, type=click.Path(exists=True))
@click.option("--observations-csv", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--approved-by", default="", help="Surveyor / operator name.")
@click.option("--datum", default="NAVD88")
@click.option("--survey-method", default="differential_leveling")
@click.option("--well-ids-csv", default=None, type=click.Path(exists=True),
              help="CSV of location_id column; default: all survey points.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Preview records without writing output CSV.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]), default="error")
def update_well_elevations_cmd(...):
    """Tool 8.2: write ElevationHistory from an approved level-loop run."""
    ...
```

**Steps:**
- [ ] Write failing CLI test, verify fail.
- [ ] Add command to `cli.py`, add to `capabilities.py`.
- [ ] Run CLI tests and full suite.
- [ ] Commit: `feat(envmon): update-well-elevations — write ElevationHistory from level-loop (Tool 8.2)`
