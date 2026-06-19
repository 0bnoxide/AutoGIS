# Changelog

## 1.0.0 — 2026-06-10
Initial release: 23 src modules, 10-tool Python toolbox, config set for
H281 Glasgow, 56-test pytest suite with a synthetic H281-style workbook.

Schema notes (additive extensions beyond the spec's field lists):
* New table `Env_CurrentEventWide` (Tool 3 output; one row per
  location/sample with per-analyte display columns added dynamically).
* `Env_CalloutBoxes` gains `PlacementQuadrant` (TEXT 4) and
  `CollisionScore` (DOUBLE) so reviewers can sort/symbolize problem
  callouts. All schema creation is additive; nothing is dropped.

Deliberate semantics worth knowing:
* `ExceedsScreeningLevel` is tri-state (NULL for nondetects/statuses).
* Metals records store `Matrix='GW'` with `AnalyticalGroup='METALS'`
  (dissolved metals in groundwater), so GW figure specs can include them.
* Imports are idempotent on the UNIQUE_KEYS defined in `gdb_schema.py`;
  skipped duplicates are logged individually.
