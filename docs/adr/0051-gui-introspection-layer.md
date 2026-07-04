# ADR-0051: GUI introspection layer — Click-tree walk to form descriptors, hardcoded 5-pair xor table, no constraint DSL

**Status:** Accepted

**Date:** 2026-07-04

## Context

ADR-0050 committed to a standalone PySide6 GUI adapter. Its first
implementation task is the layer that tells a GUI *what to render*: the
planning pass (`docs/superpowers/specs/2026-07-03-unified-gui-planning.md`
§2.3) found per-tool form generation is ~80% mechanical from Click's own
parameter metadata, with a short list of known irregularities
(mutual-exclusion pairs enforced in command bodies, comma-separated string
options, commands that guard-then-raise in every environment).

## Decision

1. **`autogis/adapters/gui/introspect.py`, click-only.** A pure-Python
   module that walks the `autogis` root group recursively (same walk idiom
   as `tests/test_capabilities.py`'s drift guards) and emits a
   `CommandForm(path, help_text, fields, unreachable_reason)` per leaf
   command, each field a `FormField(name, label, kind, required, default,
   choices, help_text, repeatable, is_path_output, xor_group)`. No PySide6,
   no new dependency — the GUI toolkit arrives in a later ADR-0050 task.

2. **Kind mapping is a 6-value string, not a type system:** `choice`
   (`click.Choice`, choices copied), `flag` (`is_flag=True`), `path`
   (`click.Path`), `int`/`float` (by param-type name), `text` (everything
   else). `multiple=True` sets a `repeatable` flag on the underlying kind
   rather than being a kind itself. Comma-separated list options
   (`--analytes "a,b,c"`, ~15 of them) are deliberately plain `text`: the
   help string documents the format and the value passes through unchanged.

3. **Path picker direction is a heuristic flag, not ground truth.**
   `click.Path(exists=True)` → open picker; bare `click.Path()` → save
   picker (`is_path_output=True`). Verified across the file: the rule holds
   for the overwhelming majority, with known input-declared-without-exists
   exceptions (`evaluate-readiness`/`portfolio-metrics` run-history readers,
   whose input may legitimately not exist yet; `validate-db`'s GDB
   argument). Exceptions are documented in the module docstring; a GUI
   treats the flag as a default direction and always allows typed paths.

4. **Mutual exclusion is a hardcoded 5-entry table (`XOR_PAIRS`), not a
   constraint DSL.** The pairs are enforced in command *bodies*
   (`raise UsageError`), invisible to parameter introspection, so they are
   named explicitly: `reconcile-locations` (`wells_csv`/`gdb`),
   `survey-to-well-elevation` (`wells_csv`/`gdb`), `update-well-elevations`
   (`wells_csv`/`gdb`), `agol sync-to-gdb` (`out_csv`/`gdb`),
   `batch-import-workbooks` (`manifest`/`edd_dir`). The planning pass
   estimated 4; searching for the actual enforcement signal found the
   fifth. `draft-plume-boundary`'s three-way rule (`--points` xor both
   `--results` and `--coords`) deliberately stays out of the pair table, as
   do conditional requirements (`--gdb requires --table`) — the CLI's own
   UsageErrors cover them. A drift-guard test asserts every table entry
   resolves to real parameter names.

5. **Unreachable commands are the caller's input, not hardcoded.**
   `introspect_cli(unreachable={...})` accepts a space-joined-path → reason
   mapping; matching commands are still fully described (never omitted) but
   carry `unreachable_reason`. The ADR-0006 Pro-fallback-only tools and
   ADR-0039 dead-end families are the intended list — kept out of this
   module because they are reopenable policy decisions, not introspection
   facts.

## Consequences

- The GUI form-rendering task can build against a stable, toolkit-free data
  shape, and gains every future CLI command automatically via the walk.
- Renaming an xor'd option breaks the test, not the GUI at runtime.
- The 5-pair table must be extended by hand if a future command adds a
  body-enforced pair — accepted; the alternative (a constraint DSL or
  body-parsing) was explicitly rejected as over-build for 5 rows.
- `is_path_output` mis-directs the picker on the documented exceptions;
  accepted as a hint with typed-path fallback rather than a per-command
  override table nothing needs yet.

## Related decisions

- [ADR-0050](0050-unified-gui-adapter-direction.md) — the GUI adapter
  direction this implements the first slice of.
- [ADR-0006](0006-pyt-toolbox-as-primary-ui.md) /
  [ADR-0039](0039-cli-first-generation-2-local-tools.md) — the sources of
  the unreachable-command list callers pass in.
