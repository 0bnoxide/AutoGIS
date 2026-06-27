# ProcessLevelLoop (Tool 8.1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans to
> implement task-by-task. Steps use checkbox (`- [ ]`) syntax. Locked design
> decisions live in **ADR-0026** — do not re-litigate them.

**Goal:** Add a headless `envmon process-level-loop` CLI command + core module
that processes single-loop differential (height-of-instrument) leveling notes,
computes adjusted elevations and misclosure, emits QA flags, and writes the
existing `LevelLoopRun` + adjusted `LevelLoopObservation` schema rows. Writing
`ElevationHistory` is **out of scope** (that is Tool 8.2).

**Architecture:** New pure-core module `autogis/core/envmon/level_loop.py` with
`process_level_loop(observations, *, run_id, site_id, survey_date, benchmark_id,
known_elevation, tolerance, qa) -> tuple[LevelLoopRun, list[LevelLoopObservation]]`.
A single new `click` command on the `envmon` group reads an observation CSV (via
the existing `read_records_csv` against `LevelLoopObservation`), calls the
function, writes the run + observation rows to two CSVs, and renders QA + exit
through the existing `_render_qa`. No arcpy, no openpyxl.

**Tech stack:** Python 3.14, `click`, stdlib `csv`/`dataclasses`/`datetime`/`math`,
`pytest`. Reuses: `LevelLoopRun`, `LevelLoopObservation` (`common/schema/survey.py`),
`read_records_csv` (`evaluate_rpd_qa.py`), `QACollector`/`SEV_*` (`common/qa.py`),
`_render_qa` (`cli.py`).

## Global constraints

- `core/` and `adapters/` import with neither `arcpy` nor `arcgis` present. This
  command is headless — never import arcpy, never call `_guard`.
- Lazy-import core modules inside the command body.
- Command name exactly `process-level-loop`. Tests via `python -m pytest -q`.
- Survey math is in feet; the tool is unit-agnostic but labels outputs `_ft`.

---

### Task 1: Core module `level_loop.py` + unit tests

**Files:**
- Create: `autogis/core/envmon/level_loop.py`
- Create: `tests/test_level_loop.py`

**Interfaces:**
- Consumes (do not modify): `LevelLoopRun`, `LevelLoopObservation`
  (`common/schema/survey.py`), `QACollector`, `SEV_INFO/SEV_WARNING/SEV_ERROR`.
- Produces: `process_level_loop(observations: list[LevelLoopObservation], *,
  run_id: str, site_id: str, survey_date: date, benchmark_id: str,
  known_elevation: float, tolerance: Optional[float], qa: QACollector)
  -> tuple[LevelLoopRun, list[LevelLoopObservation]]`.

**Locked behaviour (ADR-0026):**
- Input observations are ordered rows of a single loop. Each row has
  `setup_id, point_id, backsight, foresight, intermediate_sight` (any may be
  `None`). The benchmark row is the row whose `point_id == benchmark_id` carrying
  a backsight (the first instrument setup off the BM).
- Height-of-instrument rules:
  - Starting elevation of `benchmark_id` = `known_elevation`.
  - On a row with a **backsight** on a known-elevation point: `HI = elev + BS`.
  - On a row with a **foresight** (turning point or the closing BM):
    `elev(point) = HI - FS`; this point becomes the new known elevation and the
    next backsight (same `setup_id`+1 or same row carrying both) recomputes HI.
  - **Intermediate sights** read side-shots: `elev = HI - IS`, but do **not**
    advance HI and are not turning points.
  - A row may carry both a foresight (closing the prior setup) and a backsight
    (opening the next) — process foresight first, then backsight.
- Misclosure: after the loop returns a foresight onto `benchmark_id`,
  `misclosure_ft = observed_closing_elevation - known_elevation`.
- Adjustment (v1, equal-per-setup): correction per setup =
  `-misclosure / n_setups`; cumulative correction applied to each turning point's
  elevation by setup index. Side-shots inherit their setup's cumulative
  correction. Record `adjusted=True` on the run when adjustment applied.
