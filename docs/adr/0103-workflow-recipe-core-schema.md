# ADR-0103: Workflow-recipe core schema (Phase 5, slice 1)

**Status:** Accepted

**Date:** 2026-07-22

## Context

Production roadmap Phase 5 (ADR-0087) extends the existing GUI workflow builder
with save/load for linear YAML recipes. The GUI already models a run as
`Workflow(name, steps)` with `Step(command, values, fail_on, pause_on_warning,
message)` (`gui/runner.py`, `gui/executor.py`). Two constraints shape the first
slice:

1. **Governance line 21** — reusable behavior belongs in `autogis.core`; adapters
   consume it. Recipe save/load/validate is reusable, so it belongs in core.
2. **Invariants + coordination** — core must not import adapters, and the
   `autogis/adapters/gui/` files are owned by a separate, active workstream.
   Editing them (or importing `Step`/`Workflow` into core) would break the
   invariant and collide with that workstream.

Phase 4 (#280) is still open, so Phase 5 is started in parallel under the owner's
standing "continue roadmap development" directive.

## Decision

Ship the **GUI-agnostic core substrate only** and defer the GUI wiring:

- New arcpy-free module `autogis/core/common/workflow_recipe.py` defining the
  recipe as **pure data** whose field shape mirrors the GUI `Workflow`/`Step`
  model exactly, without importing it: `validate_recipe`, `load_recipe`,
  `dump_recipe` (`yaml.safe_dump(sort_keys=False)` for stable, diff-friendly
  order), `save_recipe`. Reuses `core.common.config.load_config` + `ConfigError`.
- Validation is strict (unknown-key rejection, `command` is null-or-`list[str]`,
  `fail_on ∈ {error,warning}`, version guard) so a malformed or future-version
  recipe fails loudly rather than mis-parsing.
- New headless `envmon validate-recipe PATH` CLI + a `capabilities._REGISTRY_SEED`
  entry, so recipes can be validated standalone (GUI-saved or hand-authored).

## Consequences

- The GUI later maps `Workflow ⇄ recipe dict` on top of `dump_recipe`/`load_recipe`
  — a 1:1 field translation (YAML list ⇄ tuple) — with **no core→adapter
  dependency** and no edit to the contested GUI files in this slice.
- 18 arcpy-free tests (round-trip, order preservation, null-command checkpoint,
  every rejection rule, CLI good/bad). Full headless suite green.
- **Deferred:** GUI save/load wiring, headless recipe execution, and the
  monitoring-event / RTK-to-CAD example recipes (the Phase 5 gate) — all land in
  the GUI-wiring slice that coordinates with the GUI workstream.
- **YAGNI (per roadmap):** branching, expression languages, output-binding DSL,
  internal scheduling.

## Notes

Spec: `docs/superpowers/specs/2026-07-22-workflow-recipe-core-design.md`.
Numbered ADR-0103 against `origin/main` (merged: 0100, 0102) **and** all open PRs
(#280 → 0099, #281 → 0101) — 0103 is the next free. Built autonomously under the
standing "continue roadmap development" goal with the owner unavailable;
judgement logged in `docs/adr/logs/2026-07-22-agent-decisions.md`.
