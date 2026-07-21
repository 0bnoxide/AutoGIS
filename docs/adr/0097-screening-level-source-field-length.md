# ADR-0097: Widen ScreeningLevelSource to 256 + increase-only field migration

**Status:** Accepted

**Date:** 2026-07-21

## Context

Live headless testing of the arcpy import path (the campaign behind ADR-0096,
issue #272 Option 2) surfaced finding **F1**:
`Env_AnalyticalResults.ScreeningLevelSource` was declared `TEXT(64)` in
`gdb_schema.py`, but every `source` string in the canonical
`config/screening_levels/screening_levels.yaml` is **128–162 characters** (e.g.
"Montana DEQ Tier 1 RBSL (2018) for groundwater — …, May 2018"). The importer
writes that value verbatim, so a real import fails at the arcpy INSERT with
`RuntimeError: … Field length exceeded. Field: ScreeningLevelSource`.

The arcpy-free suite (ADR-0002) cannot see this: field length is an arcpy
write-time constraint, and the writer is `# pragma: no cover`. The schema
version was 2.5.

## Decision

1. **Widen the field:** `ScreeningLevelSource` `TEXT(64)` → `TEXT(256)` in
   `gdb_schema.py` (longest configured source is 162; 256 gives headroom). New
   GDBs created by `create_or_update_gdb_schema` get 256 immediately.

2. **Migrate existing GDBs.** `create_or_update_gdb_schema` is additive-only —
   it never touches an existing field — so a pre-existing GDB keeps the 64-char
   column and stays broken. Added a widening pass to `upgrade_gdb_schema` (the
   schema-migration tool): for each `TABLE_SCHEMAS` text field whose actual
   length is less than the schema length, run `arcpy.management.AlterField(...,
   field_length=<schema length>)`. It only ever **increases** length.

   **Doc-verified (ADR-0077):** `AlterField(in_table, field, {new_field_name},
   {new_field_alias}, {field_type}, {field_length}, {field_is_nullable},
   {clear_field_alias})`. On a populated table the only permitted length change
   is an **increase** — exactly this operation — so it is safe on GDBs that
   already hold data. Not deprecated at Pro 3.5+.
   Sources: pro.arcgis.com "Alter Field (Data Management)"
   (`.../data-management/alter-field-properties.htm`); Esri KB 000012081
   ("Can the Field Length in an Attribute Table Be Modified?").

3. **SCHEMA_VERSION 2.5 → 2.6.** The upgrade report gains a `fields_widened`
   count (per-table + total).

4. **Regression pin (arcpy-free):**
   `test_screening_level_source_field_fits_config_sources` asserts the schema
   field length ≥ the longest `source` in `screening_levels.yaml`. Runs in the
   normal CI; catches drift in either direction (a longer source added, or the
   field shrunk). Follows #272 Option 5 / ADR-0091's backport-pin rule.

## Consequences

- Real imports write the full screening-level source; existing GDBs are fixed by
  running `envmon upgrade-schema`.
- Verified live (Pro 3.6.1 clone): fresh GDB = 256; a simulated 64-char GDB is
  widened to 256 by `upgrade_gdb_schema` (report "1 widened") and a 141-char
  source then inserts cleanly.
- The widening pass generalizes to any future text-field widening (increase-only,
  never shrink) — no per-field special-casing.

## Alternatives considered

- **Forward-only (bump the constant, no migration):** rejected — leaves every
  pre-existing GDB broken with no repair path.
- **Truncate the source in the importer to fit 64:** rejected — silently drops
  the regulatory citation (data loss on a provenance field).
- **Drop + re-add the field at the new length:** rejected — loses existing data;
  `AlterField` increase-in-place preserves it.

## Related

Issue #272 (automated arcpy testing umbrella), ADR-0096 (sibling campaign fix
F2), ADR-0002 (arcpy-free invariant), ADR-0077 (doc-verify), ADR-0091
(qualification runner + backport-pin rule), ADR-0018 (UpgradeGDBSchema tool).
Sibling finding **F3** (missing `Env_AnalyticalKey` table) remains open.
