# ADR-0099: GUI folder picker for gdb params + hide redirect-only tools

**Status:** Accepted — user request (this session)

**Date:** 2026-07-22

## Context

Two usability defects surfaced while a user drove the unified GUI adapter
(`autogis-gui`) through the drone-surface workflow:

1. **gdb Browse opened a save-file dialog.** A file geodatabase (`.gdb`) is a
   *directory* on disk, but `introspect._field` classified every gdb param as an
   output *file* → the Browse button opened `QFileDialog.getSaveFileName`, which
   navigates *into* the `.gdb` and shows its internal `.gdbtable`/`.atx`/`.lock`
   guts with no way to select the `.gdb` folder itself. Root cause: CLI gdb
   params are declared inconsistently — some bare `click.Path()` (`file_okay`
   left True, so the generic `dir_okay and not file_okay` folder test can't see
   them) and some a plain `click.argument("gdb")` (a STRING, e.g.
   `upgrade-schema`, which rendered as a text field with **no Browse at all**).

2. **The GUI offered tools that can only HALT.** `reachability.UNREACHABLE`
   (ADR-0062) lists class-1 *redirect-only* LOCAL tools so the window can mark
   them, but three shipped without an entry — `compare-drone-surfaces`,
   `condition-dem`, `run-gw-model-pipeline`. Each `_guard()`s then
   *unconditionally* raises "…runs inside ArcGIS Pro only; use the .pyt toolbox",
   so selecting one from the GUI produced a guaranteed HALT. The user selected
   Compare Drone Surfaces and hit exactly that dead end. Existing marked tools
   were only *greyed*, still cluttering the picker with never-runnable entries.

## Decision

Pure GUI-adapter change (no CLI/core/arcpy touched); the value passed to each
command is unchanged.

### Folder picker for every gdb param (`introspect._field`)

Recognise the gdb param family by name (`gdb`, `gdb_path`, or `*_gdb`) and force
a directory path field — `kind="path"`, `is_dir=True` — for any text/path
spelling, so `_dialog_kind` opens `getExistingDirectory`. A boolean `--gdb`
*flag* (`reconcile-locations`' "also write to a gdb" toggle) is **excluded** — it
stays a checkbox (`kind in ("text", "path")` guard). Name-based, not a per-param
whitelist, so it covers every current and future tool's gdb uniformly. The field
stays typeable, so creating a *new* `.gdb` (pick the parent, append the name)
still works.

### Hide redirect-only tools instead of greying (`app.py`)

The window builds `self._forms` filtering out any form carrying an
`unreachable_reason`, so class-1 redirect-only tools are **absent** from the
command picker rather than shown disabled ("only offer what can run"). Headless
and class-2 (arcpy-executable once a `local_python` is set) tools stay listed.
`_run_blocked_reason`'s unreachable check is kept as a defensive belt-and-braces
guard even though no unreachable form is now selectable. `_window_forms` /
`introspect_cli(unreachable=…)` still stamp the reason (the filter consumes it).

### Complete the UNREACHABLE map (`reachability.py`)

Add the three missing class-1 entries (`run-gw-model-pipeline`, `condition-dem`,
`compare-drone-surfaces`), verified against their cli.py bodies (each guards then
unconditionally redirects). `build-conc-surface` is deliberately **not** added —
its `--dry-run` leg runs headless, so it stays reachable (same
reachable-via-a-headless-leg rationale as `export-civil3d` in the module
docstring).

## Consequences

- Every tool's gdb Browse opens a folder chooser; `upgrade-schema`'s gdb gains a
  Browse button it never had. The picker selects *existing* directories — new-gdb
  creation is by typing (documented ceiling, matches the "Browse is a convenience
  over typing" design).
- The command picker shows only runnable commands; the three dead-end tools (and
  the eight already-marked ones) vanish from the GUI. They remain the primary-UI
  `.pyt` toolbox tools inside ArcGIS Pro — the GUI just no longer pretends it can
  run them. Discoverability trade-off (a user won't learn from the GUI that these
  exist in Pro) was accepted by the user over a cluttered, misleading list.
- Tests: `test_gui_introspect` gains a gdb-folder-picker case; `test_gui_app`'s
  two class-1 greyed-behaviour tests become hidden-from-picker tests;
  `test_gui_reachability` guards the three new entries and pins
  `build-conc-surface` reachable. Full GUI suite green.

## Related decisions

- ADR-0062 — GUI reachability policy (the UNREACHABLE map this completes)
- ADR-0052 — GUI introspection layer (pure `click`→form, no toolkit)
- ADR-0050 — unified GUI adapter
- ADR-0006 — tools 2-7 are Pro-only, CLI redirects to the .pyt toolbox
