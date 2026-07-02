# ADR-0040: Canonical arcpy-access style — function-scope `arcpy_env`

**Status:** Accepted

**Date:** 2026-07-02

## Context

`core/envmon` modules reach arcpy through three different styles, none
documented as canonical:

- **A — module-scope lazy provider** (8 modules): `from ...runtime.sessions
  import arcpy_env as _arcpy` at top level — `build_figure_dataset.py:46`,
  `export_figures.py:26`, `groundwater_contours.py:28`, `import_to_gdb.py:42`,
  `layout_manager.py:23`, `manage_callout_overrides.py:13`,
  `validate_database.py:28`, and `build_current_event.py:354` (placed 354
  lines into the file as a deliberate section marker — legal, still a
  landmine for readers).
- **B — function-scope provider**: `import_boring_logs.py:175`,
  `register_drone_flight.py:107`, `survey_to_well_elevation.py:135`,
  `import_drone_products.py:171`, and others.
- **C — raw `import arcpy` in-function, bypassing the provider entirely**:
  `build_analytical_key.py:210`, `dashboard_data_mart.py:292`,
  `export_snapshot.py:74`, `gdb_schema.py:416`, `import_rtk_survey.py:107`,
  `upgrade_schema.py:75`, `import_drone_products.py:198`. One site
  (`dashboard_data_mart.py:292-293`) does C *and* imports `arcpy_env` unused
  (`# noqa: F401`) — evidence a batch author copied the incantation without
  knowing which one is canonical.

Style C evades the one seam (`runtime.sessions.arcpy_env`) the guard
architecture is built around: a reviewer can't grep for one import pattern to
audit the core/adapters arcpy boundary when three exist. Styles A and B also
create a quiet **core → runtime** package dependency (upward, against the
normal core/adapters layering) — harmless today only because `sessions.py` is
52 lines, dependency-free, and lazy at both the module and call level.
(Originally flagged as finding M1 in the independent architecture review,
`docs/reviews/fable-architecture-review.md`, merged in #103.)

## Decision

**Style B — function-scope `arcpy_env` — is canonical** for new `core/envmon`
code:

```python
def some_arcpy_touching_function(...):
    from ...runtime.sessions import arcpy_env as _arcpy
    arcpy = _arcpy()
    ...
```

Function-scope (not module-scope) keeps the import next to its one use site
instead of hidden at the top or middle of a file a reader might not scroll to
(`build_current_event.py:354`'s "landmine" case). Going through `arcpy_env()`
(not a raw `import arcpy`) keeps the guard architecture's one seam intact —
`autogis-env-checker`-style tooling and reviewers can grep for
`import arcpy` in `core/` and expect zero real hits outside
`runtime/sessions.py` itself.

The **sanctioned core → runtime exception**: `core/envmon` modules importing
`runtime.sessions.arcpy_env` is accepted layering, not a violation of the
core/adapters direction (ADR-0001 governs core → *adapters*, not core →
*runtime*). `runtime/sessions.py` has no dependencies of its own and is lazy
at both the module and call level, so this exception carries no import-time
cost and cannot create a cycle.

**Converting existing style A/C sites is not required** — the value here is
stopping a fourth style from appearing, not spending a batch churning working
code for a naming convention. `envmon-spec-checker` (the agent that checks new
and modified code for structural compliance) now flags raw `import arcpy` in a
function body as a style-B recommendation on any *touched* module, which lets
existing A/C sites migrate opportunistically when a batch is already editing
that file for another reason.

## Consequences

### Positive consequences

- One paragraph now answers "how do I reach arcpy from a new core/envmon
  module", ending the guess-from-the-nearest-example pattern that produced
  three styles.
- `envmon-spec-checker` enforces the convention going forward without a
  separate migration batch.
- The core → runtime exception is now written down instead of merely
  "harmless in practice" — a future reviewer doesn't have to re-derive that
  `sessions.py` being 52 lines and dependency-free is *why* it's safe.

### Negative consequences

- 15 existing call sites (8 style-A, 7 style-C) remain non-canonical until a
  batch happens to touch them. Accepted: the review that surfaced this
  explicitly called converting them "not urgent."

## Alternatives considered

1. **Module-scope style A as canonical:** Marginally less repetition across a
   file with many arcpy-touching functions. Rejected — the
   `build_current_event.py:354` landmine case (a module-scope import placed
   hundreds of lines into a file) is exactly the readability failure
   function-scope avoids, and most `core/envmon` modules only touch arcpy in
   one or two functions anyway.
2. **Convert all A/C sites now:** Turns a documentation ADR into a 15-site
   mechanical PR with zero functional change and real regression risk (arcpy
   code untestable in this arcpy-free environment — same risk class as the
   deferred work in ADR-0017/#104 and ADR-0039/#105). Rejected in favor of
   opportunistic migration via the spec-checker.

## Related decisions

- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  this ADR's style B keeps that invariant auditable via a single grep pattern.
- [ADR-0001: Core-plus-adapters architecture](0001-core-adapters-separation.md)
  — the core → runtime exception is scoped narrowly against this ADR's
  core → adapters direction.
- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
  — same architecture-review batch (H2), same "document, don't churn working
  code" discipline.
- `docs/reviews/fable-architecture-review.md` — finding M1, source of this ADR.
