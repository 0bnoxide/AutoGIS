# ADR-0053: CLI-seam run recording via RecordingCommand/RecordingGroup, not a result callback

**Status:** Accepted

**Date:** 2026-07-04

## Context

ADR-0050 item 6 decided that run-history writes happen at the CLI adapter
seam (`cli.py`), covering every invocation regardless of caller. It
described the mechanism as a callback — "the CLI-seam callback" — following
the architecture review's suggestion of a "click result-callback"
(`docs/reviews/fable-architecture-review.md:53`) and the planning doc's
"one result-callback wired at the CLI adapter seam"
(`docs/superpowers/specs/2026-07-03-unified-gui-planning.md:274`).

That wording is factually wrong against Click's execution model: a plain
`click.Group` `result_callback` fires only after a clean return of the
group's invoke chain. It never fires on `ClickException` (every
runtime-guard refusal of a LOCAL tool), `SystemExit` (`_render_qa`'s
QA-FAIL exit), `Abort`/`KeyboardInterrupt`, or unhandled crashes — exactly
the runs an audit log most needs. A result-callback implementation would
have recorded only successes, silently, and `evaluate-readiness` /
`portfolio-metrics` would have kept reading a log with no failure signal.

## Decision

Record via a `RecordingCommand` / `RecordingGroup` class pair in `cli.py`,
wired through Click's own class cascade:

- `RecordingGroup.command_class = RecordingCommand` — in Click 8.4.1,
  `Group.command()` injects `command_class` as `cls` whenever the decorator
  passes no explicit `cls` kwarg (`click/core.py:1765-1766`).
- `RecordingGroup.group_class = type` — the documented self-propagation
  sentinel: `Group.group()` resolves `group_class is type` to `type(self)`
  (`click/core.py:1814-1818`), so subgroups (`envmon`, `agol`, ...) are
  themselves RecordingGroups and their leaves record too.
- `cli.py` has zero explicit `cls=` kwargs, so changing the ONE root-group
  line to `@click.group(cls=RecordingGroup)` covers all ~105 leaf commands.
  No individual command registration changes.

`RecordingCommand.invoke` overrides `Command.invoke`, which runs *after*
argument parsing — `--help` and bad-argument UsageErrors never reach it —
but wraps execution, so every exit path is caught and re-raised unchanged:

| Exit path | Recorded status |
|---|---|
| Clean return | `success` |
| `click.exceptions.Exit` / `SystemExit` with falsy code | `success` |
| `click.exceptions.Exit` / `SystemExit` with truthy code | `error` |
| `click.UsageError` | *(no record — parse-time failure, not a run)* |
| `KeyboardInterrupt` / `click.Abort` | `cancelled` |
| `click.ClickException` (e.g. runtime guard), any other exception | `error` |

An exit-0 run with QA warnings records `success`: `evaluate_readiness`
(core) treats any status != "success" as not-ready, and a run that passed
its own `--fail-on` policy must not be flagged not-ready.

Supporting choices:

- **QA counts via `ctx.meta`.** `_render_qa` stashes
  `qa.counts_by_severity()` under `autogis.qa_counts`; `Context.meta` is
  one dict shared across the whole context tree, so the leaf command's
  hook reads it directly. Severity keys are `INFO`/`WARNING`/`ERROR`;
  `CRITICAL` is deliberately not folded into the error count, matching
  `_log_promotion`'s convention (`autogis/core/agol/promote.py:142-144`).
- **`AUTOGIS_RUN_HISTORY` env var.** A path overrides the destination; the
  literal `off` disables recording. `tests/conftest.py` sets `off`
  autouse-wide so the ~1.5k existing CliRunner-driven tests don't litter
  `run_history.csv` files; recorder tests re-point it at a tmp path.
- **Default path `Path.cwd() / "run_history.csv"`** — matches the existing
  readers (`evaluate-readiness`, `portfolio-metrics`, `run-history show`)
  and `agol promote`'s `--run-history` default.
- **One-entry skip-list `{"promote"}`.** `agol promote` self-logs a richer
  record (rows_copied, promotion_status) via `_log_promotion`; the hook
  skipping it prevents the double-logging ADR-0050 item 6 warned about.
  Generalize only when a second self-logging command exists.
- **Best-effort.** `_record` swallows its own exceptions and the hook never
  alters exit codes or return values; observability must never break or
  change the CLI itself. `inputs` are sanitized through
  `json.dumps(..., default=str)` first because `run_history._encode`
  json-encodes with no `default=` — one unserializable param (Path, date)
  would otherwise silently drop the whole record.

### Amendment note

This ADR corrects ADR-0050 item 6's mechanism *wording* only; the decision
itself — record every run at the CLI adapter seam — stands and is
implemented here. See [ADR-0050](0050-unified-gui-adapter-direction.md).

## Consequences

### Positive consequences

- Every CLI invocation — console script, CliRunner tests, GUI subprocess
  launches — now feeds `evaluate-readiness` and `portfolio-metrics`, which
  previously read a log with a single writer (`agol promote`).
- Failure exits (guard refusals, QA FAILs, crashes) are recorded, which a
  result callback would have missed entirely.
- One-line registration: future commands added under the root group record
  automatically, with no per-command wiring to forget.

### Negative consequences

- Every CLI run in a directory without `AUTOGIS_RUN_HISTORY` set appends to
  `./run_history.csv` — a new side-effect file users may not expect.
  Accepted: it is the documented default the readers already assume, and
  the env var opts out.
- `ctx.params` are recorded as inputs stringified via `default=str`; exact
  round-tripping of rich types is not guaranteed. Accepted: the log is an
  audit trail, not a replay mechanism.
- An exit-0 run with warnings is `success`, so warning-tolerant runs are
  indistinguishable from clean ones in the status column (the
  `qa_count_warning` column still carries the signal).

## Alternatives considered

1. **`result_callback` on the root group** (ADR-0050's wording). Rejected:
   fires only on clean returns; misses every exception exit (see Context).
2. **Per-command decorator or explicit wrapper in each command body.**
   Rejected: ~105 call sites to keep in sync, exactly the drift the class
   cascade avoids.
3. **Workflow executor as sole writer.** Already rejected by ADR-0050
   (its own first-draft mistake, reversed by adversarial review).
4. **Folding `CRITICAL` into `qa_count_error`.** Rejected to stay
   consistent with `_log_promotion`'s existing convention; revisit if a
   reader ever needs it.

## Related decisions

- [ADR-0050: Unified GUI adapter direction](0050-unified-gui-adapter-direction.md)
  — item 6 is the decision this ADR implements and whose wording it corrects.
- [ADR-0017: CSV-based append-only run history log](0017-run-history-csv-log.md)
  — the schema and deferred write-side hook this ADR finally wires.
- [ADR-0051: Run-history msvcrt sentinel lock](0051-run-history-msvcrt-sentinel-lock.md)
  — the concurrency-safe write path that makes a fire-on-every-invocation
  writer safe (ADR-0050 item 5).

## Issues/PRs

- Implementation: `feat/cli-run-history-recording` (draft PR against main).
