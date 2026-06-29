# WriteRunHistory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `WriteRunHistory` — JSON-Lines append-only run log; context manager wrapping any tool call; query/format helpers; `log-run` and `query-runs` CLI commands.
See spec: `docs/superpowers/specs/2026-06-28-write-run-history-design.md`.

**Architecture:**
- New: `autogis/core/envmon/run_history_writer.py`
- Modify: `autogis/adapters/cli.py` — add `log-run` and `query-runs` commands (headless)
- New: `tests/envmon/test_run_history_writer.py`

## Global Constraints

- Arcpy-free. stdlib only: `json`, `uuid`, `datetime`, `socket`, `contextlib`.
- JSON-Lines format: one JSON object per line; append-only.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `run_history_writer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_run_history_writer.py`:

```python
from pathlib import Path
import json
import pytest
from autogis.core.envmon.run_history_writer import (
    RunRecord, append_run_record, query_run_history,
    run_history_context, format_run_summary,
)


def _make_record(**kw) -> RunRecord:
    defaults = dict(
        run_id="test-uuid", tool_name="test-tool",
        started_at="2026-06-28T10:00:00+00:00",
        finished_at="2026-06-28T10:00:05+00:00",
        status="success", inputs={}, outputs={},
        qa_error_count=0, qa_warning_count=0,
        duration_s=5.0, host="testhost", notes="",
    )
    defaults.update(kw)
    return RunRecord(**defaults)


def test_append_and_query(tmp_path):
    hist = tmp_path / "history.jsonl"
    rec = _make_record()
    append_run_record(rec, hist)
    records = query_run_history(hist)
    assert len(records) == 1
    assert records[0].tool_name == "test-tool"
    assert records[0].status == "success"


def test_multiple_append(tmp_path):
    hist = tmp_path / "history.jsonl"
    append_run_record(_make_record(tool_name="tool-a"), hist)
    append_run_record(_make_record(tool_name="tool-b"), hist)
    records = query_run_history(hist)
    assert len(records) == 2


def test_filter_by_tool(tmp_path):
    hist = tmp_path / "history.jsonl"
    append_run_record(_make_record(tool_name="import-edd"), hist)
    append_run_record(_make_record(tool_name="build-event"), hist)
    results = query_run_history(hist, tool_name="import-edd")
    assert len(results) == 1
    assert results[0].tool_name == "import-edd"


def test_filter_by_status(tmp_path):
    hist = tmp_path / "history.jsonl"
    append_run_record(_make_record(status="success"), hist)
    append_run_record(_make_record(status="error"), hist)
    results = query_run_history(hist, status="error")
    assert len(results) == 1
    assert results[0].status == "error"


def test_filter_by_date(tmp_path):
    hist = tmp_path / "history.jsonl"
    append_run_record(_make_record(started_at="2026-01-15T10:00:00+00:00"), hist)
    append_run_record(_make_record(started_at="2026-06-15T10:00:00+00:00"), hist)
    results = query_run_history(hist, date_from="2026-06-01")
    assert len(results) == 1


def test_context_manager_success(tmp_path):
    hist = tmp_path / "history.jsonl"
    with run_history_context("my-tool", hist, inputs={"x": 1}) as rec:
        rec.outputs["result"] = "ok"
    records = query_run_history(hist)
    assert records[0].status == "success"
    assert records[0].tool_name == "my-tool"
    assert records[0].duration_s >= 0


def test_context_manager_exception(tmp_path):
    hist = tmp_path / "history.jsonl"
    with pytest.raises(ValueError):
        with run_history_context("failing-tool", hist) as rec:
            raise ValueError("boom")
    records = query_run_history(hist)
    assert records[0].status == "error"
    assert "boom" in records[0].notes


def test_format_run_summary(tmp_path):
    hist = tmp_path / "history.jsonl"
    append_run_record(_make_record(), hist)
    records = query_run_history(hist)
    table = format_run_summary(records)
    assert "test-tool" in table
    assert "success" in table
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_run_history_writer.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/run_history_writer.py`**