- Default tolerance when `tolerance is None`: `0.05 * sqrt(n_setups)` ft; surface
  the formula + value as an INFO `closure_tolerance_default`.
- QA flags (category, severity):
  - `misclosure_exceeds_tolerance` ERROR when `abs(misclosure) > tolerance`.
  - `missing_backsight` / `missing_foresight` ERROR for a setup that needs one.
  - `benchmark_mismatch` ERROR if no closing foresight returns to `benchmark_id`.
  - `negative_reading` ERROR for any negative BS/FS/IS.
  - `unclosed_loop` WARNING if loop never closes on the BM (no closing shot).
  - `duplicate_turning_point` WARNING if a non-BM `point_id` is used as a turning
    point twice.
  - `level_loop_complete` INFO with n_setups, misclosure, adjusted flag.
- Returned `LevelLoopObservation` rows carry computed `hi` and adjusted
  `elevation`. Returned `LevelLoopRun` carries `misclosure_ft`,
  `closure_tolerance_ft`, `adjusted`.

- [ ] **Step 1: Write the failing test file** `tests/test_level_loop.py`.

```python
"""Unit tests for process_level_loop (Tool 8.1)."""
import math
from datetime import date

from autogis.core.common.qa import QACollector
from autogis.core.common.schema.survey import LevelLoopObservation, LevelLoopRun
from autogis.core.envmon.level_loop import process_level_loop


def _obs(setup, point, bs=None, fs=None, is_=None):
    return LevelLoopObservation(run_id="L1", setup_id=str(setup), point_id=point,
                                backsight=bs, foresight=fs, intermediate_sight=is_)


def test_perfect_closing_loop_zero_misclosure():
    # BM100.000; setup1 BS on BM, FS to TP1; setup2 BS on TP1, FS back to BM.
    obs = [
        _obs(1, "BM", bs=2.000),          # HI = 102.000
        _obs(1, "TP1", fs=3.000),         # TP1 = 99.000
        _obs(2, "TP1", bs=4.000),         # HI = 103.000
        _obs(2, "BM", fs=3.000),          # closing -> 100.000, misclosure 0
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.000, tolerance=0.05, qa=qa)
    assert isinstance(run, LevelLoopRun)
    assert run.misclosure_ft == 0.0
    tp1 = next(r for r in rows if r.point_id == "TP1" and r.backsight is None)
    assert tp1.elevation == 99.000
    assert run.adjusted in (False, True)
    assert not any(r.severity == "ERROR" for r in qa.records)


def test_misclosure_exceeds_tolerance_errors():
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=2.900),          # closes at 100.100 -> misclosure +0.100
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.000, tolerance=0.05, qa=qa)
    assert round(run.misclosure_ft, 3) == 0.100
    assert any(r.category == "misclosure_exceeds_tolerance"
               and r.severity == "ERROR" for r in qa.records)


def test_default_tolerance_is_sqrt_rule():
    obs = [
        _obs(1, "BM", bs=2.0), _obs(1, "TP1", fs=3.0),
        _obs(2, "TP1", bs=4.0), _obs(2, "BM", fs=3.0),
    ]
    qa = QACollector()
    run, _ = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=None, qa=qa)
    assert run.closure_tolerance_ft == 0.05 * math.sqrt(2)
    assert any(r.category == "closure_tolerance_default" for r in qa.records)


def test_negative_reading_errors():
    obs = [_obs(1, "BM", bs=-2.0), _obs(1, "BM", fs=2.0)]
    qa = QACollector()
    process_level_loop(obs, run_id="L1", site_id="S",
                       survey_date=date(2026, 4, 1), benchmark_id="BM",
                       known_elevation=100.0, tolerance=0.05, qa=qa)
    assert any(r.category == "negative_reading" for r in qa.records)


def test_unclosed_loop_warns():
    # never returns a foresight onto BM
    obs = [_obs(1, "BM", bs=2.0), _obs(1, "TP1", fs=3.0)]
    qa = QACollector()
    run, _ = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.05, qa=qa)
    assert any(r.category in ("unclosed_loop", "benchmark_mismatch")
               for r in qa.records)


def test_adjustment_distributes_equally_per_setup():
    # +0.100 misclosure over 2 setups -> -0.050 per setup cumulative
    obs = [
        _obs(1, "BM", bs=2.000),
        _obs(1, "TP1", fs=3.000),         # raw 99.000 -> adj -0.050 -> 98.950
        _obs(2, "TP1", bs=4.000),
        _obs(2, "BM", fs=2.900),
    ]
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id="L1", site_id="S", survey_date=date(2026, 4, 1),
        benchmark_id="BM", known_elevation=100.0, tolerance=0.5, qa=qa)
    assert run.adjusted is True
    tp1 = next(r for r in rows if r.point_id == "TP1" and r.foresight is not None)
    assert round(tp1.elevation, 3) == 98.950
```

