# ADR-017: CSV-based append-only run history log

**Status:** Accepted (write side deferred — see below)

**Date:** 2026-06-25

## Status update (2026-07-02)

`RunHistory.write` has zero production callers: no CLI command, `.pyt` `execute()`,
or core module writes a `RunRecord`. `EvaluateReportReadiness` and `envmon
run-history` (the readers this ADR names) are shipped and will see an empty/absent
log unless the user hand-authors `run_history.csv`. `job_queue.py` and
`dashboard_data_mart.py` — the other two consumers this ADR names — don't reference
`RunHistory` at all.

**Update (2026-07-04, issue #147):** the "zero production callers" claim above is
now stale. `agol promote` (shipped the same evening in PR #118) added
`_log_promotion()` (`core/agol/promote.py`), which does call
`run_history.write(RunRecord(...))` — a real, deliberate per-command wiring
decision, consistent with the "defer to per-command wiring" call made below. It's
the *only* command wired so far, so `evaluate-readiness`/`envmon run-history` are
still structurally near-empty for every other command. See issue #147 for the
open question of which commands get wired next (or whether to revisit the generic
CLI-seam hook now that ADR-0050 §5/§6 has scoped a GUI's run-history needs).

**Update (2026-07-06):** issue #147's option (b) was taken — ADR-0054's
`RecordingCommand`/`RecordingGroup` pair (`cli.py`) now wraps essentially every
leaf command (~105, via Click's `command_class`/`group_class` cascade) and calls
`RunHistory.write()` generically at the CLI adapter seam, superseding the
per-command hand-wiring this status update previously described. The "not
uniformly available at the adapter layer" concern in the "generic hook" analysis
below was resolved via `ctx.meta` for QA counts and `ctx.params`/exit-code
classification for the rest — see ADR-0054 for the mechanism. `evaluate-readiness`
and `envmon run-history` are no longer structurally near-empty; the one open item
is `promote`'s pre-existing self-logging being skip-listed to avoid double
recording (also documented in ADR-0054).

A generic write-side hook (e.g. a click `result_callback` wrapping every `envmon`
command) was considered and rejected: it would fire under every `CliRunner` test in
the suite (stray-file writes / failures in read-only test dirs unless explicitly
disabled), and — more importantly — it can only capture `tool_name`/timing/
success-vs-exception generically. `site_id`, `event_id`, and `qa_count_*` are not
uniformly available at the adapter layer (commands `click.echo` rather than return
structured results, and readers filter on `site_id`), so a generic hook would
produce a log `evaluate-readiness` still couldn't use correctly — worse than no log,
since it looks populated. Populating those fields correctly means touching each
command body, the "80 call sites" this ADR's original decision explicitly avoided.

**Write side deferred until a per-command wiring decision is made deliberately**
(tracked in issue #104), not fast-tracked as a generic hook. The read side
(`query`/`latest`) and CSV format below remain valid design; only production writers
are missing.

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
