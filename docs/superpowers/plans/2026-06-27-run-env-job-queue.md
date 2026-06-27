# RunEnvJobQueue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `RunEnvJobQueue` — a declarative YAML job manifest parser and
sequential execution loop that dispatches existing core tools and records each run in
`RunHistory`. See spec: `docs/superpowers/specs/2026-06-27-run-env-job-queue-design.md`.

**Architecture:**
- New: `autogis/core/common/job_queue.py` — `JobStep`, `JobManifest`, `run_job_queue()`, `TOOL_REGISTRY`
- New: `autogis/config/job_queues/job_queue.example.yaml`
- Modify: `autogis/adapters/cli.py` — add `run-job-queue` command

## Global Constraints

- Branch: `feat/gdb-schema-upgrade`
- All code in `core/` arcpy-free.
- `run_job_queue()` must not call `sys.exit()` — callers decide on exit codes.
- Run tests with `python -m pytest -q`.
- Commit after each task.

---

### Task 1: Core `job_queue.py` module

**Files:**
- Create: `autogis/core/common/job_queue.py`
- Create: `tests/test_job_queue.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_job_queue.py`:

```python
import uuid
from pathlib import Path
from autogis.core.common.job_queue import (
    JobStep, JobManifest, load_manifest, run_job_queue,
)
from autogis.core.common.run_history import RunRecord

_EXAMPLE_YAML = """\
manifest_id: test-run
description: unit test manifest
steps:
  - tool_name: _noop
    site_id: TEST
    args: {}
  - tool_name: _noop
    site_id: TEST
    args: {}
"""

def test_load_manifest_parses_steps(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(_EXAMPLE_YAML, encoding="utf-8")
    m = load_manifest(p)
    assert m.manifest_id == "test-run"
    assert len(m.steps) == 2
    assert m.steps[0].tool_name == "_noop"

def test_run_job_queue_returns_one_record_per_step(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(_EXAMPLE_YAML, encoding="utf-8")
    m = load_manifest(p)
    records = run_job_queue(m)
    assert len(records) == 2
    assert all(isinstance(r, RunRecord) for r in records)

def test_run_job_queue_records_success_status(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(_EXAMPLE_YAML, encoding="utf-8")
    m = load_manifest(p)
    records = run_job_queue(m)
    assert all(r.status == "success" for r in records)

def test_unknown_tool_records_error(tmp_path):
    yaml = """\
manifest_id: err-run
description: unknown tool test
steps:
  - tool_name: _unknown_tool_xyz
    site_id: TEST
    args: {}
"""
    p = tmp_path / "m.yaml"
    p.write_text(yaml, encoding="utf-8")
    records = run_job_queue(load_manifest(p))
    assert records[0].status == "error"

def test_stop_on_error_aborts_remaining(tmp_path):
    yaml = """\
manifest_id: abort-run
description: abort on error
steps:
  - tool_name: _unknown_tool_xyz
    site_id: TEST
    stop_on_error: true
    args: {}
  - tool_name: _noop
    site_id: TEST
    args: {}
"""
    p = tmp_path / "m.yaml"
    p.write_text(yaml, encoding="utf-8")
    records = run_job_queue(load_manifest(p))
    assert len(records) == 1     # second step never ran

def test_steps_preserve_ordering(tmp_path):
    yaml = """\
manifest_id: order-run
description: ordering test
steps:
  - tool_name: _noop
    site_id: ALPHA
  - tool_name: _noop
    site_id: BETA
  - tool_name: _noop
    site_id: GAMMA
"""
    p = tmp_path / "m.yaml"
    p.write_text(yaml, encoding="utf-8")
    records = run_job_queue(load_manifest(p))
    assert [r.site_id for r in records] == ["ALPHA", "BETA", "GAMMA"]

def test_run_history_written_when_path_provided(tmp_path):
    p = tmp_path / "manifest.yaml"
    p.write_text(_EXAMPLE_YAML, encoding="utf-8")
    hist = tmp_path / "history.csv"
    run_job_queue(load_manifest(p), history_path=hist)
    assert hist.exists()
    assert hist.read_text().count("\n") >= 3  # header + 2 rows
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_job_queue.py -v
```

Expected: all fail (ImportError).

- [ ] **Step 3: Create `autogis/core/common/job_queue.py`**

