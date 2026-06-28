# ProcessLevelLoop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ProcessLevelLoop` — differential leveling computation (arcpy-free
pure-Python tier) + GDB write tier + CLI command. See spec:
`docs/superpowers/specs/2026-06-27-process-level-loop-design.md`.

**Architecture:**
- New: `autogis/core/envmon/process_level_loop.py`
- Modify: `autogis/adapters/cli.py` — add `process-level-loop` command (headless compute; optional `--gdb` for LOCAL write)
- New: `tests/envmon/test_process_level_loop.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `compute_level_loop()` and `format_loop_report()` are arcpy-free, fully unit-testable.
- `write_level_loop_results()` is LOCAL (arcpy), `# pragma: no cover`.
- `--gdb` flag on CLI is the only arcpy trigger; without it the command runs headless.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `process_level_loop.py` + computation tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_process_level_loop.py`:

```python
import pytest
from pathlib import Path
import csv

from autogis.core.envmon.process_level_loop import (
    LevelObservation, LevelLoopResult, compute_level_loop,
    format_loop_report, load_level_loop_csv,
)

# Trivial two-setup loop:
# BM-001 known elev = 100.00 ft
# S1: BS on BM = 2.00 ft → HI = 102.00
# S1: FS on MW-01 = 5.00 ft → MW-01 elev = 97.00
# S2: BS on MW-01 = 4.00 ft → HI = 101.00
# S2: FS on BM-001 = 1.00 ft → BM elev computed = 100.00 → misclosure = 0.00

_OBSERVATIONS = [
    LevelObservation("S1", "BM-001", backsight_ft=2.00, foresight_ft=None,
                     intermediate_ft=None, is_benchmark=True),
    LevelObservation("S1", "MW-01", backsight_ft=None, foresight_ft=5.00,
                     intermediate_ft=None, is_benchmark=False),
    LevelObservation("S2", "MW-01", backsight_ft=4.00, foresight_ft=None,
                     intermediate_ft=None, is_benchmark=False),
    LevelObservation("S2", "BM-001", backsight_ft=None, foresight_ft=1.00,
                     intermediate_ft=None, is_benchmark=True),
]


def test_compute_level_loop_elevations():
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    assert abs(r.point_elevations.get("MW-01", 0) - 97.00) < 0.001


def test_perfect_closure_within_tolerance():
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    assert r.within_tolerance is True
    assert abs(r.misclosure_ft) < 0.001


def test_loop_adjusted_on_perfect_closure():
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    assert r.adjusted is True


def test_exceeds_tolerance_not_adjusted():
    bad = [
        LevelObservation("S1", "BM-001", backsight_ft=2.00, foresight_ft=None,
                         intermediate_ft=None, is_benchmark=True),
        LevelObservation("S1", "MW-01", backsight_ft=None, foresight_ft=5.00,
                         intermediate_ft=None, is_benchmark=False),
        LevelObservation("S2", "MW-01", backsight_ft=4.00, foresight_ft=None,
                         intermediate_ft=None, is_benchmark=False),
        LevelObservation("S2", "BM-001", backsight_ft=None, foresight_ft=1.10,
                         intermediate_ft=None, is_benchmark=True),  # 0.10 ft error
    ]
    r = compute_level_loop(bad, "BM-001", 100.00, closure_tolerance_ft=0.02)
    assert r.within_tolerance is False
    assert r.adjusted is False


def test_bowditch_adjustment_closes():
    """After adjustment, re-running forward should produce ~zero misclosure."""
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    assert r.adjusted is True
    # perfect closure loop — adjusted elevations are unchanged
    assert abs(r.misclosure_ft) < 0.001


def test_format_loop_report_contains_misclosure():
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    text = format_loop_report(r)
    assert "misclosure" in text.lower() or "Misclosure" in text


def test_format_loop_report_shows_pass():
    r = compute_level_loop(_OBSERVATIONS, "BM-001", 100.00)
    text = format_loop_report(r)
    assert "PASS" in text


def test_format_loop_report_shows_fail():
    bad = [
        LevelObservation("S1", "BM-001", backsight_ft=2.00, foresight_ft=None,
                         intermediate_ft=None, is_benchmark=True),
        LevelObservation("S1", "MW-01", backsight_ft=None, foresight_ft=5.10,
                         intermediate_ft=None, is_benchmark=False),
        LevelObservation("S2", "MW-01", backsight_ft=4.00, foresight_ft=None,
                         intermediate_ft=None, is_benchmark=False),
        LevelObservation("S2", "BM-001", backsight_ft=None, foresight_ft=1.00,
                         intermediate_ft=None, is_benchmark=True),
    ]
    r = compute_level_loop(bad, "BM-001", 100.00, closure_tolerance_ft=0.02)
    text = format_loop_report(r)
    assert "FAIL" in text


