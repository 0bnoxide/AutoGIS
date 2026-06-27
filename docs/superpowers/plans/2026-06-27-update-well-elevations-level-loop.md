# UpdateWellElevationsFromLevelLoop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `UpdateWellElevationsFromLevelLoop` — push adjusted elevations from a
`LevelLoopResult` (produced by `ProcessLevelLoop`) into the `MonitoringWells` feature
class `TOCElevation_ft` field, with an approval/supersede audit trail via `ElevationHistory`.

**Architecture:**
- Modify: `autogis/core/envmon/process_level_loop.py` — add `update_well_elevations()` function
- Modify: `autogis/adapters/cli.py` — add `update-well-elevations` command (LOCAL)
- Modify: `tests/envmon/test_process_level_loop.py` — add approval workflow tests

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- All new computation is arcpy-free (approval logic, elevation selection).
- `update_well_elevations()` is LOCAL (arcpy), `# pragma: no cover`.
- Depends on `ProcessLevelLoop` (Phase 4.1a plan — `process_level_loop.py` must exist).
- Run tests with `python -m pytest -q`.

---

### Task 1: Approval logic (pure Python) + tests

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_process_level_loop.py`:

```python
from autogis.core.envmon.process_level_loop import (
    select_elevations_for_update, ElevationUpdatePlan,
)


_RESULT = LevelLoopResult(
    run_id="test-run-001",
    benchmark_id="BM-001",
    known_elevation_ft=100.00,
    raw_closing_elevation_ft=100.00,
    misclosure_ft=0.0,
    closure_tolerance_ft=0.02,
    within_tolerance=True,
    adjusted=True,
    point_elevations={"MW-01": 97.23, "MW-02": 94.10, "BM-001": 100.00},
    observations=[],
)

_WELL_IDS = {"MW-01", "MW-02"}   # known GIS wells


def test_select_elevations_returns_plan():
    plan = select_elevations_for_update(_RESULT, _WELL_IDS)
    assert isinstance(plan, ElevationUpdatePlan)


def test_select_elevations_excludes_benchmark():
    plan = select_elevations_for_update(_RESULT, _WELL_IDS)
    assert "BM-001" not in plan.updates


def test_select_elevations_only_known_wells():
    plan = select_elevations_for_update(_RESULT, _WELL_IDS)
    assert set(plan.updates.keys()) == {"MW-01", "MW-02"}


def test_select_elevations_skipped_when_not_in_well_list():
    plan = select_elevations_for_update(_RESULT, {"MW-01"})  # MW-02 not in GIS
    assert "MW-02" not in plan.updates
    assert "MW-02" in plan.skipped


def test_plan_not_created_when_not_within_tolerance():
    bad_result = LevelLoopResult(
        run_id="bad", benchmark_id="BM-001", known_elevation_ft=100.0,
        raw_closing_elevation_ft=100.10, misclosure_ft=0.10,
        closure_tolerance_ft=0.02, within_tolerance=False, adjusted=False,
        point_elevations={"MW-01": 97.0}, observations=[])
    plan = select_elevations_for_update(bad_result, _WELL_IDS)
    assert plan.blocked is True
    assert plan.block_reason == "misclosure_exceeds_tolerance"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_process_level_loop.py -k "elevation_update or plan" -v
```

- [ ] **Step 3: Add to `process_level_loop.py`**

```python
from dataclasses import dataclass, field as dc_field

@dataclass
class ElevationUpdatePlan:
    run_id: str
    updates: dict[str, float]   # point_id → elevation_ft
    skipped: list[str]          # points in result but not in well_ids
    blocked: bool = False
    block_reason: str = ""


def select_elevations_for_update(
    result: LevelLoopResult,
    well_ids: set[str],
) -> ElevationUpdatePlan:
    if not result.within_tolerance:
        return ElevationUpdatePlan(
            run_id=result.run_id, updates={}, skipped=[],
            blocked=True, block_reason="misclosure_exceeds_tolerance")
    updates: dict[str, float] = {}
    skipped: list[str] = []
    for pt_id, elev in result.point_elevations.items():
        if pt_id == result.benchmark_id:
            continue
        if pt_id in well_ids:
            updates[pt_id] = elev
        else:
            skipped.append(pt_id)
    return ElevationUpdatePlan(run_id=result.run_id, updates=updates, skipped=skipped)