- [ ] **Step 2: Run, verify fail** (`ImportError`).
  `python -m pytest tests/test_level_loop.py -q`

- [ ] **Step 3: Implement `autogis/core/envmon/level_loop.py`.**

Implement the locked HI rules and equal-per-setup adjustment. Skeleton:

```python
"""Single-loop differential (height-of-instrument) leveling (Tool 8.1).

Headless, arcpy-free. Computes adjusted elevations + misclosure and emits QA.
Does NOT write ElevationHistory (that is Tool 8.2). See ADR-0026.
"""
from __future__ import annotations

import math
from datetime import date
from typing import List, Optional, Tuple

from ..common.schema.survey import LevelLoopObservation, LevelLoopRun
from ..common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR


def process_level_loop(observations, *, run_id, site_id, survey_date,
                       benchmark_id, known_elevation, tolerance, qa):
    # 1. validate readings (negative -> ERROR), count setups
    # 2. forward pass: maintain HI + current known elevation; compute raw elev
    #    for each foresight turning point and each intermediate side-shot
    # 3. detect closing foresight onto benchmark_id -> observed closing elev
    #    (else benchmark_mismatch ERROR + unclosed_loop WARNING)
    # 4. misclosure = observed_closing - known_elevation
    # 5. tolerance default 0.05*sqrt(n_setups) when None (+INFO)
    # 6. if abs(misclosure) > tolerance -> ERROR; distribute -misclosure/n_setups
    #    cumulatively per setup -> adjusted elevations
    # 7. build LevelLoopRun + adjusted LevelLoopObservation rows; INFO complete
    ...
```

- [ ] **Step 4: Run unit tests, verify pass.**

---

### Task 2: Wire `envmon process-level-loop` CLI + CLI tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add one headless command.
- Create: `tests/test_cli_process_level_loop.py`

- [ ] **Step 1: Write failing CLI tests.** Write a `LevelLoopObservation` CSV
  (columns `run_id,setup_id,point_id,backsight,foresight,intermediate_sight`),
  invoke the command, assert exit 0, two output CSVs written (run + observations),
  and `--help` lists `--observations-csv`, `--run-id`, `--site-id`,
  `--survey-date`, `--benchmark-id`, `--known-elevation`, `--tolerance`,
  `--run-output`, `--observations-output`, `--report`, `--fail-on`.

```python
def test_help_lists_options():
    from click.testing import CliRunner
    from autogis.adapters.cli import autogis
    r = CliRunner().invoke(autogis, ["envmon", "process-level-loop", "--help"])
    assert r.exit_code == 0
    for opt in ("--observations-csv", "--known-elevation", "--benchmark-id",
                "--tolerance", "--run-output", "--observations-output"):
        assert opt in r.output
```

- [ ] **Step 2: Run, verify fail** (`No such command`).