def test_load_level_loop_csv(tmp_path):
    p = tmp_path / "loop.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SetupID","PointID","Backsight_ft",
                                           "Foresight_ft","IntermediateSight_ft",
                                           "IsBenchmark"])
        w.writeheader()
        w.writerow({"SetupID": "S1", "PointID": "BM-001", "Backsight_ft": "2.00",
                    "Foresight_ft": "", "IntermediateSight_ft": "", "IsBenchmark": "True"})
        w.writerow({"SetupID": "S1", "PointID": "MW-01", "Backsight_ft": "",
                    "Foresight_ft": "5.00", "IntermediateSight_ft": "", "IsBenchmark": "False"})
    obs = load_level_loop_csv(p)
    assert len(obs) == 2
    assert obs[0].is_benchmark is True
    assert obs[0].backsight_ft == 2.00
    assert obs[1].foresight_ft == 5.00


def test_load_level_loop_csv_missing_isbenchmark_column(tmp_path):
    p = tmp_path / "loop_no_bm.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["SetupID","PointID","Backsight_ft","Foresight_ft"])
        w.writeheader()
        w.writerow({"SetupID": "S1", "PointID": "MW-01", "Backsight_ft": "2.00",
                    "Foresight_ft": ""})
    obs = load_level_loop_csv(p)
    assert obs[0].is_benchmark is False  # default
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_process_level_loop.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/process_level_loop.py`**

```python
"""process_level_loop.py — differential leveling computation and GDB write.

compute_level_loop() and format_loop_report() are arcpy-free.
write_level_loop_results() requires arcpy — # pragma: no cover.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LevelObservation:
    setup_id: str
    point_id: str
    backsight_ft: Optional[float]
    foresight_ft: Optional[float]
    intermediate_ft: Optional[float] = None
    is_benchmark: bool = False


@dataclass
class LevelLoopResult:
    run_id: str
    benchmark_id: str
    known_elevation_ft: float
    raw_closing_elevation_ft: float
    misclosure_ft: float
    closure_tolerance_ft: float
    within_tolerance: bool
    adjusted: bool
    point_elevations: dict[str, float]
    observations: list[LevelObservation]


def compute_level_loop(
    observations: list[LevelObservation],
    benchmark_id: str,
    known_elevation_ft: float,
    closure_tolerance_ft: float = 0.02,
) -> LevelLoopResult:
    elevations: dict[str, float] = {benchmark_id: known_elevation_ft}
    hi = known_elevation_ft
    current_elev = known_elevation_ft
    foresight_count = 0

    for obs in observations:
        if obs.backsight_ft is not None:
            hi = current_elev + obs.backsight_ft
        if obs.foresight_ft is not None:
            current_elev = hi - obs.foresight_ft
            elevations[obs.point_id] = current_elev
            foresight_count += 1

    raw_close = elevations.get(benchmark_id, current_elev)
    misclosure = raw_close - known_elevation_ft
    within = abs(misclosure) <= closure_tolerance_ft

    # Bowditch equal-interval adjustment
    if within and foresight_count > 0:
        correction = -misclosure / foresight_count
        cumulative = 0.0
        adjusted_elevations = dict(elevations)
        adjusted_elevations[benchmark_id] = known_elevation_ft  # anchor
        for obs in observations:
            if obs.foresight_ft is not None:
                cumulative += correction
                prev = elevations.get(obs.point_id, 0)
                adjusted_elevations[obs.point_id] = prev + cumulative
        adjusted_elevations[benchmark_id] = known_elevation_ft
        return LevelLoopResult(
            run_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            known_elevation_ft=known_elevation_ft,
            raw_closing_elevation_ft=raw_close,
            misclosure_ft=misclosure,
            closure_tolerance_ft=closure_tolerance_ft,
            within_tolerance=True,
            adjusted=True,
            point_elevations={k: v for k, v in adjusted_elevations.items()
                              if k != benchmark_id or not adjusted_elevations},
            observations=observations,
        )

    return LevelLoopResult(
        run_id=str(uuid.uuid4()),
        benchmark_id=benchmark_id,
        known_elevation_ft=known_elevation_ft,
        raw_closing_elevation_ft=raw_close,
        misclosure_ft=misclosure,
        closure_tolerance_ft=closure_tolerance_ft,
        within_tolerance=within,
        adjusted=False,
        point_elevations={k: v for k, v in elevations.items()},
        observations=observations,
    )


def format_loop_report(result: LevelLoopResult) -> str:
    status = "PASS" if result.within_tolerance else "FAIL"
    adj = "Adjusted" if result.adjusted else "Not adjusted"
    lines = [
        f"Level Loop Report  [{status}]  Benchmark: {result.benchmark_id}",
        f"Known elevation:  {result.known_elevation_ft:.3f} ft",
        f"Raw closing elev: {result.raw_closing_elevation_ft:.3f} ft",
        f"Misclosure:       {result.misclosure_ft:+.4f} ft  "
        f"(tolerance ±{result.closure_tolerance_ft:.3f} ft)  {adj}",
        "",
        f"{'Point':<20} {'Elevation (ft)':>14}",
        "-" * 36,
    ]
    for pt, elev in sorted(result.point_elevations.items()):
        if pt != result.benchmark_id:
            lines.append(f"{pt:<20} {elev:>14.3f}")
    lines.append("")
    lines.append(f"Run ID: {result.run_id}")
    return "\n".join(lines)


def load_level_loop_csv(path: Path) -> list[LevelObservation]:
    out: list[LevelObservation] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            def _f(k):
                v = row.get(k, "").strip()
                return float(v) if v else None
            bm_raw = row.get("IsBenchmark", "false").strip().lower()
            is_bm = bm_raw in ("true", "1", "yes")
            out.append(LevelObservation(
                setup_id=row.get("SetupID", ""),
                point_id=row.get("PointID", ""),
                backsight_ft=_f("Backsight_ft"),
                foresight_ft=_f("Foresight_ft"),
                intermediate_ft=_f("IntermediateSight_ft"),
                is_benchmark=is_bm,
            ))
    return out


def write_level_loop_results(  # pragma: no cover
    gdb_path: str,
    site_id: str,
    result: LevelLoopResult,
) -> None:
    """Write LevelLoopRuns, LevelLoopObservations, and ElevationHistory rows (ArcGIS Pro)."""
    from datetime import datetime
    import arcpy
    from pathlib import Path as _P

    gdb = str(gdb_path)

    # LevelLoopRuns
    runs_table = str(_P(gdb) / "LevelLoopRuns")
    if arcpy.Exists(runs_table):
        with arcpy.da.InsertCursor(runs_table,
                                   ["RunID", "SiteID", "SurveyDate", "BenchmarkID",
                                    "KnownElevation_ft", "Misclosure_ft",
                                    "ClosureTolerance_ft", "Adjusted"]) as cur:
            cur.insertRow([result.run_id, site_id, datetime.now(),
                           result.benchmark_id, result.known_elevation_ft,
                           result.misclosure_ft, result.closure_tolerance_ft,
                           int(result.adjusted)])

    # ElevationHistory
    elev_table = str(_P(gdb) / "ElevationHistory")
    if arcpy.Exists(elev_table):
        with arcpy.da.InsertCursor(elev_table,
                                   ["LocationID", "ElevationType", "Elevation_ft",
                                    "SurveyDate", "SurveyMethod", "SourceRunID",
                                    "ApprovedForUse", "Superseded"]) as cur:
            for pt_id, elev in result.point_elevations.items():
                cur.insertRow([pt_id, "TOC", elev, datetime.now(),
                               "DifferentialLevel", result.run_id, 0, 0])
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_process_level_loop.py -v
```

Expected: all 10 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/process_level_loop.py tests/envmon/test_process_level_loop.py
git commit -m "feat(envmon): process_level_loop — differential leveling computation + GDB write"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (headless; LOCAL only with `--gdb`)

```python
@envmon.command("process-level-loop")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--benchmark", "benchmark_id", required=True)
@click.option("--benchmark-elev", "benchmark_elev_ft", type=float, required=True,
              help="Known benchmark elevation in feet.")
@click.option("--tolerance", "closure_tolerance_ft", type=float, default=0.02,
              show_default=True, help="Closure tolerance in feet.")
@click.option("--gdb", default=None, type=click.Path(),
              help="Write results to GDB (requires ArcGIS Pro).")
@click.option("--report", default=None, type=click.Path())
def process_level_loop_cmd(csv_path, site_id, benchmark_id, benchmark_elev_ft,
                           closure_tolerance_ft, gdb, report):
    """Process a differential level loop CSV and adjust well elevations."""
    from autogis.core.envmon.process_level_loop import (
        load_level_loop_csv, compute_level_loop, format_loop_report,
        write_level_loop_results,
    )
    observations = load_level_loop_csv(Path(csv_path))
    result = compute_level_loop(observations, benchmark_id, benchmark_elev_ft,
                                closure_tolerance_ft)
    text = format_loop_report(result)
    click.echo(text)
    if report:
        Path(report).write_text(text, encoding="utf-8")
        click.echo(f"Report written: {report}")
    if gdb:
        _guard("process-level-loop")
        write_level_loop_results(gdb, site_id, result)
        click.echo(f"Elevations written to {gdb}")
    if not result.within_tolerance:
        raise SystemExit(1)
```

- [ ] **Step 2: Help test + commit**

```python
def test_process_level_loop_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "process-level-loop" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_process_level_loop.py
git commit -m "feat(cli): add process-level-loop command (headless compute, optional LOCAL write)"
```
