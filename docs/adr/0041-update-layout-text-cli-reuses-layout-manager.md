# ADR-0041: UpdateLayoutDynamicText (5.8) — CLI wrapper over the shipped layout_manager, no new module

**Status:** Accepted

**Date:** 2026-07-02

## Context

Roadmap tool 5.8 (UpdateLayoutDynamicText) asks for a batch updater that
pushes one metadata record into an APRX layout's text elements. Two planning
artifacts from 2026-06-28 each proposed a **new** core module for it:

- `docs/superpowers/specs/2026-06-28-update-layout-dynamic-text-design.md` —
  a new `layout_text.py` with `resolve_layout_text()`.
- `docs/superpowers/plans/2026-06-28-update-layout-dynamic-text.md` — a
  different new `layout_text_updater.py` with `apply_substitutions()` /
  `load_substitutions_from_yaml()`, full TDD walkthrough included.

Neither references `autogis/core/envmon/layout_manager.py::update_layout_text()`,
which already ships and is already in production (called from `toolbox.pyt`'s
report-figure-package pipeline): it sets named layout text elements *and*
resolves `{{placeholder}}` tokens, raising a QA warning on any unresolved
placeholder — more capable than either proposal. Both docs also chose the
pre-ADR-0039 "CLI guards-and-redirects to the `.pyt`" architecture, which no
longer applies to new LOCAL tools.

The actual gap was only this: no standalone CLI command ran that step against
an arbitrary APRX + a values file outside the full figure-package pipeline.

## Decision

**Reuse, don't rebuild.** Tool 5.8 is the `envmon update-layout-text` CLI
command (`--aprx`, `--layout` (optional; default all layouts), `--values`,
`--dry-run`, shared `--report`/`--fail-on` contract), CLI-first per ADR-0039,
guarded via `_guard("update-layout-text")`, calling the existing
`layout_manager.update_layout_text()` directly. No `.pyt` entry — the tool
needs no interactive map context.

Two small additions to `layout_manager.py`, nothing else:

- `load_layout_text_yaml(path) -> dict[str, str]` — arcpy-free loader for the
  values file, accepting a flat `{ElementName: text}` mapping or a list of
  `{element_name, text}` dicts (the two shapes the stale plan proposed),
  returning the `text_values` dict `update_layout_text()` already takes.
- A keyword-only `dry_run: bool = False` on `update_layout_text()` — apply
  and report QA without saving the APRX. Default preserves the pipeline
  call's behavior exactly. (The no-layout early-return path no longer saves
  an unmodified APRX — a save with zero changes was a no-op.)

Both stale planning docs are marked **Superseded** at the top, pointing here,
so a future session doesn't resurrect a parallel module.

`--layout` is optional rather than required (the specs implied required):
`update_layout_text()` already treats `layout_name=None` as "all layouts",
and the figure pipeline itself passes a possibly-absent `layout_name` — the
CLI mirrors the function's real contract instead of narrowing it.

## Consequences

### Positive consequences

- Zero duplicated placeholder/element logic; one production code path serves
  both the pipeline and the standalone command.
- The last "Foundation laid"-era roadmap gap in §5 closes with a diff of one
  CLI command, one small loader, one flag, and tests — instead of a third
  parallel text-substitution module.
- `layout_manager.py` gains its first direct unit tests (mocked-arcpy tests
  for `update_layout_text` alongside the loader tests): the brief assumed
  existing coverage, but none existed.

### Negative consequences

- The CLI edits the target APRX **in place** (with `--dry-run` as preview),
  unlike the pipeline which always works on a copy of the template. Accepted:
  editing the file you point at is the expected semantics for a standalone
  updater; users wanting the copy behavior use the figure-package pipeline.
- The loader lives in `layout_manager.py` (an otherwise arcpy-bound module —
  module-scope style-A `arcpy_env`, lazy either way) rather than a separate
  arcpy-free file. Accepted: it belongs next to the function it feeds; the
  module stays importable without arcpy.

## Alternatives considered

1. **Implement the 2026-06-28 plan as written (`layout_text_updater.py`):**
   Rejected — duplicates shipped, in-production logic; two text-substitution
   authorities would drift.
2. **Implement the 2026-06-28 spec (`layout_text.py` with field-spec
   resolution / figure-number sequencing):** Rejected — the metadata→element
   resolution layer is speculative (no caller needs it); the flat values-file
   shape covers the roadmap use case. Add resolution later if a real packet
   workflow demands it.
3. **Guard-and-redirect to a new `.pyt` tool class (ADR-0006 pattern):**
   Rejected per ADR-0039 — generation-2 LOCAL tools are CLI-first; no
   interactive map context is needed here.

## Related decisions

- [ADR-0039: Generation-2 LOCAL tools are CLI-first](0039-cli-first-generation-2-local-tools.md)
  — governs the command shape; both stale docs predate it.
- [ADR-0006: .pyt toolbox as primary UI for LOCAL tools](0006-pyt-toolbox-as-primary-ui.md)
  — still governs tools 2-8 only; not this tool.
- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) —
  the new loader is arcpy-free; `update_layout_text` keeps its existing lazy
  provider access.
- `docs/superpowers/specs/2026-07-02-remaining-roadmap-items-brief.md`
  (PR #130) — the brief that identified the reuse-don't-rebuild shape.
