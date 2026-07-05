# ADR-0055: GUI workflow runner — single-flight advance/pause/resume/cancel, thread-boundary punted to the widget layer

**Status:** Accepted

**Date:** 2026-07-05

## Context

ADR-0053 (the per-step executor) explicitly scoped out the multi-step
orchestrator: "the multi-step orchestrator is a separate future task that
composes `run_step`." ADR-0050 decision 4 requires the workflow builder to
generalize `FullPipeline`'s ordered stages with a halt-on-QA-fail gate and a
pause-for-human-review step type (`toolbox.pyt`'s deliberate stop-before-export).
Both the introspector (ADR-0052) and the executor (ADR-0053) are toolkit-free
by design, with the actual PySide6 widget layer deferred to its own task.
This ADR covers that missing middle piece: something that drives a
`Workflow` (an ordered sequence of `Step`s) through `run_step` one at a time,
with pause/resume/cancel control — while a real GUI still doesn't exist to
validate against.

The one genuinely hard design question here: `run_step` is a **blocking**
call (`subprocess.run`, waits for the child to exit). A future Qt window
must not freeze while a step's process runs, which means *something* has to
put that blocking call on a background thread. But *how* — `QThread`,
`QRunnable` in a `QThreadPool`, a plain `threading.Thread`, an
`asyncio` bridge via `qasync` — is a decision that depends on the widget
layer's own event-loop and signal/slot design, which doesn't exist yet and
isn't this task's job to invent speculatively.

## Decision

1. **`autogis/adapters/gui/runner.py` — pure logic, no threading policy
   baked in, no GUI toolkit, no arcpy.** Same scoping discipline as
   ADR-0052/ADR-0053. `WorkflowRunner.advance()` is a single **blocking**
   call: it runs exactly one step and returns. The module does not spawn its
   own thread and does not import any toolkit.

2. **The thread-boundary decision is explicitly punted to the widget-layer
   task**, not solved here. What this module owns instead is everything that
   *any* threading mechanism needs to use `run_step` correctly from two
   threads at once:
   - A single internal `threading.Lock` guards all state (`status`,
     `results`, `next_step`) so a UI thread can read them, or call
     `cancel()`/`resume()`, while a worker thread is blocked inside
     `advance()`.
   - A single-flight guard: `advance()` raises if a step is already
     `RUNNING`, rather than silently racing two subprocesses.
   - `cancel()` and `resume()` are plain, thread-safe methods with no
     dependency on signals/slots or an event loop — whatever bridge the
     widget layer picks (a `QThread` emitting `Signal(StepResult)`, a
     `QRunnable` posted to a pool, a `concurrent.futures` executor) can wrap
     `advance()`/`cancel()`/`resume()` directly with no adapter shim needed.

3. **State machine:** `PENDING -> RUNNING -> {PENDING, PAUSED, HALTED,
   DONE, CANCELLED}`. `HALTED`/`DONE`/`CANCELLED` are terminal — no further
   `advance()`. `PAUSED` requires an explicit `resume()` before the next
   `advance()`; this is `FullPipeline`'s stop-before-export made resumable
   instead of terminal (a real workflow builder's checkpoint step should let
   a human continue after review, not force restarting the whole run).

4. **Cancellation cannot force-kill an in-flight step.** `run_step` blocks
   inside `subprocess.run`, which owns the child process until it exits — it
   does not expose a `Popen` handle a caller could terminate. So:
   - `cancel()` called while `PENDING` or `PAUSED` takes effect immediately.
   - `cancel()` called while `RUNNING` (another thread is mid-`advance()`)
     is recorded and applied the moment that step's `run_step` call returns
     — the in-flight step still completes and its `StepResult` is still
     recorded in `.results`, but the runner transitions straight to
     `CANCELLED` regardless of that step's own decision, and no further
     step launches. This is a deliberate, documented v1 limitation
     (`ponytail:` comment in the module), not a bug: force-kill would
     require changing `run_step`'s signature to expose `Popen` instead of
     blocking on `subprocess.run`, which nothing has asked for yet. If a
     hung LOCAL (arcpy) step turns out to need hard termination in
     practice, that is the upgrade path.

5. **Per-step job directories are `job_root/step_{index:02d}`**, assigned by
   the runner (not the caller), matching `run_step`'s existing
   reused-`job_dir` handling (ADR-0053's stale-`qa.csv` fix) — each step
   gets a fresh directory, so there is no stale-report risk to inherit here.

6. **No workflow save/reuse format, no persistence, no DAG/branching.** A
   `Workflow` is an in-memory ordered tuple of `Step`s; serializing a
   workflow definition to disk (the "save/reuse format" ADR-0050 decision 4
   anticipates) is a workflow-*builder* concern that belongs with the
   widget-layer task, once there is an actual authoring UI whose save format
   it should match. Building a serialization format speculatively, before
   any UI exists to produce or consume it, would be guessing at its shape.

## Consequences

### Positive

- The widget-layer task inherits a fully tested, thread-safe control
  surface and does not have to design (or debug) the advance/pause/cancel
  state machine itself — only wire it to whatever Qt threading primitive it
  picks.
- `advance()`'s single-blocking-call contract means the runner's own test
  suite needs no GUI toolkit and no real subprocesses beyond what
  `test_gui_executor.py` already covers — `run_step` is monkeypatched with
  canned `StepResult`s, plus one real `threading.Thread` test proving the
  lock-guarded surface is safe from a second thread, not just
  single-threaded-safe by accident.
- Punting the actual `QThread`-vs-`QRunnable`-vs-asyncio choice avoids
  building a bridge for an event loop that doesn't exist yet and might not
  match what the widget layer needs once it's designed against a real
  window.

### Negative / accepted trade-offs

- A hung or very long-running LOCAL step cannot be force-terminated from the
  UI in v1 — `cancel()` only prevents the *next* step from launching.
  Accepted: no requirement has surfaced for hard-killing arcpy subprocesses
  mid-run, and building that now would be speculative.
- No persisted workflow definitions yet — a user cannot save/reload a
  workflow template between sessions until the widget-layer task adds a
  format. Accepted: that format should be designed against the actual
  authoring UI, not guessed at here.

## Alternatives considered

1. **Have this module spawn and own a background thread itself (e.g. return
   a `Future`, or take a callback and manage a `threading.Thread`
   internally).** Rejected: this would bake in a threading policy the
   widget layer might not want (Qt code generally prefers driving its own
   `QThread`/`QRunnable` so results marshal back to the UI thread via
   signals rather than raw callbacks from an arbitrary thread) — safer to
   expose a synchronous, lock-safe `advance()` and let the widget layer own
   the bridge.
2. **Make `advance()` non-blocking / generator-based (`yield` after each
   step, driven by a scheduler).** Considered for a cooperative-cancellation
   story, but rejected as unnecessary complexity: `run_step` itself has no
   internal yield points (`subprocess.run` is atomic from this module's
   perspective), so a generator here would not gain finer-grained
   cancellation over the current call-`advance()`-from-a-thread shape — it
   would only add API surface.
3. **Design the exact Qt threading bridge now (`QThread` subclass, signals,
   etc.).** Rejected — that is the widget-layer task's job, and doing it
   without a real window to integrate against would be guessing; see
   Decision 2.
4. **Persist `Workflow`/run state to disk as part of this task (crash
   recovery, save/reuse).** Rejected as premature per Decision 6 — no
   authoring UI exists yet to define what should be saved or in what shape.

## Related decisions

- [ADR-0050](0050-unified-gui-adapter-direction.md) — GUI direction; v1
  workflow-builder scope (decision 4) this runner implements the execution
  side of.
- [ADR-0053](0053-gui-executor-qa-signal.md) — the per-step executor this
  runner composes via `run_step`; its own Scope section (item 7) named this
  orchestrator as the next task.
- [ADR-0052](0052-gui-introspection-layer.md) — `CommandForm`/`FormField`,
  the other toolkit-free layer a future workflow-builder UI will read from
  to let a user assemble the `Step`s this runner executes.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/runner.py`,
  `tests/test_gui_runner.py`.
