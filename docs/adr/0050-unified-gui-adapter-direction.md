# ADR-0050: Unified GUI — standalone PySide6 adapter, v1 includes workflow wiring, CLI-seam run-history with concurrency-safe writes

**Status:** Accepted

**Date:** 2026-07-04

## Context

`docs/superpowers/specs/2026-07-03-unified-gui-planning.md` opened the
post-roadmap "unified GUI" planning chapter: tying the ~105 CLI commands
together behind one GUI, with generalized workflow/pipeline wiring between
tools (`FullPipeline`, Tool 7, generalized). That doc laid out six open
questions rather than deciding anything, after two Fable review passes (a
quick direction check, then a full adversarial architectural review that
corrected four HIGH-severity issues in the first draft — see that doc's
appendix). The user answered all six questions directly in conversation on
2026-07-04. This ADR records those decisions; no code has been written yet.

## Decision

1. **Audience: existing ArcGIS Pro users only.** Not field staff, PMs, or
   clients without a Pro seat. This removes the two-tier capability UX
   problem the planning doc raised (§2.1) — every user of this GUI already
   has arcpy available via a licensed Pro install.

2. **Where it runs: a standalone app, added as a new adapter in this same
   repo** — not a `.pyt` toolbox extension, not a new ArcGIS Pro SDK (.NET/
   C#) add-in, and **not a fork or a separate repository**. It lives
   alongside `adapters/cli.py` and `adapters/toolbox.pyt` as a fourth adapter
   over the same `autogis/core`, matching the existing "three adapters, one
   core" shape. A literal fork (or a separately-versioned repo carrying its
   own copy of the core) was explicitly considered and rejected: it would
   recreate, at the repo level, the exact code-divergence problem
   ADR-0006 rejected at the command level ("dual execution paths lead to
   code divergence and bugs... single path is clearer and more
   maintainable"). New tools shipped to `core`/`cli.py` in the future must
   be usable from the GUI without a manual port step.

3. **Framework: PySide6/PyQt.** Chosen over Tkinter (stdlib, but rated
   "less polished" for a persistent multi-tab hub by the prior planning
   pass in `docs/candidates/boring-survey-drone-level-automation-roadmap.md`
   §3.2) and NiceGUI/Streamlit (browser-based, needs a local server process,
   and that same prior doc separately flags Streamlit as less suited to
   ArcGIS-adjacent workflows). The audience (technical Pro-seated analysts,
   already comfortable installing this package via `pip install -e .`) can
   absorb a real desktop-toolkit dependency, and the workflow-builder
   ambition (item 4) needs a toolkit built for complex multi-pane UIs, not
   one that fights it.

4. **v1 scope includes both the tool launcher and the workflow/pipeline
   builder together** — not launcher-first with the builder deferred to a
   V2, as the planning doc's own tentative lean suggested. The workflow
   model generalizes `FullPipeline`'s hardcoded chain (ordered tool steps,
   `job_queue.py`'s CLOUD→HYBRID→LOCAL ordering, a halt-on-QA-fail gate, and
   a "pause for human review" step type modeled on `FullPipeline`'s
   deliberate stop-before-export).

5. **Concurrent use is real and must be designed for in v1, not deferred.**
   Multiple analysts can work the same project/site concurrently over
   shared/networked files (the same GDB, the same project folder). This
   means the known unlocked-CSV-append race in `run_history.py` (no file
   lock, no cross-process cache invalidation) is a live bug the moment the
   CLI-seam writer (item 6) starts firing on every invocation, not a
   theoretical one — it must be closed (a file lock, or serializing writes
   through a small local mechanism) as part of this work, not left for
   later.

6. **Run-history writes are hooked at the CLI adapter seam** (`cli.py`),
   covering every invocation regardless of caller — GUI-launched, scripted,
   or a human at a terminal — per the 2026-07-01 architecture review's H1
   recommendation. This was chosen over making the (now in-scope, per item
   4) workflow executor the sole writer: that design was this planning
   chapter's own draft mistake, caught by the adversarial review, because it
   would create two audit-log philosophies (GUI-run history vs.
   everything-else-unlogged) and double-log `agol promote`, which already
   self-logs via `_log_promotion`. The CLI-seam callback needs the
   concurrency-safe write path from item 5 to be correct under concurrent
   use.

## Consequences

### Positive

- No new repository, no dependency-drift risk, no divergent copy of `core`
  to keep in sync — the GUI adapter automatically gains every tool shipped
  to `cli.py`/`core` going forward, the same way `.pyt` does today.
