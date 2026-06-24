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

## File naming

ADRs are named sequentially: `NNNN-kebab-case-title.md`

## New ADRs

When proposing a new ADR:

1. Create a new file with the next sequential number
2. Use the [template](TEMPLATE.md)
3. Start with **Proposed** status
4. Submit for review/discussion
5. Update status to **Accepted** or **Deprecated** after resolution