```python
"""run_history_writer.py — JSON-Lines append-only run history for tool auditing."""
from __future__ import annotations

import json
import socket
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional


@dataclass
class RunRecord:
    run_id: str
    tool_name: str
    started_at: str
    finished_at: str
    status: str          # success | error | warning
    inputs: dict
    outputs: dict
    qa_error_count: int
    qa_warning_count: int
    duration_s: float
    host: str
    notes: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration(start: str, end: str) -> float:
    try:
        from datetime import datetime as dt
        fmt = lambda s: dt.fromisoformat(s)
        return (fmt(end) - fmt(start)).total_seconds()
    except Exception:
        return 0.0


def append_run_record(record: RunRecord, history_path: Path) -> None:
    p = Path(history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record)) + "\n")


def query_run_history(
    history_path: Path,
    *,
    tool_name: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
) -> list:
    p = Path(history_path)
    if not p.exists():
        return []
    records = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                records.append(RunRecord(**d))
            except Exception:
                continue

    if tool_name:
        records = [r for r in records if r.tool_name == tool_name]
    if status:
        records = [r for r in records if r.status == status]
    if date_from:
        records = [r for r in records if r.started_at[:10] >= date_from]
    if date_to:
        records = [r for r in records if r.started_at[:10] <= date_to]
    return records[-limit:]


@contextmanager
def run_history_context(
    tool_name: str,
    history_path: Path,
    *,
    inputs: Optional[dict] = None,
    notes: str = "",
) -> Generator:
    started = _now()
    rec = RunRecord(
        run_id=str(uuid.uuid4()),
        tool_name=tool_name,
        started_at=started,
        finished_at="",
        status="success",
        inputs=inputs or {},
        outputs={},
        qa_error_count=0,
        qa_warning_count=0,
        duration_s=0.0,
        host=socket.gethostname(),
        notes=notes,
    )
    try:
        yield rec
    except Exception as exc:
        rec.status = "error"
        rec.notes = f"{notes}; {exc}" if notes else str(exc)
        raise
    finally:
        rec.finished_at = _now()
        rec.duration_s = _duration(rec.started_at, rec.finished_at)
        append_run_record(rec, history_path)


def format_run_summary(records: list) -> str:
    if not records:
        return "(no records)"
    cols = ["run_id", "tool_name", "started_at", "status", "duration_s"]
    widths = [36, 28, 26, 10, 10]

    def _cell(v, w):
        return str(v)[:w].ljust(w)

    sep = "  "
    header = sep.join(_cell(c, w) for c, w in zip(cols, widths))
    rule = sep.join("─" * w for w in widths)
    rows = [header, rule]
    for r in records:
        vals = [getattr(r, c, "") for c in cols]
        rows.append(sep.join(_cell(str(v), w) for v, w in zip(vals, widths)))
    return "\n".join(rows)
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_run_history_writer.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/run_history_writer.py \
        tests/envmon/test_run_history_writer.py
git commit -m "feat(envmon): run_history_writer — JSON-Lines audit log + context manager"
```

---

### Task 2: CLI commands

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("log-run")
@click.option("--tool", "tool_name", required=True)
@click.option("--status", type=click.Choice(["success", "error", "warning"]),
              default="success")
@click.option("--inputs", "inputs_json", default="{}")
@click.option("--outputs", "outputs_json", default="{}")
@click.option("--duration", "duration_s", type=float, default=0.0)
@click.option("--history", "history_path", required=True, type=click.Path())
@click.option("--notes", default="")
def log_run_cmd(tool_name, status, inputs_json, outputs_json,
                duration_s, history_path, notes):
    """Append a tool run record to the JSON-Lines run history file (headless)."""
    import json as _json
    from autogis.core.envmon.run_history_writer import RunRecord, append_run_record
    import uuid, socket
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rec = RunRecord(
        run_id=str(uuid.uuid4()), tool_name=tool_name,
        started_at=now, finished_at=now, status=status,
        inputs=_json.loads(inputs_json), outputs=_json.loads(outputs_json),
        qa_error_count=0, qa_warning_count=0,
        duration_s=duration_s, host=socket.gethostname(), notes=notes,
    )
    append_run_record(rec, Path(history_path))
    click.echo(f"Logged: {tool_name} [{status}]  → {history_path}")


@envmon.command("query-runs")
@click.option("--history", "history_path", required=True, type=click.Path(exists=True))
@click.option("--tool", "tool_name", default=None)
@click.option("--status", "status_filter", default=None)
@click.option("--date-from", default=None)
@click.option("--date-to", default=None)
@click.option("--limit", type=int, default=100, show_default=True)
def query_runs_cmd(history_path, tool_name, status_filter, date_from,
                   date_to, limit):
    """Query run history JSON-Lines file and print summary table (headless)."""
    from autogis.core.envmon.run_history_writer import (
        query_run_history, format_run_summary)
    records = query_run_history(
        Path(history_path), tool_name=tool_name, status=status_filter,
        date_from=date_from, date_to=date_to, limit=limit,
    )
    click.echo(format_run_summary(records))
    click.echo(f"\n{len(records)} record(s).")
```

- [ ] **Step 2: Help test + commit**

```python
def test_log_run_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "log-run" in result.output

def test_query_runs_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "query-runs" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_run_history_writer.py
git commit -m "feat(cli): add log-run and query-runs commands"
```
