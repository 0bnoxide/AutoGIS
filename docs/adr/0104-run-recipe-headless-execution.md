# ADR-0104: Headless `run-recipe` execution (Phase 5, slice 2)

**Status:** Accepted

**Date:** 2026-07-22

## Context

Phase 5 slice 1 (ADR-0103) shipped the core recipe schema + `validate-recipe`.
The Phase 5 gate also requires that recipes be **repeated deterministically**.
The GUI already has the execution engine — `WorkflowRunner` (`gui/runner.py`)
drives a `Workflow` of `Step`s one child process at a time — and, importantly,
`gui/runner.py` and `gui/executor.py` import cleanly without PySide6 (verified),
so that engine can be reused headlessly.

## Decision

Add a headless `envmon run-recipe` CLI that reuses the existing runner, plus a
small mapping module — **without editing the GUI files** the GUI workstream owns:

- New adapter module `autogis/adapters/recipe_workflow.py`:
  `recipe_to_workflow(data)` maps a validated recipe dict to a runnable
  `Workflow` (list `command` → tuple; `command: null` → `Step.command=None`
  review checkpoint). It lives in the adapter layer (it depends on the GUI
  `Workflow`/`Step`), so **both** this CLI and the future GUI save/load reuse one
  mapping and the recipe format never drifts from the runtime objects. Core is
  untouched (no core→adapter dependency).
- New `envmon run-recipe PATH [--job-root] [--local-python] [--timeout]
  [--continue-through-review]` CLI: load+validate → map → drive `WorkflowRunner`
  step by step, reporting each decision. It **stops at a review checkpoint**
  (`PAUSE_FOR_REVIEW`) unless `--continue-through-review` is given. `run_step`
  failures (`TimeoutExpired` / `ValueError` for a LOCAL step missing
  `--local-python` or a bad command / `OSError`) are caught and reported; the
  runner is already `HALTED`.
- **Exit codes:** 0 done, 1 halted/errored, 2 paused-for-review, 130 cancelled —
  stable codes for automation.

## Consequences

- Recipes can now be run and repeated deterministically from the CLI, closing
  most of the Phase 5 gate ahead of the GUI save/load wiring.
- 4 arcpy-free tests (field mapping; stop-at-checkpoint exit 2;
  continue-through-review → done exit 0; bad recipe → clean error). The
  subprocess execution path itself stays covered by `test_gui_executor.py`;
  these tests use review-checkpoint steps to exercise the loop without spawning
  processes. Full headless suite green.
- Registered `run-recipe` in `capabilities._REGISTRY_SEED` (CLOUD — the
  orchestrator is arcpy-free; individual steps carry their own arcpy needs via
  `--local-python`).
- **Deferred:** the GUI save/load wiring (would reuse `recipe_to_workflow` and a
  future `workflow_to_recipe`), and the example monitoring-event / RTK-to-CAD
  recipes.

## Notes

Numbered ADR-0104 against `origin/main` (merged: 0100, 0102, 0103) **and** all
open PRs (#280 → 0099, #281 → 0101) — 0104 is next free. Built autonomously under
the standing "continue roadmap development" goal; judgement in
`docs/adr/logs/2026-07-22-agent-decisions.md`.
