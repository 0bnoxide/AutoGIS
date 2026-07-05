# ADR-0053: GUI executor QA signal — exit code + injected CSV report; JSON summary status and stdout rejected as gating inputs

**Status:** Accepted

**Date:** 2026-07-04

## Context

ADR-0050's v1 scope includes the workflow builder: ordered tool steps with a
halt-on-QA-fail gate and a "pause for human review" step type. The executor
that runs one step needs a per-step signal: did this command's run HALT the
workflow, CONTINUE, or should it PAUSE_FOR_REVIEW?

The child process's exit code alone cannot carry that signal:

- `0` means QA PASS **or** warnings-under-threshold — `_render_qa`
  (`adapters/cli.py`) only raises on FAIL, computed as
  `qa.status(allow_warnings=(fail_on != "warning"), allow_errors=False)`.
- `1` means QA FAIL, **or** a runtime-guard refusal
  (`click.ClickException`, exit code 1), **or** a direct business failure,
  **or** an unhandled crash.
- `2` is Click's own `UsageError` — bad arguments, a pre-flight/config
  problem rather than a tool failure.

Three candidate side channels exist: the QA CSV report (per-record rows),
the QA JSON summary (counts + a `"status"` field), and stdout.

## Decision

1. **`autogis/adapters/gui/executor.py` — pure logic + `subprocess`.** No
   GUI toolkit, no arcpy import, same scoping discipline as the ADR-0052
   introspector. It writes **no run-history records**: the child process
   goes through the CLI adapter seam, which is the recording hook per
   ADR-0050 decision 6 — recording here would double-log every GUI run.

2. **Child invocation is `<python> -m autogis.adapters.cli <path> ...`** —
   the same click group the `autogis` console script targets (pyproject
   `[project.scripts]`). Using `-m` with an explicit interpreter makes the
   environment a deliberate choice instead of a PATH lookup: CLOUD/HYBRID
   tools run under `sys.executable`; LOCAL (arcpy) tools require a
   caller-supplied `local_python` (the `python.exe` of an arcgispro-py3
   clone — never hardcoded). Runtime classification comes from
   `capabilities.TOOLS` via a leaf-first path lookup (so
   `manage-callout-overrides lock` resolves through its group); unknown
   names default to the headless env because the CLI's own runtime guard is
   the backstop and refuses cleanly.

3. **The QA channel is an executor-injected `--report <job_dir>/qa.csv`**,
   added only when the command declares the shared `--report` option
   (detected by param name, the same name `FormField.name` exposes);
   a step-configured `--fail-on` is passed through the same way. The CSV
   format specifically: it has per-record severity/category/message detail,
   and `_render_qa` writes it immediately before computing the pass/fail
   status, so on a QA-FAIL exit the file is guaranteed present. The
   executor owns the report path during workflow runs (a user-picked
   `report` value is overridden; copy qa.csv from the job dir if wanted
   elsewhere).

4. **Decision table** (`decide(exit_code, qa_csv, pause_on_warning)`):

   | Signal | Decision |
   |---|---|
   | exit != 0, qa.csv has WARNING+ rows | HALT — QA FAIL; rows are the reason |
   | exit == 2, no such rows | HALT — usage/config error; stderr is the reason |
   | exit != 0 otherwise | HALT — crash or guard refusal; stderr is the reason |
   | exit == 0, WARNING+ rows, step's `pause_on_warning` | PAUSE_FOR_REVIEW |
   | exit == 0 otherwise | CONTINUE |

   The QA-FAIL branch requires *blocking-capable* rows (WARNING or worse),
   not merely a non-empty file: only WARNING+ rows can flip `_render_qa`'s
   status to FAIL, so a nonzero exit with INFO-only rows is some other
   failure and stderr is the truthful reason.

5. **A checkpoint step type exists independently of QA content:**
   `Step(command=None, message=...)` runs no child process and always
   returns PAUSE_FOR_REVIEW — modeling `FullPipeline`'s (`toolbox.pyt`)
   deliberate stop-before-export, which prints "run Tool 6 per figure spec
   … so layouts can be reviewed first" and returns.

6. **The JSON summary's `"status"` field is rejected as a gating input.**
   `QACollector.write_json_summary` computes it as `self.status()` with
   *default* thresholds (`allow_warnings=True, allow_errors=False`),
   while the process exit code comes from `_render_qa`'s
   `status(allow_warnings=(fail_on != "warning"))`. Under
   `--fail-on warning` with WARNING records, the JSON says `PASS` while the
   process exits 1 — the two threshold computations genuinely diverge. The
   JSON also carries only counts, no per-record detail to render as a halt
   reason. **stdout is rejected too**: it is human-facing echo text with no
   stability contract.

7. **Scope: per-step decision logic + subprocess assembly only.** No
   workflow/DAG engine, no scheduling, no retry policy — the multi-step
   orchestrator is a separate future task that composes `run_step`.

## Consequences

- The workflow orchestrator gets a single, deterministic per-step verdict
  (`StepResult(decision, reason, exit_code, qa_rows, stdout, stderr)`) that
  is testable without arcpy: the tests drive a stub child script that
  writes its qa.csv through the real `QACollector.write_csv`.
- Gating is immune to the JSON-status threshold mismatch and to stdout
  format drift.
- Commands without the shared `--report` option gate on exit code alone
  (no warning-pause available for them) — accepted; the `qa_report_options`
  decorator is the single place the contract lives, and new QA-producing
  commands adopt it.
- `--fail-on` remains the child's own gate: the executor does not
  re-implement threshold logic, it only reads back what the child already
  decided plus the per-record detail.

## Alternatives considered

1. **Parse the QA JSON summary's `"status"`.** Rejected — decision 6: its
   threshold logic ignores `--fail-on`, so it contradicts the exit code in
   exactly the configuration (`--fail-on warning`) where a workflow gate
   matters most, and it has no per-record detail.
2. **Parse stdout.** Rejected — echo text for humans, fragile, no contract.
3. **In-process invocation (`CliRunner`) instead of a subprocess.**
   Rejected: LOCAL tools need a *different interpreter* (the Pro clone), and
   an in-process call would bypass the CLI-seam run-history hook
   (ADR-0050 decision 6) and let one tool's crash take down the GUI.
4. **A new machine-readable status contract (e.g. `--status-json` written
   by every command).** Rejected as over-build: the CSV report plus exit
   code already carry the needed signal; a new contract would touch every
   QA-producing command for no additional information.

## Related decisions

- [ADR-0050](0050-unified-gui-adapter-direction.md) — GUI direction; v1
  workflow scope and the CLI-seam run-history decision this defers to.
- [ADR-0052](0052-gui-introspection-layer.md) — the `CommandForm` /
  `FormField` descriptors whose param names drive the `--report`/`--fail-on`
  injection check.
- [ADR-0017](0017-run-history-csv-log.md) /
  [ADR-0051](0051-run-history-msvcrt-sentinel-lock.md) — the run-history
  write path that records the child invocations this executor launches.
- [ADR-0006](0006-pyt-toolbox-as-primary-ui.md) — the `.pyt` pipeline whose
  stop-before-export pattern the checkpoint step type generalizes.