```python
"""job_queue.py — declarative job manifest + sequential execution loop.

Pure-Python at the orchestrator level. Individual tool callables are registered
in TOOL_REGISTRY. Unknown tool_names or runtime errors are captured as
RunRecord(status="error") — the queue always continues unless stop_on_error.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .qa import QACollector, QARecord, SEV_ERROR
from .run_history import RunHistory, RunRecord


@dataclass
class JobStep:
    tool_name: str
    site_id: str
    event_id: Optional[str] = None
    args: dict = field(default_factory=dict)
    stop_on_error: bool = False


@dataclass
class JobManifest:
    manifest_id: str
    description: str
    steps: list[JobStep]
    run_history_path: Optional[Path] = None


def load_manifest(path: Path) -> JobManifest:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    steps = [
        JobStep(
            tool_name=s["tool_name"],
            site_id=s.get("site_id", ""),
            event_id=s.get("event_id"),
            args=s.get("args") or {},
            stop_on_error=s.get("stop_on_error", False),
        )
        for s in (data.get("steps") or [])
    ]
    return JobManifest(
        manifest_id=data.get("manifest_id", str(uuid.uuid4())),
        description=data.get("description", ""),
        steps=steps,
        run_history_path=Path(data["run_history_path"])
        if data.get("run_history_path") else None,
    )


# ---------------------------------------------------------------------------
# Tool registry — maps tool_name → callable(step) -> (outputs_dict, QACollector)
# ---------------------------------------------------------------------------
def _noop(step: JobStep):
    qa = QACollector()
    return {}, qa


TOOL_REGISTRY: dict[str, Callable] = {
    "_noop": _noop,   # used in tests; not documented in user-facing example
}


def _register_headless_tools() -> None:
    """Lazy registration so tests don't need all core modules importable."""
    try:
        from ..envmon.validate_config import validate_env_config

        def _validate_config(step: JobStep):
            from pathlib import Path as P
            args = step.args
            qa = validate_env_config(
                P(args["site_config"]) if args.get("site_config") else None,
                [P(p) for p in args.get("profiles", [])],
                [P(f) for f in args.get("figures", [])],
                P(args["analytes"]) if args.get("analytes") else None,
                P(args["screening"]) if args.get("screening") else None,
            )
            return {}, qa

        TOOL_REGISTRY["validate_config"] = _validate_config
    except ImportError:
        pass  # core not yet importable in minimal test envs


_register_headless_tools()


def run_job_queue(
    manifest: JobManifest,
    history_path: Optional[Path] = None,
) -> list[RunRecord]:
    hist_path = history_path or manifest.run_history_path
    history = RunHistory(hist_path) if hist_path else None
    records: list[RunRecord] = []

    for step in manifest.steps:
        started = datetime.now()
        qa = QACollector()
        outputs: dict = {}
        status = "success"

        fn = TOOL_REGISTRY.get(step.tool_name)
        if fn is None:
            qa.add(QARecord(severity=SEV_ERROR, category="unknown_tool",
                            message=f"No registered tool: {step.tool_name!r}"))
            status = "error"
        else:
            try:
                outputs, qa = fn(step)
                counts = qa.counts_by_severity()
                if counts.get("ERROR", 0):
                    status = "warning"
            except Exception as exc:
                qa.add(QARecord(severity=SEV_ERROR, category="tool_exception",
                                message=str(exc)))
                status = "error"

        counts = qa.counts_by_severity()
        record = RunRecord(
            run_id=str(uuid.uuid4()),
            tool_name=step.tool_name,
            site_id=step.site_id,
            event_id=step.event_id,
            started_at=started,
            finished_at=datetime.now(),
            status=status,
            inputs=step.args,
            outputs=outputs,
            qa_count_error=counts.get("ERROR", 0),
            qa_count_warning=counts.get("WARNING", 0),
            qa_count_info=counts.get("INFO", 0),
            message=qa.records[-1].message if qa.records else "",
        )
        if history:
            history.write(record)
        records.append(record)

        if status == "error" and step.stop_on_error:
            break

    return records
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_job_queue.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add autogis/core/common/job_queue.py tests/test_job_queue.py
git commit -m "feat(common): job_queue — JobManifest + run_job_queue + TOOL_REGISTRY"
```

---

### Task 2: Example manifest + CLI command

**Files:**
- Create: `autogis/config/job_queues/job_queue.example.yaml`
- Modify: `autogis/adapters/cli.py`

- [ ] **Step 1: Write example manifest**

```yaml
# autogis/config/job_queues/job_queue.example.yaml
manifest_id: "H281_2026Q2"
description: "Quarterly import + validation for H281 Glasgow"
run_history_path: "./run_history.csv"

steps:
  - tool_name: validate_config
    site_id: H281
    stop_on_error: true
    args:
      site_config: "autogis/config/sites/H281_Glasgow.yaml"
      analytes: "autogis/config/analytes/analyte_dictionary.yaml"
      screening: "autogis/config/screening_levels/screening_levels.yaml"

  - tool_name: validate_units
    site_id: H281
    args:
      analytes: "autogis/config/analytes/analyte_dictionary.yaml"
      screening: "autogis/config/screening_levels/screening_levels.yaml"
```

- [ ] **Step 2: Add CLI command to `cli.py`** (after `upgrade-schema` command block)

```python
@envmon.command("run-job-queue")
@click.argument("manifest", type=click.Path(exists=True))
@click.option("--history", default=None, type=click.Path(),
              help="Path to run history CSV (overrides manifest setting).")
def run_job_queue_cmd(manifest, history):
    """Execute a job manifest — sequential batch tool runner."""
    from autogis.core.common.job_queue import load_manifest, run_job_queue
    m = load_manifest(Path(manifest))
    records = run_job_queue(m, Path(history) if history else None)
    errors = sum(1 for r in records if r.status == "error")
    warnings = sum(1 for r in records if r.status == "warning")
    click.echo(f"Ran {len(records)} steps: {errors} error(s), {warnings} warning(s).")
    if errors:
        raise SystemExit(1)
```

- [ ] **Step 3: Add help test**

```python
# Append to tests/test_job_queue.py
from click.testing import CliRunner
from autogis.adapters.cli import autogis

def test_run_job_queue_in_envmon_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "run-job-queue" in result.output
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/test_job_queue.py -v
```

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py autogis/config/job_queues/job_queue.example.yaml tests/test_job_queue.py
git commit -m "feat(cli): add run-job-queue command; add job_queue.example.yaml"
```
