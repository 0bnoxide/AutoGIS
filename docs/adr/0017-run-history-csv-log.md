# ADR-017: CSV-based append-only run history log

**Status:** Accepted

**Date:** 2026-06-25

## Context

Every AutoGIS tool execution needs an auditable record: what ran, when, against which
site/event, what it produced, and whether it succeeded. This record is consumed by:
- `EvaluateReportReadiness` — checks that required tools have run successfully for an event
- Dashboard data mart tools — show last-run status per site
- Job queue (`RunEnvJobQueue`) — prevents re-running completed steps

Options: append-only CSV, SQLite, GDB table (`Env_RunHistory`).

## Decision

Implement `RunHistory` in `autogis/core/common/run_history.py` as an append-only CSV file.

`RunRecord` is a `@dataclass` with 13 fields: `run_id` (UUID), `tool_name`, `site_id`, `event_id`, `started_at`, `finished_at`, `status`, `inputs` (JSON), `outputs` (JSON), `qa_count_error/warning/info`, `message`.

`RunHistory(path)` exposes:
- `write(record)` — append; best-effort (never raises on failure; logs warning only)
- `query(site_id, tool_name, since, status)` — filter; raises `RunHistoryError` on corrupt file
- `latest(tool_name, site_id)` — most recent matching record

`None` values in `event_id` are serialized via `_NONE_SENTINEL = "__None__"` since CSV has no null type. `inputs` and `outputs` dicts are JSON-encoded in a single CSV column.

Path is configured in `SiteConfig` under `run_history_path`; defaults to `run_history.csv` in the project root.

## Consequences

### Positive consequences

- Zero dependencies (stdlib `csv`, `json`, `uuid`) — importable anywhere without arcpy
- Human-readable; viewable in Excel or any text editor
- `write()` best-effort design ensures a tool failure in logging never masks the real tool result
- `query()` returns typed `RunRecord` objects, not raw dicts — callers don't parse strings

### Negative consequences

- No transactions; concurrent writers can corrupt the file (TOCTOU race on header write — minor, tools currently run single-threaded)
- `_NONE_SENTINEL = "__None__"` creates an edge case: an `event_id` value that happens to be the string `"__None__"` would round-trip as `None` (extremely unlikely in practice)
- No indexing; `query()` does a full file scan — acceptable for small files (< 10,000 records per project)
- `Optional` vs `str | None` style inconsistency in the module (minor, Python 3.10+ `str | None` preferred going forward)

## Alternatives considered

1. **SQLite:** Proper null support, indexing, transactions.
   - **Rejected:** Adds a dependency (stdlib `sqlite3` is available but adds schema management); overkill for a simple append log; harder to inspect manually.

2. **GDB table (Env_RunHistory):** Store run history in the project GDB.
   - **Rejected:** Requires arcpy to write, breaking the arcpy-free core invariant. Tools would need arcpy to log their own execution.

3. **JSON Lines file:** One JSON object per line.
   - **Rejected:** Not viewable in Excel; no stdlib reader/writer as clean as `csv.DictReader/DictWriter`.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — run_history.py upholds this invariant by using CSV not GDB
- [ADR-014: Schema dataclass package](0014-schema-dataclass-package.md) — `RunRecord` is a parallel dataclass (not in `schema/`; run history is infrastructure, not domain data)
