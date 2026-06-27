# RunEnvJobQueue Design

**Date:** 2026-06-27
**Status:** Approved
**Tool:** RunEnvJobQueue (Phase 1.5)
**Priority:** HIGH (enables batch site/event processing; WriteRunHistory already exists)

---

## Problem

The pipeline has no batch execution capability. Each tool is invoked individually from
the CLI or the `.pyt` toolbox. For a multi-site reporting event this means manually
sequencing 15+ steps across 3 sites — error-prone, non-reproducible, and producing no
audit trail of what actually ran and in what order.

`RunHistory` (ADR-017) is already implemented and ready to receive records. The
missing piece is the orchestration layer that populates it from a declarative job
manifest.

---

## Approach

**Chosen:** Declarative YAML manifest → `JobManifest` dataclass → sequential
execution loop → `RunHistory` write per step. Pure Python at the orchestrator level;
individual steps are dispatched to existing core functions. `LOCAL` steps (arcpy) fail
cleanly via the existing `_guard()` path — the queue continues to the next step and
records the failure.

**Rejected: Subprocess dispatch.** Calling `autogis envmon <cmd>` via `subprocess`
would work but loses structured return values, can't share a `RunHistory` instance,
and makes error capture harder. Direct function dispatch is simpler.

**Rejected: Celery/task queue.** Out of scope; the existing tools are serial and
single-machine. A proper task queue adds infrastructure complexity with no benefit at
this stage.

---

## Architecture

```
autogis/
  core/common/
    job_queue.py           ← NEW: JobStep, JobManifest, run_job_queue(), TOOL_REGISTRY
  config/
    job_queues/
      job_queue.example.yaml   ← NEW: documented example manifest
  adapters/
    cli.py                 ← add run-job-queue command under envmon group
tests/
  test_job_queue.py        ← NEW: arcpy-free
```

---

## Public API (`job_queue.py`)

```python
SCHEMA_VERSION = "1.0"

@dataclass
class JobStep:
    tool_name: str
    site_id: str
    event_id: Optional[str]
    args: dict = field(default_factory=dict)   # keyword args forwarded to the tool fn
    stop_on_error: bool = False                # abort remaining steps if this one errors

@dataclass
class JobManifest:
    manifest_id: str
    description: str
    steps: list[JobStep]
    run_history_path: Optional[Path] = None

def load_manifest(path: Path) -> JobManifest: ...

def run_job_queue(
    manifest: JobManifest,
    history_path: Optional[Path] = None,
) -> list[RunRecord]:
    """Execute all steps; return one RunRecord per step."""
```

---

## Tool Registry

`TOOL_REGISTRY: dict[str, Callable]` — maps `tool_name` string to a Python callable.
Each callable receives `(step: JobStep) -> tuple[dict, QACollector]` where the dict
is the `outputs` to log.

Initial registry contents (headless tools only; LOCAL tools not registered — they
raise `RuntimeUnavailable` cleanly and the queue captures the error as status="error"):

| tool_name | callable |
|---|---|
| `validate_config` | `validate_env_config(...)` from `validate_config.py` |
| `validate_units` | `validate_units_config(...)` from `validate_units.py` |
| `reconcile_locations` | `reconcile(...)` from `reconcile_locations.py` |
| `import_edd` | `import_edd(...)` from `edd_importer.py` |
| `manage_analyte_dict` | `check_analyte_dictionary(...)` |
| `manage_screening_levels` | `check_screening_levels(...)` (new, Phase 2.5) |

The registry is extensible: new tools add one line.

---

## Job Manifest Schema

```yaml
# autogis/config/job_queues/job_queue.example.yaml
manifest_id: "H281_2026Q2_import"
description: "Quarterly import run for H281 Glasgow"
run_history_path: "./run_history.csv"   # optional; defaults to ~/autogis_run_history.csv

steps:
  - tool_name: validate_config
    site_id: H281
    args:
      site_config: "autogis/config/sites/H281_Glasgow.yaml"
      analytes: "autogis/config/analytes/analyte_dictionary.yaml"

  - tool_name: import_edd
    site_id: H281
    event_id: "2026Q2"
    stop_on_error: true   # abort if EDD import fails
    args:
      edd_path: "data/H281_2026Q2_EDD.csv"
      profile_path: "autogis/config/lab_profiles/TestAmerica.yaml"
      gdb_path: "C:/GIS/H281/H281.gdb"
```

---

## CLI Command

```python
@envmon.command("run-job-queue")
@click.argument("manifest", type=click.Path(exists=True))
@click.option("--history", default=None, type=click.Path(),
              help="Path to run history CSV (overrides manifest setting).")
def run_job_queue_cmd(manifest, history):
    """Execute a job manifest (batch tool sequencer)."""
    from autogis.core.common.job_queue import load_manifest, run_job_queue
    m = load_manifest(Path(manifest))
    records = run_job_queue(m, Path(history) if history else None)
    errors = sum(1 for r in records if r.status == "error")
    click.echo(f"Ran {len(records)} steps. Errors: {errors}.")
    if errors:
        raise SystemExit(1)
```

---

## Data Flow

```
run-job-queue manifest.yaml
  → load_manifest(path) → JobManifest
  → for step in manifest.steps:
      t0 = now()
      try:
          fn = TOOL_REGISTRY[step.tool_name]
          outputs, qa = fn(step)
          status = qa.status()        # "OK" | "WARNING" | "FAIL"
          status_str = "success" if status != "FAIL" else "warning"
      except KeyError:
          status_str, outputs, qa = "error", {}, empty_qa
          if step.stop_on_error: break
      except Exception as e:
          status_str, outputs, qa = "error", {}, qa_with_error
          if step.stop_on_error: break
      run_history.write(RunRecord(tool_name=step.tool_name, ...))
  → return records
```

---

## Test Strategy

`tests/test_job_queue.py` — all arcpy-free:

1. `load_manifest()` parses example YAML into `JobManifest`
2. `run_job_queue()` with a manifest whose steps call stub functions — verifies
   `RunRecord` is written per step
3. `stop_on_error=True` aborts subsequent steps when a step fails
4. Unknown `tool_name` records `status="error"` without crashing
5. `JobManifest.steps` preserves ordering from YAML
6. `run_job_queue()` returns one `RunRecord` per step
7. `format_manifest` / summary line contains step count and error count
