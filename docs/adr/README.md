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
| [052](0052-gui-introspection-layer.md) | GUI introspection layer — Click-tree walk to form-field descriptors; hardcoded 5-pair xor table, no constraint DSL | Accepted | 2026-07-04 |
| [053](0053-gui-executor-qa-signal.md) | GUI executor QA signal — exit code + injected qa.csv gate HALT/PAUSE/CONTINUE; JSON summary status and stdout rejected as gating inputs | Accepted | 2026-07-04 |
| [054](0054-cli-seam-run-recording-recording-command.md) | CLI-seam run recording via RecordingCommand/RecordingGroup, not a result callback | Accepted | 2026-07-04 |
| [055](0055-gui-workflow-runner-thread-boundary.md) | GUI workflow runner — single-flight advance/pause/resume/cancel; Qt thread-boundary punted to the widget-layer task | Accepted | 2026-07-05 |
| [056](0056-gui-form-step-adapter.md) | GUI form-values -> Step adapter — reuses XOR_PAIRS metadata; conditional/type validation left to the child command | Accepted | 2026-07-05 |
| [057](0057-gui-walking-skeleton.md) | GUI walking skeleton — first PySide6 code (optional `gui` extra), QThread bridge, fixed a UNSET-sentinel leak + a QThread lifecycle crash | Accepted | 2026-07-05 |
| [058](0058-coord-hook-target-resolution.md) | Coord hook resolves branch/tree from the write target (not payload cwd); soft contention warn instead of a hard deny | Accepted | 2026-07-05 |
| [059](0059-gui-qa-results-table.md) | GUI QA-results table — renders the executor's already-parsed `qa_rows` as a worst-severity-first, drop-empty-columns, color-coded table (stdout pane kept) | Accepted | 2026-07-06 |
| [060](0060-gui-window-polish-browse-help.md) | GUI window polish — Browse buttons for path fields (folder picker for dir-only params via new `is_dir`), command help text shown; dropped unreachable-greying (nothing to grey) | Accepted | 2026-07-06 |
| [061](0061-drone-geotech-graphics-tool-batch.md) | Drone/geotech-graphics tool batch — DEMConditioningPipeline, CompareDroneSurfaces, GenerateSubsurfaceProfileFromBorings rescoped out of the Phase 5 geostatistical gate and shipped; new read-only LandXML TIN parser | Accepted | 2026-07-06 |
| [062](0062-gui-local-tool-support.md) | GUI LOCAL (arcpy) tool support — persisted `local_python` picker (QSettings), Run gated per tool, class-1 redirect-only tools greyed via new `reachability.UNREACHABLE` map | Accepted | 2026-07-06 |
| [063](0063-gui-workflow-builder.md) | GUI workflow builder v1 — assemble + run multi-step headless workflows over WorkflowRunner (in-session, gate-2 pause/halt/cancel); single Run unified as a 1-step workflow | Accepted | 2026-07-06 |
| [064](0064-agol-publish-hardening.md) | AGOL publish-layer hardening — keep tracebacks in QA errors, pre-check the hosted service name + explicit `publish_parameters`, detect/validate source type (FGDB zip, shapefile zip, GeoJSON) | Accepted | 2026-07-06 |
| [065](0065-gui-site-config-builder.md) | GUI Site Config Builder — guided harvest `config.yaml` dialog; live sublayer lookup resolves the pick to `layer.url`; validation round-trips through `HarvestConfig.load` | Accepted | 2026-07-06 |
| [066](0066-harvest-layer-index-combined-sublayers.md) | `HarvestConfig.layer_index` — harvest sublayer selection over the combined layers+tables list (AGOL `?sublayer=N` numbering); out-of-range raises `ConfigError`; fixes hardcoded `layers[0]` | Accepted | 2026-07-06 |
| [067](0067-coord-hook-write-coverage-hardening.md) | Coordination hook covers every git write in a command, push-to-main refspecs, history-writing porcelain, links, and NotebookEdit | Accepted | 2026-07-07 |
| [068](0068-pyt-run-history-recording.md) | Record run history for redirect-only `.pyt` executions through an arcpy-free `toolbox_core` recorder; environment override then target-GDB parent then cwd; functional Pro QA tracked in #231 | Accepted | 2026-07-11 |
| [069](0069-tool-registry-single-source-consolidation.md) | Consolidate the hand-maintained tool registries behind one table (PROPOSAL) | Proposed (not executed) | 2026-07-07 |
| [070](0070-callout-placement-cli-wiring.md) | Wire callout-placement tools 5.2 / 5.3 (folded hull-collision flag; override CRUD with a full-row read) | Accepted | 2026-07-07 |
| [071](0071-export-survey-cad-landxml-format.md) | LandXML as the CAD point-export format for `export-survey-cad` | Accepted | 2026-07-08 |
| [072](0072-harvest-all-sublayers-mode.md) | `HarvestConfig.all_sublayers` — harvest every attachment-bearing layer/table of an item in one run, each under its own subfolder; mutually exclusive with `url`/`layer_index`/`incremental`; GUI checkbox in the Site Config Builder | Accepted | 2026-07-08 |
| [073](0073-gui-report-plumbing-and-single-run-pause-parity.md) | GUI: copy the executor's qa.csv out to the user's `--report` path (extends ADR-0053), single Run honors "pause on warning" (extends ADR-0063), and color-code the output pane (blue INFO / green PASS) | Accepted | 2026-07-09 |
| [074](0074-draft-lithology-from-scan-tool.md) | DraftLithologyFromScan — headless boring-log OCR (Table-Transformer + TrOCR) into a DRAFT lithology CSV; repo's first torch/transformers dep behind the new `ocr` optional extra | Accepted | 2026-07-09 |
| [075](0075-canonical-schema-expansion-step1.md) | Canonical envmon schema expansion Step 1 — 12 new `Env_AnalyticalResults` columns, frozen 11-component unique key, `MethodDilutionKey`/`Qualifier`/limit-units conventions, `SCHEMA_VERSION` 2.1→2.2, reader-seam boundaries, Step-2 merge gate, `Env_QCResults`/VI fields deferred to Step 3 | Accepted | 2026-07-09 |
| [076](0076-run-history-canonical-tool-site-identity.md) | Canonical tool/site identity in CLI run history; restore GUI override reachability | Accepted | 2026-07-09 |
| [077](0077-arcpy-api-currency-policy.md) | arcpy API-currency policy — every new/changed arcpy call (incl. `.pyt` parameter/filter objects) must be verified against current Esri docs before shipping; compliance floor ArcGIS Pro 3.5, prefer 3.6/3.7; deprecated-at-3.5 calls banned | Accepted | 2026-07-10 |
| [078](0078-opentopography-dem-download.md) | OpenTopography DEM download tool — hybrid CLI/`.pyt`, arcpy-free core, dataset auto-routing, new `opentopo` (`pyproj`) optional extra | Accepted | 2026-07-10 |
| [079](0079-close-canonical-read-merge-gate.md) | Close the ADR-0075 canonical-read merge gate — `canonical_records` adapter + 11 consumers converted; canonical-consumer boundary defined by value/flag columns (not table/analyte name); `apply_screening`/`evaluate_rpd_qa`/`validate_database` SPECIAL (keep QC); legacy field-name island out of scope; Step-2/3 follow-ups | Accepted | 2026-07-10 |
| [080](0080-wqx-step2-import.md) | WQX Step-2 import — `wqx_csv` reader + DRAFT profile on the frozen EDD seam; ND synthesis, limit routing/convert-at-load, unconditional MethodDilutionKey fold, speciation fold; merged after the ADR-0079 gate (PR #223) | Accepted | 2026-07-10 |
| [081](0081-lab-edd-profile-drafter.md) | LabEDD profile drafter — `draft-edd-profile` (2.3a) synonym-matching heuristic + `validate-lab-profile` (2.3b); NEEDS_REVIEW fields omitted so validation flags them; closes the two-profile-system disconnect (spec Slice 1, trimmed) | Accepted | 2026-07-10 |
| [082](0082-edd-step3-equis-wmrd-slice1.md) | EDD Step 3 slice 1 — EQuIS WMRD `.xls` reader + `Env_QCResults` table (33 cols); xlrd required dep, D5 no-pivot reversal on real-file evidence, IsReportable-aware canonical-read reruns (closes ADR-0079 follow-up #3); key-collision limitation recorded, fix deferred | Accepted | 2026-07-10 |
| [083](0083-report-template-system.md) | Report template system — self-contained HTML (base64 images, print-optimized) additive to Markdown for the two envmon report tools; one canonical `report.css` consumed by the stdlib render layer and a DesignSync preview bundle; DOCX/PDF-lib deferred; closes #163 | Accepted | 2026-07-11 |
| [084](0084-edd-step3-slice2-key-collision-resolution.md) | EDD Step 3 slice 2 — #230 key collisions. Analytical `MethodID` fold into the `MethodDilutionKey` value recipe (stands). QC run-instance token **reverted post-merge** (Codex review P1a/P1b data-integrity gaps) to a fail-safe blocking guard; QC half reopened. P2 overlength-key guard added. Frozen keys untouched | Accepted (QC reverted) | 2026-07-15 |
| [085](0085-phase5-geostatistical-architecture-review.md) | Phase-5 geostatistical architecture review — slice 1 reuses `groundwater_contours`/`evaluate_gw_models`/`draft_plume_boundary` (TIN/IDW + ranking + boundary clip); EBK/kriging, uncertainty output, and nondetect policy deferred to slice 2 pending ADR-0077 verification; new additive `GW_ModelRun`/`GW_ModelCrossValidation` tables | Proposed | 2026-07-15 |
| [086](0086-geostat-slice2-ebk-uncertainty-concentration.md) | Phase-5 slice 2 — EBK stage, uncertainty raster, analytical concentration surface, and configurable nondetect policy | Proposed | 2026-07-16 |
| [087](0087-post-catalog-production-roadmap.md) | Post-catalog complementary capabilities — ten sequential production phases with explicit exit gates and minimum-slice scope | Accepted | 2026-07-16 |
| [088](0088-civil3d-cad-export-arcpy-legs.md) | Civil3D/CAD arcpy legs (#166): shared LandXML CgPoints writer; headless `export-civil3d --landxml`; `.pyt` `BuildCADExportPackage` wired to doc-verified `arcpy.conversion.ExportCAD`. CAD layer rename (`AddCADFields`) and 8.2's contour/TIN leg deliberately deferred — not doc-verifiable / out of scope | Accepted | 2026-07-15 |
| [090](0090-edd-step3-slice2b-dialects.md) | EDD Step-3 slice 2b: EQuIS dialect support (mining/epar4/NYSDEC) — xlsx engine, header normalization, `source_aliases`/`test_sheet` profile keys (amends ADR-0075's 2-sheet freeze, precedent ADR-0082), inline-batch fallback, date-extended batch join, epar4 run-identity token in the `MethodDilutionKey` recipe; three DRAFT profiles | Accepted | 2026-07-17 |

## File naming

ADRs are named sequentially: `NNNN-kebab-case-title.md`

**Collision-prone case (parallel branches/PRs):** git won't flag a duplicate
ADR number if two branches each grab the "next" number with different slugs
(this has happened repeatedly — 0034, 0061/0062). If your ADR is on a branch
that may land alongside others, name the file `XXXX-kebab-case-title.md`
(literal `XXXX` placeholder) instead of guessing a number. Assign the real
next-free number at merge time, after checking both `docs/adr/` *and* the
files of any other open PRs. `tests/test_adr_numbering.py` guards against
duplicate real numbers on `main`; it ignores `XXXX-*.md` files since those
are pre-merge by design.

## New ADRs

When proposing a new ADR:

1. Create a new file with the next sequential number — or, if your branch
   may land alongside others, use an `XXXX-` placeholder (see "File naming"
   above) and assign the real number at merge
2. Use the [template](TEMPLATE.md)
3. Start with **Proposed** status
4. Submit for review/discussion
5. Update status to **Accepted** or **Deprecated** after resolution

## Agent-decision logs vs ADRs

`docs/adr/logs/YYYY-MM-DD-agent-decisions.md` records the agent's **autonomous
judgment calls** for audit — a *supplement* to ADRs, **not** a substitute. A
tool-batch or architectural decision still needs an ADR here (logging the
judgment calls does not discharge it). See [`logs/README.md`](logs/README.md).