def update_well_elevations(    # pragma: no cover
    gdb_path: str,
    site_id: str,
    plan: ElevationUpdatePlan,
) -> int:
    """Update TOCElevation_ft in MonitoringWells and write ElevationHistory rows."""
    if plan.blocked:
        raise ValueError(f"Plan blocked: {plan.block_reason}")
    import arcpy
    from datetime import datetime
    from pathlib import Path as _P
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)
    wells_fc = str(_P(gdb) / "MonitoringWells")
    elev_table = str(_P(gdb) / "ElevationHistory")
    updated = 0

    for loc_id, elev in plan.updates.items():
        where = f"SiteID='{site_id}' AND LocationID='{loc_id}'"
        with _ax.da.UpdateCursor(wells_fc, ["TOCElevation_ft"], where) as cur:
            for row in cur:
                cur.updateRow([elev])
                updated += 1
        if _ax.Exists(elev_table):
            with _ax.da.InsertCursor(elev_table,
                                     ["LocationID", "ElevationType", "Elevation_ft",
                                      "SurveyDate", "SurveyMethod", "SourceRunID",
                                      "ApprovedForUse", "Superseded"]) as cur:
                cur.insertRow([loc_id, "TOC", elev, datetime.now(),
                               "DifferentialLevel", plan.run_id, 0, 0])
    return updated
```

- [ ] **Step 4: Run tests + full suite + commit**

```bash
git add autogis/core/envmon/process_level_loop.py tests/envmon/test_process_level_loop.py
git commit -m "feat(envmon): process_level_loop — ElevationUpdatePlan + update_well_elevations"
```

---

### Task 2: CLI command `update-well-elevations`

- [ ] **Step 1: Add to `cli.py`** (LOCAL)

```python
@envmon.command("update-well-elevations")
@click.argument("csv_path", metavar="CSV", type=click.Path(exists=True))
@click.option("--site", "site_id", required=True)
@click.option("--benchmark", "benchmark_id", required=True)
@click.option("--benchmark-elev", "benchmark_elev_ft", type=float, required=True)
@click.option("--gdb", required=True, type=click.Path())
@click.option("--tolerance", "closure_tolerance_ft", type=float, default=0.02)
@click.option("--dry-run", is_flag=True, default=False,
              help="Show update plan without writing to GDB.")
def update_well_elevations_cmd(csv_path, site_id, benchmark_id, benchmark_elev_ft,
                               gdb, closure_tolerance_ft, dry_run):
    """Process level loop and push adjusted elevations to MonitoringWells (ArcGIS Pro)."""
    from autogis.core.envmon.process_level_loop import (
        load_level_loop_csv, compute_level_loop,
        select_elevations_for_update, update_well_elevations, format_loop_report)

    observations = load_level_loop_csv(Path(csv_path))
    result = compute_level_loop(observations, benchmark_id, benchmark_elev_ft,
                                closure_tolerance_ft)
    click.echo(format_loop_report(result))
    if result.blocked if hasattr(result, "blocked") else not result.within_tolerance:
        click.echo("Misclosure exceeds tolerance. Aborting elevation update.")
        raise SystemExit(1)

    # Get well IDs from GDB for filtering
    well_ids: set[str] = set()
    if not dry_run:
        _guard("update-well-elevations")
        from autogis.runtime.sessions import arcpy_env as _arcpy
        _ax = _arcpy()
        from pathlib import Path as _P
        wells_fc = str(_P(gdb) / "MonitoringWells")
        if _ax.Exists(wells_fc):
            with _ax.da.SearchCursor(wells_fc, ["LocationID"],
                                     f"SiteID='{site_id}'") as cur:
                for row in cur:
                    if row[0]:
                        well_ids.add(str(row[0]).strip())

    plan = select_elevations_for_update(result, well_ids)
    if plan.blocked:
        click.echo(f"Blocked: {plan.block_reason}")
        raise SystemExit(1)

    click.echo(f"Update plan: {len(plan.updates)} wells, {len(plan.skipped)} skipped")
    for loc_id, elev in plan.updates.items():
        click.echo(f"  {loc_id}: {elev:.3f} ft TOC")

    if not dry_run:
        n = update_well_elevations(gdb, site_id, plan)
        click.echo(f"Updated {n} MonitoringWells records.")
```

- [ ] **Step 2: Help test + commit**

```python
def test_update_well_elevations_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "update-well-elevations" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_process_level_loop.py
git commit -m "feat(cli): add update-well-elevations command (LOCAL, dry-run supported)"
```
