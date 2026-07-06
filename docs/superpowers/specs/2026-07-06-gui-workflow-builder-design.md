# Unified GUI — workflow builder (v1) design

**Status:** implemented (2026-07-06), ADR-0062. **Date:** 2026-07-06.
**ADR:** 0062 (renumbered from 0061 — collided with open PR #174).

## Context

The GUI adapter's toolkit-free backend is complete and tested, and its
PySide6 window now runs **one** headless command at a time: pick a command,
fill its form, Run, see the result (`Decision`/`Reason`/stdout/stderr + a QA
table, ADR-0057 + ADR-0059) with Browse buttons and help text (ADR-0060,
PR #172). The multi-step **engine** is also already built and tested —
`WorkflowRunner` (ADR-0055) drives an ordered `Workflow(name, steps)` through
`advance()`, one step per call, with a full state machine
(`PENDING → RUNNING → PAUSED/DONE/HALTED/CANCELLED`) and thread-safe
`cancel()`/`resume()`. It already accepts `local_python`, so LOCAL-tool
support later is a parameter, not a rewrite.

What is missing is the **authoring + driving UI**: a way to assemble several
steps into a `Workflow` and run them end to end, watching per-step progress
and handling pause/halt. This is ADR-0050 decision 4 ("workflow/pipeline
builder"), the generalization of `FullPipeline`'s hand-built import→QA→export
chain with its deliberate stop-before-export human-review breakpoint. This is
the "V2" milestone the planning doc
(`2026-07-03-unified-gui-planning.md` §2.4) said to build "once the launcher
is proven" — which it now is.

## Scope decisions (v1)

Settled with the user before design:

1. **In-session only — no persistence.** Build a workflow, run it, watch it;
   it is gone when the window closes. Save/load (and the reuse *format*
   ADR-0055 deferred) is a separate, later slice.
2. **Grow the existing window; do not split into a tab.** The same command
   combo + form configures each step. The proven single-tool **Run** stays for
   one-off runs. This reuses *all* existing plumbing — form rendering,
   `build_step`, the QA table, `_StepWorker`, the result panes — instead of
   duplicating any of it.
3. **Gate level 2:** automatic **HALT** (a failing step stops the workflow,
   displayed), a **Cancel** button (stop between steps), and a per-step
   **"pause on warning"** checkbox → the workflow **PAUSES** and offers
   **Resume**/**Cancel** when that step finishes with warnings. This exercises
   the runner's entire state machine. Explicit "review checkpoint" steps
   (`Step(command=None)`) and auto CLOUD→HYBRID→LOCAL ordering are deferred.
4. **Headless commands only** (same `_headless_forms()` filter). LOCAL-tool
   support is the *next* slice; the runner already takes `local_python`.

## Architecture

**Everything lives in `app.py` (`MainWindow`).** No new toolkit-free module is
needed — `Workflow`, `WorkflowRunner`, `Step`, `build_step`, and `_show_qa`
all exist. This slice is widget wiring plus **one** refactor.

### The one refactor: generalize the drive from one-step to a loop

Today the drive is single-shot and two responsibilities are fused in
`_join_worker`:

- `_on_run` builds a 1-step `Workflow`, a `WorkflowRunner`, one `_StepWorker`.
- `_StepWorker.run()` calls `runner.advance()` once and emits
  `finished_result`/`failed`.
- `_on_result`/`_on_failure` call `_join_worker()`, which **joins the thread
  AND `shutil.rmtree`s the job dir**, then re-enable Run and render the result.

Generalize to **"advance until the runner is terminal or paused":**

- Split `_join_worker` into `_join_worker()` (thread `.wait()` only, run after
  *every* step) and `_finish_workflow()` (rmtree the shared job dir + reset
  run state + re-enable authoring, run **only** on a terminal/paused stop).
- `_on_result(result)` becomes the **dispatcher**: join the thread, render
  *this* step's result (status + QA table + stdout, reusing today's code) and
  mark its row in the Steps list, then switch on `self._runner.status`:
  - `PENDING` → spawn the next `_StepWorker` for the next step (the loop).
  - `PAUSED` → stop; show "PAUSED at step N"; enable Resume + Cancel.
  - `HALTED` → stop; "HALTED at step N: <reason>"; leave the failing step's
    QA table visible; `_finish_workflow()`.
  - `DONE` → "Workflow complete"; `_finish_workflow()`.
  - `CANCELLED` → "Cancelled"; `_finish_workflow()`.
- The single **Run** button becomes "run a 1-step workflow through this same
  loop" — identical observable behavior to today (one advance → terminal), no
  second code path.

The job dir is shared across steps (`WorkflowRunner` already namespaces each
step as `job_root/step_NN`), so cleanup must move from per-step to
workflow-end — exactly what the `_join_worker` split accomplishes.

### New `MainWindow` state

- `self._steps: list[Step]` — the assembled workflow (in memory), the single
  source of truth. The `QListWidget` rows mirror it (display text derived at
  Add time); reorder/remove mutate both in lockstep, so no parallel summary
  list is kept.
- `self._runner: WorkflowRunner | None` — the active run (None when idle).
- Reused: `self._worker` (`_StepWorker`, now re-spawned per step),
  `self._job_root`.

## UI additions (Option A layout)

Under the existing form/Run row, in order:

- **`+ Add to workflow`** button and a **"pause on warning"** `QCheckBox`
  (its state is read at Add time into the new `Step`).
- **Steps** `QListWidget` (`self._step_list`) — one row per step, summary =
  command label + a short arg hint + a `[pause-on-warn]` tag. Selecting a row
  enables the management buttons.
- **Remove**, **↑**, **↓** buttons — remove selected, move up, move down
  (manual ordering; no auto CLOUD→HYBRID→LOCAL sort in v1).
- **Run workflow** and **Clear** buttons.
- **Cancel** button — visible/enabled only while a workflow is running;
  **Resume** — visible/enabled only when `PAUSED`.

The status label, QA table, and stdout pane are **shared**: during a workflow
they show the *current* step's result as each completes.

## Data flow

`+ Add to workflow` → `build_step(form, raw_values)` (reused; a
`FormValidationError` shows inline and the step is **not** added) → append the
`Step` (with `pause_on_warning` from the checkbox) to `self._steps`, append a
summary row to the list.

`Run workflow` → `Workflow("gui-workflow", tuple(self._steps))` →
`WorkflowRunner(workflow, mkdtemp())` → disable authoring, show Cancel, spawn
the first `_StepWorker`. The drive loop above carries it to a terminal/paused
stop.

`Resume` → `runner.resume()` → spawn the next `_StepWorker`.
`Cancel` → `runner.cancel()` (applies immediately if idle/paused; after the
current step finishes if one is in flight — the runner's documented limit) →
the loop observes `CANCELLED` and stops.

## Error handling / edge cases

- **Invalid form on Add** → inline `FormValidationError`, no step added.
- **Run workflow with 0 steps** → the button is disabled until ≥1 step exists.
- **Worker exception** (`_on_failure`): `advance()` already sets HALTED or
  CANCELLED in its `except` block, so the runner is left terminal; render the
  message, `_finish_workflow()`.
- **`closeEvent`:** refuse while a step is in flight (unchanged — the
  documented can't-force-kill limitation). When idle or `PAUSED` (no thread
  running), allow close and clean up the job dir. A `PAUSED` workflow simply
  discards on close (in-session only, by decision 1).
- **Add during a run** is prevented: authoring controls are disabled while a
  workflow runs.

## Testing (offscreen Qt, real widgets, `run_step` monkeypatched)

Following the suite's convention (`run_step` stubbed to return per-call
results; `test_gui_executor.py` owns real subprocess correctness):

- Add appends to the list; an invalid form shows the inline error and adds
  nothing.
- Remove / ↑ / ↓ reorder `self._steps` and the list in lockstep.
- A 2-step all-`CONTINUE` workflow drives both and ends `DONE`; both steps'
  rows are marked done; the last step's result shows.
- A mid-workflow `HALT` stops the run — the later step's `run_step` is never
  called (asserted via a call counter).
- A `pause_on_warning` step → `PAUSED`; **Resume** advances the next step;
  **Cancel** ends the run.
- **Single Run still works** (1-step workflow through the shared loop) — the
  existing single-run tests must stay green unchanged.
- Cancel while running → the run ends `CANCELLED` after the in-flight step.

## Out of scope (deferred, by decision)

Persistence/save-load; explicit review-checkpoint steps; auto
CLOUD→HYBRID→LOCAL ordering; LOCAL (arcpy) tools + a `local_python` picker
(the next slice); any per-step live progress (job-level status only, per the
planning doc).

## Verification beyond tests

Offscreen tests certify structure/wiring, not appearance — a human must run
`autogis-gui`, build a 2-step headless workflow (e.g. `validate-rtk-survey`
then another headless command), and confirm the run drives, pauses, and halts
as shown. Recorded as an explicit outstanding item in the ADR, as with every
widget slice this chapter.