- Fixing the run-history write path at the CLI seam (item 6) has value
  independent of the GUI: `evaluate-readiness` and `portfolio-metrics`
  currently read a log that's almost entirely empty (one caller,
  `agol promote`) and will start working correctly for *all* CLI usage, not
  just GUI-launched runs.
- PySide6 and "launcher + workflow builder together" both point at building
  the more ambitious version once, rather than a smaller v1 that gets
  rebuilt when the workflow builder turns out to need a different
  foundation than the launcher assumed.

### Negative / accepted trade-offs

- v1 is larger than the planning doc's own lean (launcher-only first) —
  more design surface (the executor, the pause-for-review step semantics, a
  workflow save/reuse format) has to be gotten right before anything ships,
  rather than validating the launcher alone first. Accepted: the user's
  explicit call, weighed against re-architecting the launcher later if the
  workflow builder needed a different shape.
- Solving concurrent-write safety in v1 (item 5) is real, non-trivial scope
  (file locking or a serialization mechanism, plus whatever it takes to test
  that safely) that a single-user assumption would have avoided entirely.
  Accepted: the alternative (ship it single-user-only, discover the race in
  production once two analysts hit the same project) is worse.
- This adapter is standalone-desktop-only; it does not reach anyone without
  an ArcGIS Pro seat. Explicitly out of scope per decision 1 — revisit only
  if the audience assumption changes.

## Alternatives considered

1. **Grow the existing `.pyt` toolbox instead of a new adapter.** Rejected
   for the workflow-builder ambition: `.pyt` script tools are inherently
   modal (pick params, run, read messages, done) and cannot host a
   persistent multi-tab hub with a live job list, which is what "launcher +
   workflow builder" implies. Also inherits a documented weakness (the
   2026-07-01 architecture review's M2 finding: undertested inline
   marshalling in most envmon `.pyt` tools) that would compound under added
   orchestration logic.
2. **A new ArcGIS Pro SDK (.NET/C#) add-in for a persistent dockable pane.**
   Rejected: a new language/toolchain for this project, already precedent-
   rejected once for a different feature
   (`docs/repo-integration-roadmap.md:37`, "wrong language & runtime for a
   Python framework"). A standalone PySide6 app running alongside Pro
   delivers the same "persistent hub" UX in pure Python.
3. **Fork the repository (or a new repo depending on `autogis` as a
   package) to house the GUI.** A literal fork was rejected outright (see
   decision 2). A dependency-based separate repo was considered as a
   cleaner variant (no code divergence, GUI's heavier UI deps stay out of
   the core package's footprint) but rejected in favor of the simplest
   option: no new repo to version, release, or keep in sync at all, since
   the core package's dependency footprint concern doesn't yet justify the
   overhead of a second repo.
4. **Launcher-only v1, workflow builder deferred to V2** (the planning
   doc's own tentative lean). Rejected by explicit user decision — see
   decision 4.
5. **Executor-as-sole-run-history-writer.** This was the planning doc's own
   first-draft position, caught and reversed by the adversarial Fable
   review before this ADR — see decision 6 and that review's finding H3.

## Related decisions

- `docs/superpowers/specs/2026-07-03-unified-gui-planning.md` — the full
  architecture recap, brainstorm, and both Fable review passes this ADR's
  decisions resolve. Read first for the reasoning trail.
- [ADR-0006: .pyt toolbox as primary UI for LOCAL tools](0006-pyt-toolbox-as-primary-ui.md)
  — the code-divergence precedent decision 2 applies at the repo level.
- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
  — documents the 4 tool families that stay unreachable from any adapter,
  including this new one, until separately reopened.
- [ADR-0017: CSV-based append-only run history log](0017-run-history-csv-log.md)
  — the schema decision 6 builds the write-hook on top of; its deferred-write
  status is what decision 6 finally closes.
- `docs/reviews/fable-architecture-review.md` — finding H1 (unwired
  run-history) and finding M2 (undertested `.pyt` marshalling), both cited
  above.
- `docs/candidates/boring-survey-drone-level-automation-roadmap.md` §3 —
  prior GUI planning (framework comparison, "Project Automation Hub"
  concept) that decisions 3 and 4 draw on directly.
- [ADR-0053: CLI-seam run recording via RecordingCommand/RecordingGroup](0053-cli-seam-run-recording-recording-command.md)
  — implements item 6 and corrects its mechanism wording: a plain result
  callback fires only on clean returns; the shipped hook wraps
  `Command.invoke` so exception exits (guard failures, QA FAIL SystemExit,
  crashes) are recorded too.

## Issues/PRs

- Planning: PR #144 (`docs/superpowers/specs/2026-07-03-unified-gui-planning.md`)
- This decision: recorded here, implementation not yet started.
