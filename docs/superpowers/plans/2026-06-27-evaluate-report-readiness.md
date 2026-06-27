# EvaluateReportReadiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `EvaluateReportReadiness` — six-flag readiness gate + Dash_ReportReadiness write.
See spec: `docs/superpowers/specs/2026-06-27-evaluate-report-readiness-design.md`.

**Architecture:**
- New: `autogis/core/envmon/evaluate_report_readiness.py`
- Modify: `autogis/adapters/cli.py` — add `evaluate-report-readiness` command (LOCAL)
- New: `tests/envmon/test_evaluate_report_readiness.py`

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- `compute_readiness_flags()` and `format_readiness_report()` are arcpy-free.
- `evaluate_report_readiness()` is LOCAL, `# pragma: no cover`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Pure Python layer + tests

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_evaluate_report_readiness.py`:

```python
from autogis.core.envmon.evaluate_report_readiness import (
    ReadinessFlags, compute_readiness_flags, format_readiness_report,
)

_PLANNED = {"MW-01", "MW-02", "MW-03"}
_SAMPLED = {"MW-01", "MW-02", "MW-03"}
_SAMP_IDS = {"H281-MW01-GW", "H281-MW02-GW", "H281-MW03-GW"}
_WITH_RESULTS = {"H281-MW01-GW", "H281-MW02-GW", "H281-MW03-GW"}
_GIS = {"MW-01", "MW-02", "MW-03"}


def test_all_ready():
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, _WITH_RESULTS, _SAMP_IDS, _GIS, 0)
    assert flags.field_ready and flags.lab_ready and flags.gis_ready
    assert flags.qa_ready and flags.model_ready
    assert flags.report_ready and flags.overall_ready


def test_missing_lab_result():
    with_results = {"H281-MW01-GW", "H281-MW02-GW"}  # MW-03 missing
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, with_results, _SAMP_IDS, _GIS, 0)
    assert flags.lab_ready is False
    assert flags.report_ready is False


def test_missing_gis_location():
    gis = {"MW-01", "MW-02"}   # MW-03 not in GIS
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, _WITH_RESULTS, _SAMP_IDS, gis, 0)
    assert flags.gis_ready is False


def test_open_qa_errors():
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, _WITH_RESULTS, _SAMP_IDS, _GIS, 3)
    assert flags.qa_ready is False


def test_missing_planned_location():
    sampled = {"MW-01", "MW-02"}   # MW-03 not sampled
    flags = compute_readiness_flags(_PLANNED, sampled, _WITH_RESULTS, _SAMP_IDS, _GIS, 0)
    assert flags.field_ready is False


def test_no_planned_locations_uses_any_sampled():
    flags = compute_readiness_flags(set(), _SAMPLED, _WITH_RESULTS, _SAMP_IDS, _GIS, 0)
    assert flags.field_ready is True  # has samples, no planned set to violate


def test_model_ready_always_true():
    flags = compute_readiness_flags(set(), set(), set(), set(), set(), 999)
    assert flags.model_ready is True


def test_format_report_contains_pass():
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, _WITH_RESULTS, _SAMP_IDS, _GIS, 0)
    text = format_readiness_report(flags, "H281", "2026Q2")
    assert "PASS" in text


def test_format_report_contains_fail_for_lab():
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, {"H281-MW01-GW"}, _SAMP_IDS, _GIS, 0)
    text = format_readiness_report(flags, "H281", "2026Q2")
    assert "FAIL" in text


