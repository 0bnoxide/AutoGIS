# ADR-0016: Lab EDD Importer — per-lab YAML profile + gdb_schema output types

**Status:** Accepted

**Date:** 2026-06-25

## Context

Labs deliver Electronic Data Deliverables (EDDs) as flat CSV or two-tab XLSX files.
Column names, date formats, matrix codes, and qualifier conventions vary by lab and even
by lab contract. The existing import pipeline only handles Excel workbooks structured
around `ParserProfile` / `SheetProfile` column anchors, which are position-based (column
letter → field). Lab EDDs are header-name-based (column name → field).

Two output type options exist:
- `gdb_schema.SampleRecord` / `AnalyticalResultRecord` (35-field dataclasses in
  `autogis/core/envmon/gdb_schema.py`) — the types `append_records_idempotent` writes
- `schema/envmon.EnvSample` / `EnvAnalyticalResult` (9-field dataclasses in
  `autogis/core/common/schema/envmon.py`) — lightweight domain-model layer with no
  active callers in production

The codebase navigator confirmed `schema/envmon.EnvSample` has zero callers and cannot
reach `append_records_idempotent` without a bridge adapter that does not yet exist.

## Decision

### Profile design
Add `LabEDDProfile` — a parallel YAML-loaded dataclass in `autogis/core/envmon/edd_profile.py`. One YAML per lab in `autogis/config/lab_profiles/`. Column anchors are header-name strings (not position integers). Same `load_config()` loader as `ParserProfile`. Supports two formats: `flat_csv` and `two_tab_xlsx` (sample sheet + result sheet joined on sample_id).

`resolve_column(row, field)` accepts a string or list of alternates for each field mapping, returning the first match (or None if absent). Caller emits the QA record — the resolver is passive.

### Output types
The EDD importer outputs `gdb_schema.SampleRecord` and `gdb_schema.AnalyticalResultRecord` — the same types all other normalizers produce. This lets `run_edd_import` call `append_records_idempotent` directly without any adapter bridge.

### Separate qualifier column
`parse_result_value()` handles combined result+qualifier strings (e.g. `"0.5 U"`). Lab EDDs deliver result and qualifier in separate columns. The exposed `apply_qualifiers()` alias (ADR-016 companion: result_parser change) is called after `parse_result_value` to overlay the separate qualifier column.

### Monkeypatch seam in run_edd_import
`run_edd_import` needs to call `import_to_gdb` functions (arcpy-required) but must remain importable and testable without arcpy. Module-level stub functions in `edd_importer.py` forward to `import_to_gdb` via lazy inner imports. The stubs are replaced by `monkeypatch` in unit tests. This pattern is consistent with the existing `_guard("LOCAL")` approach in the CLI.

## Consequences

### Positive consequences

- Per-lab YAML profiles are version-controllable and can be shared without code changes
- `resolve_column` with alternate name lists handles minor column name variations across batches from the same lab
- Using `gdb_schema` output types requires no new adapter bridge — the import lifecycle is identical to the Excel normalizer
- `normalize_edd_rows` is fully arcpy-free and unit-testable with synthetic row dicts
- The module-level stub pattern makes `run_edd_import` testable without a real GDB

### Negative consequences

- `LabEDDProfile` and `ParserProfile` are parallel, not unified — two profile concepts to understand
- `gdb_schema.SampleRecord` has 17 fields; several (SourceWorkbook, SourceSheet, SourceColumn, SourceCell) don't map naturally from EDDs and are populated with stub values (lab profile ID, format name, empty string)
- `schema/envmon.EnvSample` remains unused by the EDD importer, deferring the question of when to migrate to the lighter domain-model types

## Alternatives considered

1. **Extend ParserProfile to support EDDs:** Add an `edd` format flag to SheetProfile.
   - **Rejected:** SheetProfile is position-based (column letters/integers). EDDs are header-name-based. Making one dataclass handle both structural models produces a confusing union.

2. **Output schema/envmon.EnvSample:** Use the lighter 9-field domain-model types and build a bridge to `append_records_idempotent`.
   - **Rejected:** `EnvSample` has no callers; the bridge adapter doesn't exist yet; this would require designing and building a new adapter layer as a prerequisite. The gdb_schema types work today.

3. **Monkeypatch via `import_to_gdb` module attribute patching:** Patch `autogis.core.envmon.import_to_gdb.create_import_batch` directly.
   - **Rejected:** Would require the monkeypatch to import `import_to_gdb`, which triggers arcpy at test time. Module-level stubs in `edd_importer.py` itself avoid this.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — edd_importer.py and edd_profile.py must uphold this
- [ADR-014: Schema dataclass package](0014-schema-dataclass-package.md) — schema/envmon.py is deferred for EDD output; gdb_schema types used instead
- [ADR-009: Config dataclass style](0009-config-dataclass-style.md) — LabEDDProfile follows the same pattern
