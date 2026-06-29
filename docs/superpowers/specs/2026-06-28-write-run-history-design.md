# WriteRunHistory Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** WriteRunHistory (Phase 1 / Tool 1.2)
**Priority:** HIGH — enables audit trail for all tool executions; prerequisite for job queue and replay

---

## Problem

With 30+ CLI commands, there is no audit trail of what ran, when, with what inputs,
or whether it succeeded. When an analyst needs to reproduce a report or debug a
pipeline failure, they have no record of which event dataset was used, what
screening levels were applied, or when figures were generated. `run-history-report`
and `run-history-query` tools already exist but have no persistent store to write to.

---

## Approach

**Chosen:** Append-only JSON-Lines run history file (`Env_RunHistory.jsonl`).
Each tool execution writes a single JSON record: `run_id`, `tool_name`,
`started_at`, `finished_at`, `status` (success/error/warning), `inputs` dict,
`outputs` dict, `qa_summary` (error/warning counts), `duration_s`, `host`.
The file is human-readable and grep-friendly. `query_run_history()` reads all
records and supports filtering by tool name, date range, or status.

**Rejected: SQLite.** Adds a dependency and makes the file opaque to grep/tail.
JSON-Lines is zero-dependency and survives partial writes (one record per line).

**Rejected: Integrating into every tool.** Run history is written by a context
manager `RunHistoryContext` that wraps any tool call — tools don't need modification.

---

## Architecture

```
autogis/
  core/envmon/
    run_history_writer.py      ← NEW
  adapters/
    cli.py                     ← add log-run and query-runs commands (headless)
tests/envmon/
  test_run_history_writer.py   ← NEW
```

---

## Public API (`run_history_writer.py`)

```python
@dataclass
class RunRecord:
    run_id: str           # UUID4
    tool_name: str
    started_at: str       # ISO datetime
    finished_at: str
    status: str           # success | error | warning
    inputs: dict
    outputs: dict
    qa_error_count: int
    qa_warning_count: int
    duration_s: float
    host: str
    notes: str

@contextmanager
def run_history_context(
    tool_name: str,
    history_path: Path,
    *,
    inputs: dict | None = None,
    notes: str = "",
) -> Generator[RunRecord, None, None]:
    """
    Context manager. Yields a RunRecord stub; caller populates outputs.
    On exit: sets finished_at, duration_s, status; appends JSON line.
    If exception: status = "error".
    """

def append_run_record(record: RunRecord, history_path: Path) -> None:
    """Append a single record to the JSON-Lines file."""

def query_run_history(
    history_path: Path,
    *,
    tool_name: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> list[RunRecord]:
    """Read and filter run history records."""

def format_run_summary(records: list[RunRecord]) -> str:
    """Render as text table: run_id | tool | started_at | status | duration_s"""
```

---

## CLI Commands

```
autogis envmon log-run \
  --tool <tool_name> \
  --status success|error|warning \
  --inputs <json_string> \
  --outputs <json_string> \
  --duration <seconds> \
  --history <env_run_history.jsonl> \
  [--notes <text>]

autogis envmon query-runs \
  --history <env_run_history.jsonl> \
  [--tool <name>] \
  [--status success|error|warning] \
  [--date-from <ISO>] \
  [--date-to <ISO>] \
  [--limit 100]
```

Headless.

---

## Test Strategy

`tests/envmon/test_run_history_writer.py` — arcpy-free:

1. `append_run_record` writes a valid JSON line to file
2. `query_run_history` reads it back as a RunRecord with correct fields
3. `run_history_context` sets `started_at`, `finished_at`, `status=success` on clean exit
4. Exception inside context → `status=error`, file still written
5. `query_run_history(tool_name=...)` filters to matching tool only
6. `query_run_history(status="error")` returns only error records
7. `query_run_history(date_from=...)` respects date filter
8. `format_run_summary` produces string with header + data rows
9. Multiple records accumulate in file (append semantics)
