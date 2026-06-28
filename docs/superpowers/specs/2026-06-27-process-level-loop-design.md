# ProcessLevelLoop Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** ProcessLevelLoop (Phase 4.1a / Tool 8.1)
**Priority:** HIGH (well elevation accuracy is a prerequisite for GWE calculations and groundwater maps)

---

## Problem

Differential leveling is the standard method for establishing and confirming well
casing elevations (top-of-casing, TOC) relative to an established benchmark. Field
crews record backsight/foresight rod readings at each instrument setup; the data is
currently processed manually in Excel, which provides no audit trail, no formal
misclosure check, no proportional adjustment, and no link to the GDB elevation history.

`ElevationHistory` was added to TABLE_SCHEMAS in Phase 1.4. This tool populates it.

---

## Approach

**Chosen:** Pure Python computation tier (arcpy-free, fully testable) + LOCAL arcpy
write tier for `ElevationHistory` and `LevelLoopRuns`/`LevelLoopObservations`. Input
is a CSV or XLSX of rod readings in a structured format; output is an `LevelLoopResult`
with per-point adjusted elevations, a misclosure report, and an approval flag.

The computation follows standard differential leveling:
- `HI = Backsight + Elevation_at_setup`
- `Elevation_at_next = HI - Foresight`
- Misclosure = (computed closing elevation) − (known benchmark elevation)
- Adjustment: proportional Bowditch (distance-weighted if traverse lengths given,
  equal otherwise)

**Rejected: Shapefile/GIS input.** Level loop data is tabular; no geometry is needed
at computation time. Geometry is written to `SurveyPoints_QA` separately.

**Rejected: Direct Excel computation (openpyxl only).** The computation must be
unit-tested independently of the file format. Separate computation from I/O.

---

## Architecture

```
autogis/
  core/envmon/
    process_level_loop.py   ← NEW
  adapters/
    cli.py                  ← add process-level-loop command (LOCAL)
tests/envmon/
  test_process_level_loop.py ← NEW, arcpy-free (computation + format tests)
```

---

## Public API (`process_level_loop.py`)

```python
@dataclass
class LevelObservation:
    setup_id: str
    point_id: str
    backsight_ft: Optional[float]        # None if this point is a foresight-only
    foresight_ft: Optional[float]        # None if this point is a backsight-only
    intermediate_ft: Optional[float]     # optional IS reading; no height-of-inst change
    is_benchmark: bool = False

@dataclass
class LevelLoopResult:
    run_id: str                    # UUID generated at call time
    benchmark_id: str
    known_elevation_ft: float
    raw_closing_elevation_ft: float
    misclosure_ft: float           # raw_closing - known
    closure_tolerance_ft: float
    within_tolerance: bool
    adjusted: bool                 # True if adjustment applied
    point_elevations: dict[str, float]    # point_id → adjusted elevation
    observations: list[LevelObservation]

def compute_level_loop(
    observations: list[LevelObservation],
    benchmark_id: str,
    known_elevation_ft: float,
    closure_tolerance_ft: float = 0.02,
) -> LevelLoopResult:
    """
    Pure-Python differential leveling computation.
    
    Runs the loop, computes elevations, checks misclosure.
    Applies equal-interval Bowditch adjustment if within tolerance.
    Returns result with adjusted=False and unmodified elevations if
    misclosure exceeds tolerance (does not raise).
    """

def format_loop_report(result: LevelLoopResult) -> str:
    """Human-readable report: setup table, misclosure, per-point elevations."""

def load_level_loop_csv(path: Path) -> list[LevelObservation]:
    """
    Parse a level loop CSV.
    Required columns: SetupID, PointID, Backsight_ft, Foresight_ft
    Optional: IntermediateSight_ft, IsBenchmark
    """

def write_level_loop_results(   # pragma: no cover
    gdb_path: str,
    site_id: str,
    result: LevelLoopResult,
) -> None:
    """Write LevelLoopRuns, LevelLoopObservations, and ElevationHistory rows."""
```

---

## Computation Logic (Bowditch Equal Adjustment)

```python
# Phase 1: propagate HI and foresight elevations forward
hi = known_elevation_ft  # first setup starts at benchmark
for obs in observations:
    if obs.backsight_ft is not None:
        hi = elevation_at_setup + obs.backsight_ft
    if obs.foresight_ft is not None:
        elevation_at_next = hi - obs.foresight_ft
        elevations[obs.point_id] = elevation_at_next
        elevation_at_setup = elevation_at_next

# Phase 2: misclosure
misclosure = elevations[benchmark_id] - known_elevation_ft  # should be 0

# Phase 3: adjustment (equal-interval Bowditch)
n = len([o for o in observations if o.foresight_ft is not None])
correction_per_setup = -misclosure / n
cumulative = 0.0
for i, obs in enumerate(setup_sequence):
    if obs.foresight_ft is not None:
        cumulative += correction_per_setup
        elevations[obs.point_id] += cumulative
```

---

## Level Loop CSV Format

```csv
SetupID,PointID,Backsight_ft,Foresight_ft,IntermediateSight_ft,IsBenchmark
S1,BM-001,0.756,,, True
S1,MW-01,,4.532,,False
S2,MW-01,3.941,,,False
S2,MW-02,,5.203,,False
...
S_close,BM-001,,1.102,,True
```

---

## CLI Command

```python
@envmon.command("process-level-loop")
@click.argument("csv", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--benchmark", "benchmark_id", required=True)
@click.option("--benchmark-elev", "benchmark_elev_ft", type=float, required=True)
@click.option("--tolerance", "closure_tolerance_ft", type=float, default=0.02)
@click.option("--gdb", default=None, type=click.Path(),
              help="Write results to GDB (ArcGIS Pro only).")
@click.option("--report", default=None, type=click.Path())
def process_level_loop_cmd(csv, site_id, benchmark_id, benchmark_elev_ft,
                           closure_tolerance_ft, gdb, report):
    """Process a differential level loop and adjust well elevations (headless compute)."""
    from autogis.core.envmon.process_level_loop import (
        load_level_loop_csv, compute_level_loop, format_loop_report,
        write_level_loop_results,
    )
    observations = load_level_loop_csv(Path(csv))
    result = compute_level_loop(observations, benchmark_id, benchmark_elev_ft,
                                closure_tolerance_ft)
    text = format_loop_report(result)
    click.echo(text)
    if report:
        Path(report).write_text(text, encoding="utf-8")
    if gdb:
        _guard("process-level-loop")
        write_level_loop_results(gdb, site_id, result)
```

Note: `--gdb` makes this a LOCAL operation; without it, the command runs headless
(compute only, no GDB write). The `_guard()` call is inside the `if gdb:` block.

---

## Test Strategy

`tests/envmon/test_process_level_loop.py` — all arcpy-free:

1. Trivial two-setup loop with known answer: compute result matches hand-calculated elevations
2. `within_tolerance=True` when misclosure <= tolerance
3. `within_tolerance=False` when misclosure > tolerance; `adjusted=False`
4. Bowditch adjustment sums to zero (adjusted elevations close back to benchmark)
5. `format_loop_report()` contains misclosure value and per-point elevations
6. `format_loop_report()` shows `[PASS]` / `[FAIL]` tolerance status
7. `load_level_loop_csv()` parses minimal CSV into correct `LevelObservation` list
8. `load_level_loop_csv()` handles optional `IsBenchmark` column missing (defaults False)
