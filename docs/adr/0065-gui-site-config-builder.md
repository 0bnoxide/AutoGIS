# ADR-0065: GUI Site Config Builder — guided harvest `config.yaml` authoring with live sublayer lookup

**Status:** Accepted

**Date:** 2026-07-06

## Context

Authoring a harvest-job `config.yaml` requires AGOL knowledge a field user
may not have: item IDs vs REST URLs, sublayer indices, `{FieldName}`
template syntax. A real session hit this directly — a user had to be walked
through inspecting `item.layers` / `item.tables` in a one-off Python script
just to find the right sublayer to harvest photos from.

The GUI adapter already has every piece this needs: the `_pick_path` native
dialog seam (ADR-0060), the `_StepWorker` QThread-signal pattern for
blocking calls (ADR-0055/0057), the pure-logic vs Qt-glue module split
(`forms.py`/`introspect.py` vs `app.py`), and `HarvestConfig.load()` in
`core/common/config.py` as the single validation source for the harvest
schema (url-XOR-item_id, required output keys).

## Decision

1. **Two new modules, matching the existing split.**
   `autogis/adapters/gui/config_builder.py` is pure logic (no PySide6):
   `build_config()` assembles the nested `connection`/`layer`/`output`/
   `options` dict from raw form values (blank strings omitted, never written
   as `""`), `validate_config()`/`write_config()` handle validation and YAML
   output, and `sublayer_entries()` maps an AGOL item's layers + tables to
   dropdown entries. `config_builder_dialog.py` is the `QDialog` glue only.

2. **Validation is a round-trip through `HarvestConfig.load()`, never a
   second rulebook.** `validate_config()` dumps the dict to a temp YAML file
   and calls `HarvestConfig.load()` on it, catching `ConfigError` — the
   url-XOR-item_id invariant and required-output checks stay single-sourced
   in `core/common/config.py`. `write_config()` validates before writing, so
   an invalid form never produces a file.

3. **"Fetch layers/tables" resolves the picked sublayer to `layer.url`, NOT
   `item_id` + an index.** `fetch_sublayers()` lazily imports `arcgis`
   (adapters must import without it), connects via `GIS(profile=...)` (blank
   profile = anonymous), and builds the combined
   `list(item.layers or []) + list(item.tables or [])` — the same convention
   as `core/agol/dashboard_refresh.py`. Entries render as
   `"5 — Daily_Diary_Photos (Table, has attachments)"`, attachment-bearing
   first (stable sort), the rest kept visible for reference. Picking one
   writes its resolved `.url` into the URL field and clears Item ID: the
   `url` field already fully supports targeting a single layer or table with
   zero schema changes, and a resolved URL survives service edits that would
   shift a sublayer index.

4. **Existing seams reused, not reinvented.** The fetch runs on a
   `_FetchWorker(QThread)` reporting via signals (never blocking the UI
   thread), with the same `wait()`-before-drop join and refuse-close-while-
   running guards as `app.py`. A dialog-local `_pick_path()` wraps the two
   native `QFileDialog` calls (folder picker for the output directory,
   save-as-YAML for the config) so headless tests stub it — kept local so
   the dialog never imports `app.py`. Item ID / URL are mutually exclusive
   in the widgets too (filling one disables the other), as a UX mirror of
   the schema rule that `load()` still enforces authoritatively.

5. **Entry point:** a "Build Site Config…" button in `MainWindow` opens the
   dialog window-modally via `open()` (non-blocking, event loop stays free).
   No QSettings use — the dialog persists nothing, so no `settings_store`
   threading is needed.

## Consequences

### Positive

- A user who knows only "the item ID from the AGOL page" can produce a
  valid harvest config end to end: fetch, pick the attachment-bearing
  table from a plain-language list, browse to an output folder, save.
- Every field carries plain-language help; the retries/backoff copy was
  written from `core/harvest/download.py` itself (linear backoff:
  `backoff_seconds × attempt-number`), not guessed.
- 26 new tests: 15 pure (dict assembly, validation reuse, YAML round-trip
  through `HarvestConfig.load`, sublayer mapping/sorting/`None`-tables) and
  11 offscreen Qt (xor wiring, fetch gating/population/failure via a stubbed
  `fetch_sublayers`, browse/save via a stubbed `_pick_path`,
  validate-before-file-dialog, MainWindow entry point). No test touches the
  network or the real QSettings registry.

### Negative / accepted trade-offs

- **Cannot certify look/feel** (same caveat as ADR-0057/0060); the native
  dialogs and the real `arcgis` fetch are exercised only through their
  stubs — a human must run `autogis-gui` against a live org.
- "Open existing config…" (load a YAML back into the form for editing) was
  deliberately deferred — the dialog is write-only for this slice.
- The Fetch button requires both Profile and Item ID; an anonymous fetch of
  a public item is not offered (the URL escape hatch covers that user).
- Templates are free-text with placeholder examples; no field-name
  autocompletion from the fetched layer schema (would need a second
  network call per sublayer — add if users ask).

## Alternatives considered

1. **`item_id` + a new `layer_index` config field.** Rejected: needs a
   schema change (one is in flight on another branch — this dialog
   deliberately does not depend on it), and an index shifts if the service
   is edited; a resolved URL is self-contained today.
2. **Re-deriving validation rules in the dialog.** Rejected: a second copy
   of url-XOR-item_id / required-keys drifts; the temp-file round-trip
   through `HarvestConfig.load()` costs one file write and stays exact.
3. **Reusing `app._pick_path` directly.** Rejected: `app.py` imports the
   dialog for the entry point, so the dialog importing `app` back would be
   circular; the local seam is 6 lines and adds the YAML filename filter.
4. **A generic multi-tool config builder.** Rejected as YAGNI: harvest is
   the config a non-GIS user authors today; nothing else needs this yet.

## Related decisions

- [ADR-0060](0060-gui-window-polish-browse-help.md) — the `_pick_path`
  seam pattern this follows.
- [ADR-0055](0055-gui-workflow-runner-thread-boundary.md) /
  [ADR-0057](0057-gui-walking-skeleton.md) — the QThread-signal bridge
  `_FetchWorker` copies.
- [ADR-0050](0050-unified-gui-adapter-direction.md) — overall GUI direction.

## Issues/PRs

- Implementation: `autogis/adapters/gui/config_builder.py`,
  `autogis/adapters/gui/config_builder_dialog.py`,
  `autogis/adapters/gui/app.py` (entry-point button),
  `tests/test_gui_config_builder.py`,
  `tests/test_gui_config_builder_dialog.py`.
