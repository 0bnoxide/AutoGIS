# ADR-0062: GUI workflow builder (v1) — assemble and run multi-step headless workflows over WorkflowRunner

**Status:** Accepted

**Date:** 2026-07-06

## Context

The GUI window ran **one** headless command at a time (ADR-0057 walking
skeleton + ADR-0059 QA table + ADR-0060 Browse/help). The multi-step
**engine** — `WorkflowRunner` (ADR-0055), which drives an ordered
`Workflow(name, steps)` through `advance()` with a
`PENDING→RUNNING→PAUSED/DONE/HALTED/CANCELLED` state machine and thread-safe
`cancel()`/`resume()` — already existed and was tested, but had no
authoring or driving UI. This is ADR-0050 decision 4's workflow/pipeline
builder, the generalization of the `.pyt` `FullPipeline`'s hand-built
import→QA→export chain (with its deliberate stop-before-export human-review
breakpoint), and the "V2" milestone the planning doc
(`2026-07-03-unified-gui-planning.md` §2.4) said to build once the launcher
was proven.

Scope was settled with the user before any code
(`docs/superpowers/specs/2026-07-06-gui-workflow-builder-design.md`):
**in-session only** (no persistence), **grow the window** (not a separate
tab), **gate level 2** (HALT + Cancel + per-step pause-on-warning),
**headless commands only**.

## Decision

1. **Everything lives in `app.py` (`MainWindow`)** — no new toolkit-free
   module. `Workflow`, `WorkflowRunner`, `Step`, `build_step`, and the
   ADR-0059 `_show_qa` table are all reused.

2. **One refactor: generalize the single-shot drive into an
   "advance-until-terminal/paused" loop** shared by both single **Run** (a
   1-step workflow) and **Run workflow**. `_join_worker` is split into
   thread-join (`_join_worker`, after *every* step) and cleanup
   (`_finish_run`, job dir + re-enable authoring, at workflow **end** only) —
   the job dir is shared across a workflow's steps (`job_root/step_NN`), so it
   must survive until the run ends. `_on_result` is the dispatcher: advance
   the next step while `PENDING`; stop on `PAUSED`/`DONE`/`HALTED`/`CANCELLED`.

3. **Single Run keeps today's exact behavior** (the decision-label status,
   "CONTINUE"/"HALT") via a `_run_is_workflow` guard. The same guard scopes
   the per-step row glyphs (✓/⏸/✗) and the run-level status messages
   ("Workflow complete" / "HALTED at step N" / "PAUSED after step N" /
   "Cancelled") to **workflow** runs only — a single Run is observably
   identical to before this change.

4. **Authoring UI (grow-window, Option A):** `+ Add to workflow` (validated by
   `build_step`; an invalid form shows an inline error and adds nothing), a
   per-step **pause on warning** checkbox (→ `Step.pause_on_warning`), a Steps
   `QListWidget` mirroring `self._steps` (the single source of truth), and
   Remove / ↑ / ↓ / Clear. Step-list buttons enable only when idle **and**
   steps exist.

5. **Driving UI:** `Run workflow` / `Cancel` / `Resume`. `Cancel` applies
   immediately when idle or paused, and after the in-flight step otherwise
   (the runner's documented can't-force-kill limit, ADR-0055). `Resume`
   handles the pause-on-the-**last**-step edge, where `runner.resume()` goes
   straight to `DONE` — it finishes rather than advancing into a terminal
   runner. The shared status/QA/stdout widgets show the current step.

6. **Headless commands only** (the `_headless_forms()` filter is unchanged).
   The runner already takes `local_python`, so LOCAL-tool support is the
   **next** slice — a parameter, not a rewrite.

## Consequences

### Positive

- The entire `WorkflowRunner` state machine is now exercised through the UI
  (run-to-DONE, HALT-stops-later-steps, pause→resume, cancel), reusing the
  whole toolkit-free backend and the ADR-0059 QA table per step.
- Single Run is untouched in behavior — the refactor unified the code path
  without changing the proven single-tool UX or ADR-0060's Browse/help.
- No new dependency: `QListWidget` ships in the `gui` extra's PySide6.

### Negative / accepted trade-offs

- **Offscreen tests certify wiring, not appearance.** A human must run
  `autogis-gui`, build a real 2-step headless workflow, and confirm it drives,
  pauses, and halts as shown — recorded here as outstanding, as every widget
  slice this chapter.
- **No persistence** (a workflow is gone on window close), **no explicit
  review-checkpoint steps**, **no auto CLOUD→HYBRID→LOCAL ordering** — all
  deferred by decision. Persistence's save/reuse format is still ADR-0055's
  deferred design.
- `Cancel` cannot force-kill a step already in flight (ADR-0055's documented
  limit) — it takes effect once that step completes.

## Process notes

The `executing-plans` critical-review pass caught **four** control-flow bugs
in the plan *before* any code: `_on_cancel` from PAUSED never finishing the
run; `_on_resume` on a last-step pause advancing into a terminal runner;
`closeEvent` cleanup gated on `_worker is not None` (skipping a PAUSED run's
job-dir cleanup); and the dispatcher overwriting a single Run's decision-label
status with a workflow message. All were fixed in the plan and implemented
correctly.

Renumbered **0061 → 0062**: open PR #174 already claimed 0061
(`0061-drone-geotech-graphics-tool-batch.md`) — the chapter's recurring
ADR-numbering collision. Checked `docs/adr/` **and** every open PR's files
before settling on 0062.

## Alternatives considered

1. **A separate "Workflow" tab** — rejected: duplicates the form-rendering and
   QA-display plumbing across two places.
2. **Unify by dropping the single Run** (every run is a workflow) — rejected:
   it would change the single-tool UX the user just validated and ADR-0060 was
   polishing. Keeping Run, backed by the same 1-step-workflow loop, gets the
   unification without the disruption.
3. **Two separate drive paths** for single vs. workflow — rejected: the
   advance-until-terminal loop models both; a single Run is just a 1-step
   workflow.
4. **Persistence in v1** — deferred: ADR-0055 already deferred the save/reuse
   format design; an in-session builder proves the chain with the least code.

## Related decisions

- [ADR-0055](0055-gui-workflow-runner-thread-boundary.md) — the
  `WorkflowRunner` this UI drives; source of the `advance`/`pause`/`resume`/
  `cancel` surface and the can't-force-kill limit.
- [ADR-0057](0057-gui-walking-skeleton.md) — the single-command window and the
  `_StepWorker` QThread bridge this generalizes.
- [ADR-0059](0059-gui-qa-results-table.md) — the QA table reused per step.
- [ADR-0060](0060-gui-window-polish-browse-help.md) — the window this grows.
- [ADR-0050](0050-unified-gui-adapter-direction.md) decision 4 — the workflow
  builder direction this implements.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/app.py` (the
  drive-loop refactor + authoring/driving UI) and `tests/test_gui_app.py`
  (11 new offscreen tests). Spec + plan under `docs/superpowers/`.
