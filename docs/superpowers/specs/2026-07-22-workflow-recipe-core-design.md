# Saved workflow recipes — core schema (Phase 5, slice 1)

**Date:** 2026-07-22
**Phase:** Production roadmap Phase 5 (saved workflow recipes) — first slice
**Status:** Proposed (built autonomously under the standing "continue roadmap
development" goal; owner unavailable)

## Purpose

Phase 5 extends the existing GUI workflow builder with save/load for linear YAML
recipes. The **reusable substrate** — a serializable recipe format with
save/load/validate — belongs in `autogis.core` (roadmap governance line 21:
"reusable behavior belongs in autogis.core; adapters and notebooks consume it").
This slice ships that core substrate plus a headless CLI validator, and
**defers** the GUI wiring (mapping the GUI `Workflow`/`Step` objects to/from the
recipe), which would touch the `autogis/adapters/gui/` files another workstream
owns.

## Why core-only, not the GUI wiring

The GUI already has a `Workflow(name, steps)` / `Step(command, values, fail_on,
pause_on_warning, message)` model (`gui/runner.py`, `gui/executor.py`). Moving or
editing those is a collision with the GUI workstream and would create a
core→adapter dependency (banned invariant). So core defines an **independent,
pure-data recipe schema** mirroring those fields; the GUI later maps
`Workflow ⇄ recipe dict` using this module's `dump_recipe`/`load_recipe`. No GUI
file is touched in this slice.

## Recipe format (YAML)

```yaml
version: 1
name: "Monitoring event processing"
steps:
  - command: [envmon, reconcile-locations]   # null = a bare review checkpoint
    values: {results_csv: results.csv}        # param name -> value (optional)
    fail_on: error                            # error|warning|null (optional)
    pause_on_warning: false                   # optional, default false
    message: ""                               # optional annotation / checkpoint text
  - command: null                             # review checkpoint (mirrors Step.command=None)
    message: "Review layouts before export."
```

Field semantics mirror the GUI `Step`/`Workflow` exactly so the deferred mapping
is a 1:1 translation (YAML list ⇄ tuple).

## Architecture

New arcpy-free module `autogis/core/common/workflow_recipe.py`. No new deps
(reuses `yaml` and `core.common.config.load_config` / `ConfigError`).

- `RECIPE_VERSION = 1`.
- `validate_recipe(data: dict) -> None` — raises `ConfigError` on any structural
  problem (see rules below). The money path; fully unit-tested.
- `load_recipe(path) -> dict` — `load_config(path)` then `validate_recipe`.
- `dump_recipe(data: dict) -> str` — `validate_recipe` then `yaml.safe_dump`
  (`sort_keys=False` to keep step/field order stable and diff-friendly).
- `save_recipe(data: dict, path: Path)` — `dump_recipe` + write (utf-8).

### Validation rules

- Top level: `name` non-empty str; `steps` a non-empty list. `version` optional;
  if present must equal `RECIPE_VERSION` (forward-compat guard — unknown version
  is a clear error, not a silent mis-parse).
- Each step is a mapping with:
  - `command`: `null` **or** a non-empty list of non-empty strings.
  - `values` (optional): a mapping.
  - `fail_on` (optional): `"error"` or `"warning"`.
  - `pause_on_warning` (optional): bool.
  - `message` (optional): str.
  - Unknown step keys are rejected (typo guard).

## CLI

`envmon validate-recipe PATH` (headless, CLOUD): `load_recipe` + echo the recipe
name / step count, or the `ConfigError` and exit non-zero. Registered in
`capabilities._REGISTRY_SEED` (domain `admin`) so `envmon list-tools` shows it.

## Testing (arcpy-free)

`tests/common/test_workflow_recipe.py` (or `tests/envmon/`):
1. A valid recipe (with a command step and a null-command checkpoint) validates
   and round-trips: `load_recipe(save_recipe(d)) == d`.
2. `dump_recipe` preserves step order (`sort_keys=False`).
3. Each validation rule rejects its bad input (missing name; empty steps; command
   not null/list; empty command list; non-str command element; bad `fail_on`;
   non-bool `pause_on_warning`; unknown step key; wrong `version`) → `ConfigError`.
4. CLI: `validate-recipe` exits 0 on a good file, non-zero + message on a bad one.

## Scope / deferred

- **Deferred:** GUI save/load wiring (`Workflow ⇄ recipe`), running a recipe
  headlessly, and the RTK-to-CAD / monitoring-event example recipes — all land in
  the GUI-wiring slice that coordinates with the GUI workstream.
- **YAGNI:** branching, expression languages, an output-binding DSL, internal
  scheduling (roadmap Phase 5 defers these explicitly).

## Decision record

New headless tool + a new core schema → an ADR at merge time (next free number
against `origin/main` **and** all open PRs), referencing this spec and ADR-0087.
Phase 5 is started in parallel with Phase 4 (#280 open) under the owner's
standing "continue roadmap development" directive; the core-only, non-colliding
scope keeps that parallelism safe.