def test_format_report_shows_overall_status():
    flags = compute_readiness_flags(_PLANNED, _SAMPLED, _WITH_RESULTS, _SAMP_IDS, _GIS, 0)
    text = format_readiness_report(flags, "H281", "2026Q2")
    assert "OVERALL" in text.upper() or "Overall" in text
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_evaluate_report_readiness.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/evaluate_report_readiness.py`**

```python
"""evaluate_report_readiness.py — six-flag report readiness gate.

compute_readiness_flags() and format_readiness_report() are arcpy-free.
evaluate_report_readiness() is LOCAL (arcpy), # pragma: no cover.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ReadinessFlags:
    field_ready: bool
    lab_ready: bool
    gis_ready: bool
    qa_ready: bool
    model_ready: bool = True

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
    if planned_locations:
        field_ready = planned_locations.issubset(sampled_locations)
    else:
        field_ready = len(sampled_locations) > 0

    lab_ready = all_sample_ids.issubset(samples_with_results) if all_sample_ids else True
    gis_ready = sampled_locations.issubset(gis_locations) if sampled_locations else True
    qa_ready = open_qa_errors == 0

    return ReadinessFlags(
        field_ready=field_ready,
        lab_ready=lab_ready,
        gis_ready=gis_ready,
        qa_ready=qa_ready,
        model_ready=True,
    )


def format_readiness_report(flags: ReadinessFlags, site_id: str, event_id: str) -> str:
    def _f(b): return "[PASS]" if b else "[FAIL]"
    lines = [
        f"Report Readiness — {site_id} / {event_id}",
        "",
        f"  {_f(flags.field_ready):<8} Field sampling complete",
        f"  {_f(flags.lab_ready):<8} Lab results received",
        f"  {_f(flags.gis_ready):<8} GIS location coverage",
        f"  {_f(flags.qa_ready):<8} QA — no open errors",
        f"  {_f(flags.model_ready):<8} Model readiness (reserved)",
        "",
        f"  {'[OVERALL PASS]' if flags.overall_ready else '[OVERALL FAIL]'}"
        f"  Overall ready: {'YES' if flags.overall_ready else 'NO'}",
    ]
    return "\n".join(lines)


def evaluate_report_readiness(    # pragma: no cover
    gdb_path: str,
    site_id: str,
    event_id: str,
    planned_locations: Optional[list[str]] = None,
) -> ReadinessFlags:
    """Read GDB, compute flags, write Dash_ReportReadiness row."""
    from pathlib import Path as _P
    from datetime import datetime
    import arcpy
    from ...runtime.sessions import arcpy_env as _arcpy
    _ax = _arcpy()
    gdb = str(gdb_path)

    def _read_set(table, field, where=None):
        path = str(_P(gdb) / table)
        if not _ax.Exists(path):
            return set()
        result = set()
        with _ax.da.SearchCursor(path, [field], where) as cur:
            for row in cur:
                if row[0]:
                    result.add(str(row[0]).strip().upper())
        return result

    def _count(table, where=None):
        path = str(_P(gdb) / table)
        if not _ax.Exists(path):
            return 0
        n = 0
        with _ax.da.SearchCursor(path, ["OBJECTID"], where) as cur:
            for _ in cur:
                n += 1
        return n

    site_where = f"SiteID = '{site_id}'"
    event_where = f"SiteID = '{site_id}' AND EventID = '{event_id}'"

    sampled_locs = _read_set("Env_Samples", "LocationID", event_where)
    all_sample_ids = _read_set("Env_Samples", "SampleID", event_where)
    with_results = _read_set("Env_AnalyticalResults", "SampleID", event_where)
    gis_locs = _read_set("MonitoringWells", "LocationID", site_where)
    open_errors = _count("Env_ImportQA",
                         f"SiteID='{site_id}' AND Severity='ERROR'")

    planned = set(planned_locations) if planned_locations else set()
    flags = compute_readiness_flags(planned, sampled_locs, with_results,
                                    all_sample_ids, gis_locs, open_errors)

    # Write to Dash_ReportReadiness
    dash_table = str(_P(gdb) / "Dash_ReportReadiness")
    if _ax.Exists(dash_table):
        with _ax.da.InsertCursor(dash_table,
                                 ["SiteID", "EventID", "FieldReady", "LabReady",
                                  "GISReady", "QAReady", "ModelReady",
                                  "ReportReady", "OverallReady", "LastUpdated"]) as cur:
            cur.insertRow([site_id, event_id,
                           int(flags.field_ready), int(flags.lab_ready),
                           int(flags.gis_ready), int(flags.qa_ready),
                           int(flags.model_ready), int(flags.report_ready),
                           int(flags.overall_ready),
                           datetime.now().isoformat(timespec="seconds")])
    return flags
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_evaluate_report_readiness.py -v
```

Expected: all 10 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/evaluate_report_readiness.py tests/envmon/test_evaluate_report_readiness.py
git commit -m "feat(envmon): evaluate_report_readiness — ReadinessFlags + compute + format (LOCAL write)"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`** (LOCAL with `--gdb`, flag compute is headless)

```python
@envmon.command("evaluate-report-readiness")
@click.argument("gdb", type=click.Path())
@click.option("--site", "site_id", required=True)
@click.option("--event", "event_id", required=True)
@click.option("--planned", "planned_csv", default=None,
              help="Comma-separated planned location IDs.")
@click.option("--report", default=None, type=click.Path())
def evaluate_report_readiness_cmd(gdb, site_id, event_id, planned_csv, report):
    """Check report readiness flags and write to Dash_ReportReadiness (ArcGIS Pro)."""
    _guard("evaluate-report-readiness")
    from autogis.core.envmon.evaluate_report_readiness import (
        evaluate_report_readiness, format_readiness_report)
    planned = [x.strip() for x in planned_csv.split(",")] if planned_csv else None
    flags = evaluate_report_readiness(gdb, site_id, event_id, planned)
    text = format_readiness_report(flags, site_id, event_id)
    click.echo(text)
    if report:
        Path(report).write_text(text, encoding="utf-8")
    if not flags.overall_ready:
        raise SystemExit(1)
```

- [ ] **Step 2: Help test + commit**

```python
def test_evaluate_report_readiness_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "evaluate-report-readiness" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_evaluate_report_readiness.py
git commit -m "feat(cli): add evaluate-report-readiness command (LOCAL, exit-1 if not ready)"
```
