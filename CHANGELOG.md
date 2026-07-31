# Changelog

## Unreleased — Environmental Monitoring suite merge

Folded the Environmental Monitoring toolbox (formerly a standalone ArcGIS Pro
`.pyt` with a flat `src/` on `sys.path`) into the `autogis` package as one suite.

### Architecture

- **One core, four adapters.** The envmon toolbox is now `autogis.core.envmon`
  (relative imports — the `sys.path` hack is gone), sitting on the shared
  `autogis.core.common` substrate alongside `autogis.core.harvest`. Four
  adapters marshal over the same core: the `click` CLI
  (`autogis.adapters.cli`), the ArcGIS Pro GUI
  (`autogis.adapters.toolbox.pyt`), the unified PySide6 desktop GUI
  (`autogis.adapters.gui`, ADR-0050), and the importable core itself. Adapters
  carry no business logic.
- **Lazy `arcgis` / `arcpy`.** Importing any `core` module succeeds with neither
  installed. `arcgis` is the `cloud` extra; `arcpy` is detected at runtime
  (ships with Pro, never a pip dependency). `openpyxl` is a base dependency.
- **Thread-safe QA / reporter substrate.** Ported `qa_checks` →
  `core.common.qa` (`QARecord` / `QACollector`) and `logging_utils` →
  `core.common.logging` (arcpy-mirroring handler, lazy arcpy), with an `RLock`
  around the whole shared-state surface (mutators *and* iterating writers).
  Added a `Reporter` over it with a cancel/progress hook, an explicit
  `disposition` field on result records (`downloaded` / `skipped` / `failed`),
  and a `summary_counts` view (QA records stay issue-only).
- **Runtime capability registry + guard.** `runtime.capabilities` declares each
  tool's runtime class (CLOUD / LOCAL / HYBRID); `adapters.guard.require_runtime`
  refuses LOCAL tools on the CLI when `arcpy` is absent, with a clear message.
  Session providers added in `runtime.sessions` (AGOL-profile/env,
  active-Pro-portal, arcpy-env).
- **Reserved provenance columns** on the unified result record (`checksum` +
  `algorithm`, `geometry`, `source_table`, `relationship_id`) — empty now,
  filled post-merge.
- **CLI surface.** `autogis` is now a group: `autogis harvest …` plus an
  `autogis envmon <tool> …` sub-group. Tools 1/9/10 (plus harvest) are
  first-class headless; tools 2–8 are registered but runtime-guarded.
  `autogis-harvest` kept as a legacy alias.
- **Ported 56 envmon tests** into the harness suite; pure-Python modules import
  and pass with no arcpy. Deleted `staging/envmon-incoming/`.

### Carried caveats (not regressed)

- The H281 parser profile is an **unverified DRAFT** (DRAFT banner + `_TODO`s);
  real-workbook verification and a human-review-before-first-import gate
  (Tool 1) remain mandatory.
- Screening-levels files ship **all-null** with `_TODO` citations and must be
  populated before production.
- `average_parent_and_duplicate` still emits its QA WARNING.
- arcpy code paths (tools 2–8) remain un-CI-able and must be exercised in Pro.

## 1.0.0 — 2026-06-10 (Environmental Monitoring, pre-merge)

Initial standalone release: 23 src modules, 10-tool Python toolbox, config set
for H281 Glasgow, 56-test pytest suite with a synthetic H281-style workbook.
Tri-state `ExceedsScreeningLevel`; idempotent imports on the UNIQUE_KEYS in
`gdb_schema.py`; additive schema extensions (`Env_CurrentEventWide`,
`PlacementQuadrant` / `CollisionScore` on `Env_CalloutBoxes`).
