# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records for the AutoGIS project. An ADR is a document that captures an important architectural decision made along with its context and consequences.

## Format

Each ADR follows this structure:

- **Title:** Short summary of the decision
- **Status:** Proposed, Accepted, Deprecated, Superseded
- **Date:** When the decision was made
- **Context:** What prompted the decision; what trade-offs exist
- **Decision:** What was decided
- **Consequences:** What becomes easier/harder as a result
- **Alternatives considered:** What else was evaluated
- **Related decisions:** Links to other relevant ADRs

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [001](0001-core-adapters-separation.md) | Core-plus-adapters architecture | Accepted | 2026-06-18 |
| [002](0002-arcpy-free-core-invariant.md) | Arcpy-free core invariant | Accepted | 2026-06-18 |
| [003](0003-harvest-config-canonical-location.md) | HarvestConfig canonical location | Accepted | 2026-06-20 |
| [004](0004-envmon-suite-merge.md) | Merge envmon suite into AutoGIS | Accepted | 2026-06-19 |
| [005](0005-thread-safe-qa-substrate.md) | Thread-safe QA and reporting substrate | Accepted | 2026-06-19 |
| [006](0006-pyt-toolbox-as-primary-ui.md) | .pyt toolbox as primary UI for LOCAL tools | Accepted | 2026-06-20 |
| [007](0007-logs-to-adr-migration.md) | Migrate project logs to ADR format | Accepted | 2026-06-23 |
| [008](0008-openpyxl-base-dependency.md) | Openpyxl as base dependency | Accepted | 2026-06-19 |
| [009](0009-config-dataclass-style.md) | Config dataclass style (field-typed vs dict-backed) | Accepted | 2026-06-19 |
| [010](0010-explicit-disposition-field.md) | Explicit disposition field for result records | Accepted | 2026-06-19 |
| [011](0011-h281-profile-draft-status.md) | H281 profile draft status and pre-production gate | Accepted | 2026-06-19 |
| [012](0012-reserved-provenance-columns.md) | Reserved provenance columns for future use | Accepted | 2026-06-19 |
| [013](0013-per-record-json-writer.md) | Per-record JSON writer for manifest | Accepted | 2026-06-19 |
| [014](0014-schema-dataclass-package.md) | Domain-split dataclass schema package for envmon tables | Accepted | 2026-06-25 |
| [015](0015-npg-vendoring-pattern.md) | Absorbed-in-place vendoring for Dan Patterson numpy_geometry | Accepted | 2026-06-25 |
| [016](0016-lab-edd-importer-design.md) | Lab EDD Importer — per-lab YAML profile + gdb_schema output types | Accepted | 2026-06-25 |
| [017](0017-run-history-csv-log.md) | CSV-based append-only run history log | Accepted | 2026-06-25 |
| [018](0018-upgrade-gdb-schema-tool.md) | UpgradeEnvMonitoringGDBSchema tool design | Accepted | 2026-06-26 |
| [019](0019-reconcile-locations-design.md) | ReconcileSampleLocations — stdlib difflib, two-path headless/GDB design | Accepted | 2026-06-26 |
| [020](0020-callout-placement-extend-assemble-callouts.md) | Callout placement — extend assemble_callouts, add manage_callout_overrides | Accepted | 2026-06-26 |
| [021](0021-survey123-xlsform-builder-headless-openpyxl.md) | Survey123 XLSForm builder — headless openpyxl tool | Accepted | 2026-06-26 |
| [022](0022-screening-unit-conversion-invariant.md) | Unit-conversion gate for screening-level evaluation | Accepted | 2026-06-26 |
| [023](0023-workgroup-2-post-import-qa-scope.md) | Workgroup 2 scope — post-import QA + first reporting deliverable | Accepted | 2026-06-26 |
| [024](0024-reconcile-locations-fuzzy-matching.md) | ReconcileSampleLocations: stdlib difflib for fuzzy ID matching | Accepted | 2026-06-26 |
| [025](0025-edd-duplicate-rpd-via-isduplicate-flag.md) | EDD duplicate RPD: detect via IsDuplicate=1 flag | Accepted | 2026-06-26 |
| [026](0026-night-implementer-batch-2026-06-27.md) | Night-implementer batch — CompareMonitoringEvents, ProcessLevelLoop, IdentifyMonitoringDataGaps | Accepted | 2026-06-27 |

## File naming

ADRs are named sequentially: `NNNN-kebab-case-title.md`

## New ADRs

When proposing a new ADR:

1. Create a new file with the next sequential number
2. Use the [template](TEMPLATE.md)
3. Start with **Proposed** status
4. Submit for review/discussion
5. Update status to **Accepted** or **Deprecated** after resolution
