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
| [027](0027-import-rtk-survey-points.md) | ImportRTKSurveyPoints — configurable-column CSV parser + two-table GDB write | Accepted | 2026-06-28 |
| [028](0028-cloud-tools-batch-2026-06-28.md) | Cloud-tools batch — 5 headless QA/export/reporting tools | Accepted | 2026-06-28 |
| [029](0029-validation-adapters-are-intentionally-thin.md) | validate_*/manage_* are intentionally thin adapters (don't fuse) | Accepted | 2026-06-29 |
| [030](0030-autonomous-headless-batches-2026-06-29.md) | Autonomous headless tool batches (2026-06-29) — PRs #81/#84/#88 | Accepted | 2026-06-29 |
| [031](0031-autonomous-headless-batches-2026-06-30.md) | Autonomous headless tool batches (2026-06-30) — PRs #92/#93/#95/#96 | Accepted | 2026-06-30 |
| [032](0032-headless-tools-batch-2026-07-01.md) | Headless tools batch — RTK control check, portfolio metrics, GW model cross-validation, survey CAD/GIS export, well inspection reports | Accepted | 2026-07-01 |
| [033](0033-boring-log-db-and-attachment-index.md) | Foundation-completion batch — CreateBoringLogDatabase (8.0a) + SyncFieldAttachments envmon-side attachment index (6.5) | Accepted | 2026-07-01 |
| [034](0034-python-label-expression-generator.md) | GeneratePythonLabelExpressions — sibling of the Arcade label generator | Accepted | 2026-07-02 |
| [035](0035-cad-civil3d-handoff-batch.md) | CAD/Civil 3D handoff batch — BuildCADExportPackage, ExportContoursForCivil3D | Accepted | 2026-07-02 |
| [036](0036-agol-webmap-hosted-views-batch.md) | AGOL web map + hosted views batch — UpdateAGOLWebMapFromFigureSpec, CreateHostedViewsForStakeholders | Accepted | 2026-07-02 |
| [037](0037-h272-real-data-verification.md) | Real-data verification of H281-family screening levels and parser profile | Accepted | 2026-07-02 |
| [038](0038-record-dataclass-naming-convention.md) | Record-dataclass naming — PascalCase iff GDB-mirroring | Accepted | 2026-07-02 |
| [039](0039-cli-first-generation-2-local-tools.md) | Generation-2 LOCAL tools are CLI-first; scope the two callout dead ends | Accepted | 2026-07-02 |
| [040](0040-canonical-arcpy-access-style.md) | Canonical arcpy-access style — function-scope arcpy_env | Accepted | 2026-07-02 |
| [041](0041-update-layout-text-cli-reuses-layout-manager.md) | UpdateLayoutDynamicText (5.8) — CLI wrapper over shipped layout_manager, no new module | Accepted | 2026-07-02 |
| [042](0042-gen-boring-logs-headless-markdown-assembly.md) | GenerateBoringLogPDFs (8.0c) — headless Markdown assembly; report module owns the read side 8.0a never shipped | Accepted | 2026-07-02 |
| [043](0043-build-fieldmaps-cli-first-gdb-provisioning.md) | BuildFieldMapsMonitoringProject (7.1) — CLI-first plan/provision split; 7.1b field names over the spec's prose | Accepted | 2026-07-02 |
| [044](0044-sync-agol-layer-attribute-sync-cli-first.md) | SyncAGOLFeatureLayerToGDB (6.2) — attribute-only sync; attachments stay with the harvester | Accepted | 2026-07-03 |
| [045](0045-create-sampling-event-headless-planner.md) | CreateSurvey123SamplingEvent (2.7) — headless pre-field planner; plan's SampleID format over the spec's | Accepted | 2026-07-03 |
| [046](0046-well-inspection-photo-report-headless-xlsx.md) | GenerateWellInspectionPhotoReport (7.4) — headless XLSX from the harvest manifest; Pillow as a `report` extra | Accepted | 2026-07-03 |
| [047](0047-gen-map-series-cli-first-export-reuse.md) | GenerateSiteMapSeries (5.6) — CLI-first batch figure-packet exporter; arcpy-free planner + ExportFigures-chain reuse | Accepted | 2026-07-03 |
| [048](0048-fold-batch-edd-import-into-batch-import-workbooks.md) | BatchEDDImport — folded into batch-import-workbooks (2.2) as an `--edd-dir` mode instead of a new tool | Accepted | 2026-07-03 |
| [049](0049-headerless-rtk-survey-format-detection.md) | Headerless RTK survey CSV format detection — sniff, guess-with-confidence-gate, retain GNSS metadata end-to-end | Accepted | 2026-07-03 |
| [050](0050-unified-gui-adapter-direction.md) | Unified GUI — standalone PySide6 adapter (new adapter, not a fork), v1 includes workflow wiring, CLI-seam run-history with concurrency-safe writes | Accepted | 2026-07-04 |
| [051](0051-run-history-msvcrt-sentinel-lock.md) | Run-history concurrency-safe writes — msvcrt sentinel-byte lock past EOF; header decided by size-under-lock | Accepted | 2026-07-04 |

## File naming

ADRs are named sequentially: `NNNN-kebab-case-title.md`

## New ADRs

When proposing a new ADR:

1. Create a new file with the next sequential number
2. Use the [template](TEMPLATE.md)
3. Start with **Proposed** status
4. Submit for review/discussion
5. Update status to **Accepted** or **Deprecated** after resolution

## Agent-decision logs vs ADRs

`docs/adr/logs/YYYY-MM-DD-agent-decisions.md` records the agent's **autonomous
judgment calls** for audit — a *supplement* to ADRs, **not** a substitute. A
tool-batch or architectural decision still needs an ADR here (logging the
judgment calls does not discharge it). See [`logs/README.md`](logs/README.md).
