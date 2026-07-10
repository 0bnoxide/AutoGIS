# ADR-0073: GUI report copy-out, single-Run pause parity, and output colorization

**Status:** Accepted

**Date:** 2026-07-09

## Context

Three user-facing gaps in the GUI lower panel, all surfaced from one live
`envmon validate-rtk-survey` run (issue #205; RTK was only the repro vehicle —
none of this touches the RTK tool itself):

1. **The user's `--report` path was silently discarded.** For gating
   reliability, the executor injects its *own* `<job_dir>/qa.csv` on every
   command that declares `--report` (ADR-0053) — `build_argv` overrides any
   caller-supplied value. Nothing copied that qa.csv back to the path the user
   typed, and `_finish_run` then `rmtree`s the job dir, so the report wasn't
   merely misplaced — it was **deleted**. The executor docstring already
   *promised* copy-out ("copy qa.csv out of the job dir if it is wanted
   elsewhere") but nothing implemented it.

2. **The "pause on warning" checkbox was ignored by single Run.** It was read
   only by `_on_add_step` (workflow steps), never by `_on_run`. A user who
   checked it and pressed **Run** got a silent no-op — the Reason line even
   read `(pause_on_warning off)` under a checked box.

3. **The raw output/decision pane wasn't color-coded**, unlike the QA table
   beside it (#205 comment).

## Decision

**1. Copy-out in `run_step` (extends ADR-0053).** After `decide()`, if the
step carries a user `report` value, `_export_report()` copies the gating qa.csv
to that path (creating parents, to match `QACollector.write_csv`). It lives in
`run_step` — the single choke point for both single Run and workflow — so every
caller is covered. The copy is **unconditional on a `--report` value**: a HALT
still exports (the user wants the report regardless of QA verdict). A failed
copy is *surfaced, never raised* — it must not change the QA decision. Two new
`StepResult` fields keep success and failure distinguishable: `report_out`
(destination on success) and `report_error` (message on failure); the GUI
renders "Report saved to: …" / "Report NOT saved: …". The executor stays the
sole owner of the gating channel — copy-out is an additive duplicate, not a
redirect.

**2. Single Run honors pause-on-warning (extends ADR-0063).** ADR-0063 already
unified a single Run as a 1-step workflow through the same `WorkflowRunner`, so
the pause machinery existed and was merely gated off. `_on_run` now passes the
checkbox into `build_step`; `_start_run` resets Resume/enables Cancel for *any*
run; the `_on_result` PAUSED branch lights Resume for both paths. A single Run
that pauses now Resumes straight to DONE (last-step `resume()`), or is
cancelable. The prior "single Run has no Resume affordance / finish instead"
branch is removed.

**3. Output-pane colorization (UI polish).** `self._output` becomes a
`QTextEdit` rendered via `setHtml(_colorize_output(text))`. `_colorize_output`
escapes every line (arbitrary child stdout can't inject markup) and wraps the
whole in `<pre>` (keeps console monospacing / `[SEVERITY] category`
alignment), coloring each line by the first keyword it contains via an ordered
`_LINE_COLORS`: red (CRITICAL/ERROR/FAIL/HALT), orange (WARNING/PAUSE), blue
(INFO), green (CONTINUE/PASS) — per the user's blue-info/green-pass steer.
Order is precedence, so an INFO line ending "…QA pass." stays blue. This is a
**separate palette from `_SEV_COLOR`** (the QA table, where INFO stays gray);
the table is unchanged.

## Consequences

### Positive

- The typed `--report` path works again and is surfaced — closes the silent
  data-loss gap; behaves like the CLI's own `--report` (parents created).
- The pause-on-warning checkbox is honest for both Run and workflow steps.
- Decision/QA/error lines read at a glance; failure text is now escaped, not
  raw.

### Negative / limits

- Copy-out is best-effort: a HALT that crashed before writing qa.csv has
  nothing to copy (nothing surfaced) — acceptable, the run already halted.
- `<pre>` output doesn't soft-wrap long lines (horizontal scroll, console-like)
  — a `ponytail:` ceiling; revisit if a tool emits very wide lines.
- Visual rendering (do the colors read on both themes; does pause/Resume look
  right) is offscreen-uncertifiable per ADR-0057 — a human-QA follow-up issue.

## Alternatives considered

1. **Disable/annotate the `--report` field during runs** (#205 option 3):
   rejected — copy-out makes the field *functional*, strictly better than
   telling the user it does nothing.
2. **Copy-out in the GUI (`_on_result`) instead of the executor:** rejected —
   the executor is toolkit-free and unit-testable without Qt, and its docstring
   already promised the behavior; the GUI would only cover the GUI callers.
3. **Relabel the checkbox as workflow-only** (#205 C option): rejected by the
   user in favor of making single Run honor it.
4. **Extend `_SEV_COLOR` for the pane:** rejected — blue-info/green-pass
   diverges from the table's gray-info palette; a dedicated `_LINE_COLORS`
   keeps the table untouched.

## Related decisions

- Extends: ADR-0053 (executor owns the QA channel), ADR-0063 (single Run as a
  1-step workflow), ADR-0057 (offscreen tests certify wiring, not appearance).

## Issues/PRs

- Addresses: #205
