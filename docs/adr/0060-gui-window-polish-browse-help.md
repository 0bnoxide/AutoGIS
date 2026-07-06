# ADR-0060: GUI single-tool window polish — Browse buttons for path fields, command help text, `is_dir` descriptor

**Status:** Accepted

**Date:** 2026-07-06

## Context

[ADR-0057](0057-gui-walking-skeleton.md) shipped the PySide6 walking-skeleton
window (`autogis/adapters/gui/app.py`) and the user confirmed it works live
against a real AGOL org. Two rough edges remained in that first slice: every
`click.Path` field rendered as a **type-only** `QLineEdit` (no file/folder
picker), and the selected command's help text — present on 79 of 80 headless
commands — was never shown.

Scope was set from a read-only probe of the live command tree rather than
assumption:

- **264 path fields** across the 80 headless commands, all type-only.
- Of those, **255 are file-or-dir ambiguous** (a bare `click.Path()` defaults
  to `file_okay=True, dir_okay=True`), **5 are directory-only**
  (`--edd_dir`, `--input_dir`, `--out_dir`, `--harvest_dir`, `--mart_dir`),
  and 4 are file-only.
- **"Grey out unreachable commands" was dropped:** all 13 ADR-0006 /
  ADR-0039 dead-end commands are `requires_arcpy`-classified and therefore
  already filtered out of the headless window — there are **zero
  always-broken buttons to grey**. Adding the machinery would have been
  YAGNI for a headless-only window.

## Decision

1. **Browse buttons for path fields.** Each `kind == "path"` field renders as
   `[ QLineEdit ][ Browse… ]`. The `QLineEdit` stays the value widget
   (`_raw_values` reads it) and **stays editable** — typing is the correct
   universal input, because 255/264 params are file-or-dir ambiguous and no
   dialog can be universally right for them. Browse is a convenience layered
   on top.

2. **`FormField.is_dir` added to `introspect.py`** — `True` when the param is
   `click.Path(dir_okay=True, file_okay=False)`. Backward-compatible (new
   field, defaults `False`; a non-`path` field is never a directory). Only 9
   of 264 path params are unambiguous; `is_dir` precisely captures the 5
   directory-only ones so their Browse opens a folder picker instead of a
   useless file dialog.

3. **The dialog decision is split from the dialog effect.**
   `_dialog_kind(field) -> "dir" | "save" | "open"` is a pure function
   (`is_dir` wins over `is_path_output`, since a directory is picked the same
   way whether read or written) and is unit-tested. `_pick_path()` is a thin
   seam wrapping the three native modal `QFileDialog` calls — the **one piece
   a headless test cannot drive**. `MainWindow._browse` wires them and is
   tested by stubbing `_pick_path`, so no native dialog is ever opened in the
   test path. A cancelled dialog returns `""` and leaves the field untouched.

4. **Command help text** is shown in a word-wrapped `QLabel` above the form,
   refreshed on every command change (cleared on the no-form branch).

## Consequences

### Positive

- Path fields are no longer type-only; directory-only params get a folder
  picker. Command help is visible without leaving the GUI.
- 8 new offscreen tests: an `is_dir` descriptor spot-check
  (`test_gui_introspect.py`), and in `test_gui_app.py` — `_dialog_kind`
  precedence, `_browse` wiring + cancel, per-path-field Browse rendering,
  each-button-fills-its-own-field, a **button-count-stays-constant across
  repeated command switches** regression (the widget-lifecycle failure mode
  this file has hit before — confirms `removeRow` deletes nested-layout
  children synchronously), and help-text display/update.
- `is_dir` is additive on the ADR-0052 descriptor; any other future consumer
  gets folder-vs-file information for free.

### Negative / accepted trade-offs

- **This ADR still cannot certify look/feel** — same caveat as ADR-0057; a
  human must run `autogis-gui` and look at it. The native `QFileDialog`
  itself is exercised in tests only through the `_pick_path` stub.
- The 255 file-or-dir ambiguous params get a **save/open file dialog** by
  default (via the `is_path_output` heuristic, which has documented
  exceptions in `introspect.py`'s module docstring). For those the editable
  text field remains the source of truth; Browse is best-effort.
- LOCAL (arcpy) tool support and the multi-step workflow builder remain
  deferred, unchanged from ADR-0057.

## Alternatives considered

1. **No `is_dir`; Browse always a file dialog.** Rejected: the 5
   directory-only params cannot be confirmed in a file dialog — a broken
   affordance for them — and `is_dir` is ~4 lines.
2. **Capture the full `file_okay`/`dir_okay` pair (or a constraint model).**
   Rejected as YAGNI: only the dir-only case changes the dialog; the 255
   "both" params stay ambiguous regardless, so extra flags buy nothing.
3. **Grey out / disable unreachable commands (the original "polish"
   bundle's third item).** Rejected for this slice: the probe proved every
   dead-end command is already filtered out as arcpy, so there is nothing to
   grey. Revisit only if the window ever surfaces arcpy tools.
4. **Inline `_pick_path` into `_browse` (no seam).** Rejected: it is the only
   untestable line; isolating it keeps the wiring testable without a native
   dialog.

## Related decisions

- [ADR-0057](0057-gui-walking-skeleton.md) — the walking-skeleton window this
  polishes.
- [ADR-0052](0052-gui-introspection-layer.md) — `FormField`; `is_dir` is
  added here.
- [ADR-0050](0050-unified-gui-adapter-direction.md) — overall GUI direction.

## Issues/PRs

- This decision + implementation: `autogis/adapters/gui/app.py` (Browse
  buttons, help label, `_dialog_kind` / `_pick_path` / `_browse`),
  `autogis/adapters/gui/introspect.py` (`is_dir`), `tests/test_gui_app.py`,
  `tests/test_gui_introspect.py`.