- [ ] **Step 3: Add the command to `cli.py`.**

```python
@envmon.command("process-level-loop")
@click.option("--observations-csv", required=True, type=click.Path(exists=True),
              help="CSV of LevelLoopObservation rows (ordered).")
@click.option("--run-id", required=True)
@click.option("--site-id", required=True)
@click.option("--survey-date", required=True, help="ISO date YYYY-MM-DD.")
@click.option("--benchmark-id", required=True, help="point_id of the benchmark.")
@click.option("--known-elevation", required=True, type=float)
@click.option("--tolerance", default=None, type=float,
              help="Closure tolerance ft; default 0.05*sqrt(n_setups).")
@click.option("--run-output", required=True, type=click.Path(),
              help="Output LevelLoopRun CSV path.")
@click.option("--observations-output", required=True, type=click.Path(),
              help="Output adjusted-observations CSV path.")
@click.option("--report", default=None, type=click.Path())
@click.option("--fail-on", type=click.Choice(["error", "warning"]),
              default="error")
def process_level_loop_cmd(observations_csv, run_id, site_id, survey_date,
                           benchmark_id, known_elevation, tolerance, run_output,
                           observations_output, report, fail_on):
    """Tool 8.1: differential leveling — adjusted elevations + misclosure QA."""
    import csv as _csv
    from dataclasses import asdict, fields as _fields
    from datetime import date as _date
    from autogis.core.common.qa import QACollector
    from autogis.core.common.schema.survey import (
        LevelLoopObservation, LevelLoopRun)
    from autogis.core.envmon.evaluate_rpd_qa import read_records_csv
    from autogis.core.envmon.level_loop import process_level_loop

    obs = read_records_csv(Path(observations_csv), LevelLoopObservation)
    qa = QACollector()
    run, rows = process_level_loop(
        obs, run_id=run_id, site_id=site_id,
        survey_date=_date.fromisoformat(survey_date),
        benchmark_id=benchmark_id, known_elevation=known_elevation,
        tolerance=tolerance, qa=qa)

    def _dump(path, records, record_cls):
        cols = [f.name for f in _fields(record_cls)]
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=cols); w.writeheader()
            for rec in records:
                w.writerow(asdict(rec))
        return p

    _dump(run_output, [run], LevelLoopRun)
    _dump(observations_output, rows, LevelLoopObservation)
    click.echo(f"Misclosure: {run.misclosure_ft} ft  "
               f"Tolerance: {run.closure_tolerance_ft} ft  "
               f"Adjusted: {run.adjusted}")
    _render_qa(qa, report, fail_on)
```

Note: `LevelLoopObservation`/`LevelLoopRun` have `table_name` as a `ClassVar`;
`dataclasses.fields()` excludes ClassVars, so the CSV columns are the data fields
only. `read_records_csv` likewise ignores `table_name`.

- [ ] **Step 4: Run CLI tests, verify pass.**
- [ ] **Step 5: Full suite** `python -m pytest -q` — no regressions.
- [ ] **Step 6: Commit.**

```
feat(envmon): process-level-loop — differential leveling adjustment + QA (Tool 8.1)

Headless level_loop core (HI method, equal-per-setup adjustment, misclosure +
QA flags) + envmon process-level-loop CLI. Fills LevelLoopRun /
LevelLoopObservation schema. ElevationHistory write deferred to Tool 8.2.
Decisions locked in ADR-0026.
```

---

## Self-review

- HI rules, misclosure, equal-per-setup adjustment, default tolerance formula,
  QA flag set → ADR-0026; covered by Task 1 tests. ✓
- `ElevationHistory` not written here (8.2 boundary respected). ✓
- Reuses `read_records_csv` / `QACollector` / `_render_qa`; fills existing
  `survey.py` schema. ✓
- arcpy-free: stdlib + `math` + existing core imports only. ✓
- v1 limitation (equal-per-setup, not distance-weighted) documented in ADR-0026
  negative consequences. ✓
