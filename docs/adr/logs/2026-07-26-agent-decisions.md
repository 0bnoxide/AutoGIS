# Agent decisions — 2026-07-26

## Flattening semantics for matrix-nested --screening-levels files (#341)

- **Decision:** Added `load_flat_screening_levels()` to `core/common/config.py`.
  It accepts either a legacy flat `{Analyte: value}` file or the shipped
  matrix-nested shape (`{matrix: {Analyte: {value, units, source}}}`),
  flattening the latter by merging across matrices. Agreeing values merge
  silently; a genuine conflict (same analyte, two different non-null values
  in different matrices) raises `ConfigError` rather than guessing, since
  none of the six affected commands accept a `--matrix` argument to
  disambiguate.
- **Reasoning:** The issue's own fix direction asked for a regression test
  that resolves real, non-`None` values against the actually-shipped
  `screening_levels.yaml` — a "fail loudly" fix alone wouldn't satisfy that.
  Inspecting the shipped file showed only `GW` currently carries non-null
  values (`SOIL` is a 100%-null `_TODO` stub per the file's own header), so
  today's merge is unambiguous; the conflict guard exists so that changes,
  should the same analyte later gain differing GW/SOIL values.
- **Revisit if:** an owner wants per-matrix screening-level resolution for
  these commands instead — that requires adding `Matrix` to the report-CSV
  vocabulary (issue #339's territory) and a `--matrix` CLI option, which is
  a larger design decision this session deliberately did not make
  unilaterally.

## Matrix-scoping fix for #369: skip, don't guess

- **Decision:** For `import_to_gdb._delete_for_replace` under a
  matrix-scoped `replace_site_event`, `Env_WaterLevels` and `Env_RPDResults`
  are now skipped entirely (with a `replace_skipped_unscopable_table` QA
  INFO record) rather than deleted unscoped or newly matrix-filtered.
- **Reasoning:** Neither table has a `Matrix` column in `gdb_schema.py`, so
  there is no schema-safe way to scope their delete to the run's matrix.
  The issue itself frames the right scoping semantics (should
  `Env_WaterLevels` ever be matrix-scoped at all; should `Env_RPDResults`
  gain a `Matrix` column) as an open, owner-level design question. Skipping
  is the direction that is strictly safer than the current behavior (never
  deletes more than before) and doesn't foreclose either future design
  — it only stops the over-deletion.
- **Revisit if:** an owner decides `Env_RPDResults` should carry a `Matrix`
  column (derivable from its parent `Env_Samples` rows) — that's a schema
  migration + arcpy field-add, out of scope for this pass.

## ND_QUALIFIERS canonical set keeps "BDL" despite result_parser.py not parsing it (#340)

- **Decision:** The new canonical `core.common.config.ND_QUALIFIERS` is
  `{"ND", "U", "UJ", "BDL"}` — the union of the seven report modules'
  pre-existing set and `result_parser.py`'s actual nondetect qualifiers
  (`U`, `UJ`), not just the latter.
- **Reasoning:** The issue only asked to add the missing `UJ`; dropping
  `BDL` (which `result_parser.py` doesn't recognize but every report module
  already treated as nondetect) would introduce a new, opposite-direction
  regression -- lab data using that alias would flip from ND to detect in
  reports. Keeping the union satisfies "including UJ, and any other
  qualifiers result_parser.py's is_nondetect recognizes" without silently
  changing behavior nothing in the issue asked to change.
- **Revisit if:** an owner confirms `BDL` is dead/unused convention worth
  dropping, or decides `result_parser.py` itself should learn to parse it.

## export_summary wiring: additive sheets, not restructured existing ones (#343)

- **Decision:** Wired `samples`/`site_id`/`event_id` into
  `export_analytical_summary` as two *new*, conditionally-added sheets
  ("Metadata", "Samples") rather than folding the data into the four
  existing sheets.
- **Reasoning:** The issue offered wiring or dropping as equally valid
  fixes; wiring was chosen since the CLI already advertises and computes
  these options (a fallback site_id, in particular), so dropping would be a
  user-facing regression for anyone already passing them expecting *some*
  effect. Additive sheets were the shortest correct diff that satisfies the
  CLI help text's promise without restructuring the four existing,
  test-pinned sheets.
- **Revisit if:** an owner wants the metadata folded inline (e.g. a header
  row on every sheet) instead of a separate sheet.
