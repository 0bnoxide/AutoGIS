# EvaluateReportReadiness Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** EvaluateReportReadiness (Phase 3.7 / Tool 9.0b)
**Priority:** HIGH (single gate before report submission; prevents incomplete deliverables)

---

## Problem

Report submission currently has no automated gate. A report can be issued while:
- Not all wells have been sampled (missing `Env_Samples` rows)
- Lab results haven't been received (no `Env_AnalyticalResults` for some samples)
- QA issues remain unresolved (open ERROR records in `Env_ImportQA`)
- Figures haven't been exported (no entry in a figure registry)

This leads to rework and re-submissions. The `Dash_ReportReadiness` table was added
to TABLE_SCHEMAS in Phase 1.4 precisely to hold this status — it just needs to be
populated.

---

## Approach

**Chosen:** LOCAL tool (arcpy) that reads five source tables, computes six readiness
flags, writes one row to `Dash_ReportReadiness`, and prints a pass/fail summary.
Pure-Python logic (flag computation from dict inputs) is arcpy-free and testable.

Readiness flags:
- `FieldReady` — all planned locations have at least one `Env_Samples` row
- `LabReady` — all Env_Samples rows have at least one `Env_AnalyticalResults` row
- `GISReady` — all locations in Env_Samples exist as features in `MonitoringWells`
- `QAReady` — no ERROR-severity records in `Env_ImportQA` for this site/event
- `ModelReady` — reserved (always True until groundwater model tools exist)
- `ReportReady` — all five flags True
- `OverallReady` — alias for `ReportReady`

**Rejected: Separate "approve" step.** Over-engineering. The tool is idempotent — run
it before submission, fix issues, run again. The last row in `Dash_ReportReadiness`
is the current state.

---

## Architecture

```
autogis/
  core/envmon/
    evaluate_report_readiness.py   ← NEW
  adapters/
    cli.py                         ← add evaluate-report-readiness command (LOCAL)
tests/envmon/
  test_evaluate_report_readiness.py ← NEW, arcpy-free (flag computation only)
```

---

## Public API

```python
@dataclass
class ReadinessFlags:
    field_ready: bool
    lab_ready: bool
    gis_ready: bool
    qa_ready: bool
    model_ready: bool = True   # always True until Phase 5

    @property
    def report_ready(self) -> bool:
        return all([self.field_ready, self.lab_ready,
                    self.gis_ready, self.qa_ready, self.model_ready])

    @property
    def overall_ready(self) -> bool:
        return self.report_ready

def compute_readiness_flags(
    planned_locations: set[str],
    sampled_locations: set[str],
    samples_with_results: set[str],
    all_sample_ids: set[str],
    gis_locations: set[str],
    open_qa_errors: int,
) -> ReadinessFlags:
    """Pure Python — no arcpy. All inputs are pre-fetched sets/counts."""

def format_readiness_report(flags: ReadinessFlags, site_id: str, event_id: str) -> str:
    """[PASS]/[FAIL] per flag, summary line."""

def evaluate_report_readiness(   # pragma: no cover — requires arcpy
    gdb_path: str,
    site_id: str,
    event_id: str,
    planned_locations: Optional[list[str]] = None,
) -> ReadinessFlags:
    """Read GDB, compute flags, write Dash_ReportReadiness row."""
```

---

## Planned Locations

`planned_locations` is optional:
- If provided: `FieldReady = sampled_locations >= planned_locations`
- If None: `FieldReady = len(sampled_locations) > 0` (at least one sample)

Planned locations come from the site config's `monitoring_wells_fc` feature class or
from an explicit list passed by the caller.

---

## CLI Command

```
autogis envmon evaluate-report-readiness <gdb> --site H281 --event 2026Q2 \
    [--planned-locations MW-01,MW-02,MW-03] \
    [--report report.md]
```

Exit code 1 if `overall_ready = False`.

---

## Test Strategy

`tests/envmon/test_evaluate_report_readiness.py` — all arcpy-free:

1. All sets fully covered → all flags True, `report_ready=True`
2. Missing lab result for one sample → `lab_ready=False`
3. One location not in GIS → `gis_ready=False`
4. One open QA error → `qa_ready=False`
5. Missing planned location → `field_ready=False` (with planned_locations provided)
6. `model_ready` always True regardless of inputs
7. `format_readiness_report()` contains `[PASS]`/`[FAIL]` per flag
8. `format_readiness_report()` final line shows overall status
