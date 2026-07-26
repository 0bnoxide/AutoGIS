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
| [075](0075-canonical-schema-expansion-step1.md) | Canonical envmon schema expansion Step 1 — 12 new `Env_AnalyticalResults` columns; source-qualified 12-component key after issue #304 amended the original 11-component freeze; `MethodDilutionKey`/`Qualifier`/limit-units conventions; `SCHEMA_VERSION` 2.1→2.2; reader-seam boundaries; Step-2 merge gate; `Env_QCResults`/VI fields deferred to Step 3 | Accepted (amended 2026-07-24) | 2026-07-09 |
| [076](0076-run-history-canonical-tool-site-identity.md) | Canonical tool/site identity in CLI run history; restore GUI override reachability | Accepted | 2026-07-09 |
| [077](0077-arcpy-api-currency-policy.md) | arcpy API-currency policy — every new/changed arcpy call (incl. `.pyt` parameter/filter objects) must be verified against current Esri docs before shipping; compliance floor ArcGIS Pro 3.5, prefer 3.6/3.7; deprecated-at-3.5 calls banned | Accepted | 2026-07-10 |
| [078](0078-opentopography-dem-download.md) | OpenTopography DEM download tool — hybrid CLI/`.pyt`, arcpy-free core, dataset auto-routing, new `opentopo` (`pyproj`) optional extra | Accepted | 2026-07-10 |
| [079](0079-close-canonical-read-merge-gate.md) | Close the ADR-0075 canonical-read merge gate — `canonical_records` adapter + 11 consumers converted; canonical-consumer boundary defined by value/flag columns (not table/analyte name); `apply_screening`/`evaluate_rpd_qa`/`validate_database` SPECIAL (keep QC); legacy field-name island out of scope; Step-2/3 follow-ups | Accepted | 2026-07-10 |
| [080](0080-wqx-step2-import.md) | WQX Step-2 import — `wqx_csv` reader + DRAFT profile on the frozen EDD seam; ND synthesis, limit routing/convert-at-load, unconditional MethodDilutionKey fold, speciation fold; merged after the ADR-0079 gate (PR #223) | Accepted | 2026-07-10 |
| [081](0081-lab-edd-profile-drafter.md) | LabEDD profile drafter — `draft-edd-profile` (2.3a) synonym-matching heuristic + `validate-lab-profile` (2.3b); NEEDS_REVIEW fields omitted so validation flags them; closes the two-profile-system disconnect (spec Slice 1, trimmed) | Accepted | 2026-07-10 |
| [082](0082-edd-step3-equis-wmrd-slice1.md) | EDD Step 3 slice 1 — EQuIS WMRD `.xls` reader + `Env_QCResults` table (33 cols); xlrd required dep, D5 no-pivot reversal on real-file evidence, IsReportable-aware canonical-read reruns (closes ADR-0079 follow-up #3); key-collision limitation recorded, fix deferred | Accepted | 2026-07-10 |
| [083](0083-report-template-system.md) | Report template system — self-contained HTML (base64 images, print-optimized) additive to Markdown for the two envmon report tools; one canonical `report.css` consumed by the stdlib render layer and a DesignSync preview bundle; DOCX/PDF-lib deferred; closes #163 | Accepted | 2026-07-11 |
| [084](0084-edd-step3-slice2-key-collision-resolution.md) | EDD Step 3 slice 2 — #230 key collisions. Analytical `MethodID` fold into the `MethodDilutionKey` value recipe (stands). QC run-instance token **reverted post-merge** (Codex review P1a/P1b data-integrity gaps) to a fail-safe blocking guard; QC half reopened. P2 overlength-key guard added. Frozen keys untouched | Accepted (QC reverted) | 2026-07-15 |
| [085](0085-phase5-geostatistical-architecture-review.md) | Phase-5 geostatistical architecture review — slice 1 reuses `groundwater_contours`/`evaluate_gw_models`/`draft_plume_boundary` (TIN/IDW + ranking + boundary clip); EBK/kriging, uncertainty output, and nondetect policy deferred to slice 2 pending ADR-0077 verification; new additive `GW_ModelRun`/`GW_ModelCrossValidation` tables | Accepted | 2026-07-15 |
| [086](0086-geostat-slice2-ebk-uncertainty-concentration.md) | Phase-5 slice 2 — EBK stage, uncertainty raster, analytical concentration surface, and configurable nondetect policy | Accepted | 2026-07-16 |
| [087](0087-post-catalog-production-roadmap.md) | Post-catalog complementary capabilities — ten sequential production phases with explicit exit gates and minimum-slice scope | Accepted | 2026-07-16 |
| [088](0088-civil3d-cad-export-arcpy-legs.md) | Civil3D/CAD arcpy legs (#166): shared LandXML CgPoints writer; headless `export-civil3d --landxml`; `.pyt` `BuildCADExportPackage` wired to doc-verified `arcpy.conversion.ExportCAD`. CAD layer rename (`AddCADFields`) and 8.2's contour/TIN leg deliberately deferred — not doc-verifiable / out of scope | Accepted | 2026-07-15 |
| [089](0089-cad-layer-properties-and-civil3d-tin-landxml.md) | CAD layer properties + Civil 3D TIN LandXML (#166) | Proposed | 2026-07-17 |
| [090](0090-edd-step3-slice2b-dialects.md) | EDD Step-3 slice 2b: EQuIS dialect support (mining/epar4/NYSDEC) — xlsx engine, header normalization, `source_aliases`/`test_sheet` profile keys (amends ADR-0075's 2-sheet freeze, precedent ADR-0082), inline-batch fallback, date-extended batch join, epar4 run-identity token in the `MethodDilutionKey` recipe; three DRAFT profiles | Accepted | 2026-07-17 |
| [091](0091-arcgis-pro-qualification-runner.md) | ArcGIS Pro qualification runner (roadmap Phase 1): pure `core/qualify.py` reporting + live `adapters/qualification.py` probing behind `envmon qualify`, Tier-1 param construction over all 19 tools + Tier-2 scratch-GDB via shipped schema seams, `--self-test` canaries; Phase 1 gate amended to installed-Pro (owner, 2026-07-19) | Accepted | 2026-07-19 |
| [092](0092-unified-tool-discovery-agol-group.md) | Unified tool discovery: `agol` group commands join the `list-tools` registry as group-qualified entries, with bidirectional drift guards (user decision, reverses the envmon-only scoping) | Accepted | 2026-07-19 |
| [093](0093-event-status-staleness-checker.md) | Event status & staleness checker (roadmap Phase 2): headless `envmon event-status` classifies each event artifact current/stale/missing/failed/awaiting-review via a two-ledger freshness rule (RunHistory + SourceRegistry baselines from `--accept`), hardcoded dependency graph tested as a matrix, semantic exit codes; arcpy-free approval inference with documented ceilings | Accepted | 2026-07-20 |
| [094](0094-codex-coordination-shim.md) | Codex coordination shim: Codex `PreToolUse` hook reuses `hook_check.decide()` via in-repo adapter (V4A patch-path parsing) — enforcement parity for read-only-`main` + claims across harnesses | Accepted | 2026-07-20 |
| [095](0095-claude-codex-shared-memory-protocol.md) | Claude↔Codex correspondence protocol over Mnemoverse `collab:autogis`: three literal message types, GitHub-first routing rule, self-service supersession, filtered-write check, automatic three-query startup retrieval — context only, ADR-0094 locking parity conditional pending #270 | Accepted | 2026-07-21 |
| [096](0096-build-current-event-select-samples-kwarg.md) | Fix BuildCurrentEvent/BuildCallouts `select_samples` kwarg drift (`target_analyte_name`→`target_analyte`; both LOCAL tools raised TypeError on every run) + arcpy-free ast/signature regression pin; found via live execute-body testing (issue #272 Option 2 prototype); sibling findings F1 (ScreeningLevelSource field length) + F3 (missing Env_AnalyticalKey) tracked separately | Accepted | 2026-07-21 |
| [097](0097-screening-level-source-field-length.md) | Widen `Env_AnalyticalResults.ScreeningLevelSource` TEXT(64)→256 (production screening sources are 128–162 chars → arcpy INSERT failed; F1 from the #272 campaign) + increase-only `AlterField` migration in `upgrade_gdb_schema` for existing GDBs (doc-verified per ADR-0077), SCHEMA_VERSION 2.5→2.6, arcpy-free field-fits-config regression pin | Accepted | 2026-07-21 |
| [098](0098-remove-dead-analytical-key-gdb-writer.md) | Remove the orphaned `write_analytical_key_gdb_table` (F3 from the #272 campaign): dead code with no caller writing to `Env_AnalyticalKey`, a table never added to the schema; the GDB-output feature was specced 2026-06 but never wired. Pure deletion; CSV/XLSX/MD writers unchanged | Accepted | 2026-07-21 |
| [099](0099-gui-folder-picker-and-hide-unreachable.md) | GUI adapter: gdb params open a folder picker (a `.gdb` is a directory, not a save-file target) for every tool incl. bare-string args like `upgrade-schema`, boolean `--gdb` flags excluded; redirect-only tools hidden from the command picker instead of greyed ("only show what can run") + complete `UNREACHABLE` with the 3 missing class-1 stubs (`compare-drone-surfaces`, `condition-dem`, `run-gw-model-pipeline`). Pure GUI, no CLI/core/arcpy | Accepted | 2026-07-22 |
| [100](0100-new-flight-yaml-scaffold.md) | `new-flight-yaml` (8.6a) — headless scaffold that writes a ready-to-edit drone flight inventory YAML (there was no generator; a required input for one-offs). Core `flight_yaml_template` mirrors `DroneFlight` keys required-first, empties round-trip into `register-drone-flight --dry-run` for validation; `--set KEY=VALUE` pre-fills. Mirrors the `draft-parser-profile` pattern | Accepted | 2026-07-22 |
| [101](0101-compare-drone-surfaces-diff-raster-output.md) | CompareDroneSurfaces — optional `diff_raster_out`: persist the already-computed `sa.Minus` difference raster (saved inside the MINOF `EnvManager`, `overwriteOutput=True`) so the change is mappable, not just summarized. Two-DEM mode only; a pure `validate_diff_output` guard rejects the LandXML+diff combo (no aligned grid). CLI `--diff-raster-out` (parity) + `DERasterDataset` Output param appended last; Raster.save/EnvManager/DERasterDataset doc-verified (ADR-0077) | Accepted | 2026-07-22 |
| [102](0102-site-onboarding-bootstrap-init-site.md) | Production-roadmap Phase 3 first slice — headless `envmon init-site` scaffolds the site/event/parser/figure-spec config skeleton from four versioned templates under `config/_templates/site_skeleton/`, substituting `__SITE_ID__`/`__SITE_NAME__` sentinels (not `{site_id}`, which the figure engine resolves at runtime), surfacing every `_TODO` anchor plus missing regulatory content, and reusing existing loaders as structural validators; `--dry-run` supported | Accepted | 2026-07-22 |
| [103](0103-workflow-recipe-core-schema.md) | Workflow-recipe core schema (Phase 5, slice 1): strict arcpy-free YAML load, validate, dump, and save helpers plus `envmon validate-recipe`; recipe fields mirror GUI workflow steps without introducing a core-to-adapter dependency | Accepted | 2026-07-22 |
| [104](0104-run-recipe-headless-execution.md) | Headless `envmon run-recipe` execution (Phase 5, slice 2): map validated recipes to the existing workflow runner, preserve review checkpoints, and expose stable automation exit codes without duplicating the execution engine | Accepted | 2026-07-22 |
| [105](0105-phase4-monitoring-event-review-notebook.md) | Monitoring-event review notebook (roadmap Phase 4): one supported notebook aggregating 9 review sections from existing headless core producers (zero new core code); reuses public `generate_event_report_html`; excludes compliance/QC-summary (YAGNI); synthetic 2-event records-CSV fixture (no client data); opt-in `notebook = [nbclient, ipykernel]` extra + real-kernel restart-run-all test | Accepted | 2026-07-22 |
| [106](0106-non-sample-row-guard.md) | Skip non-sample rows (footnote/legend + inline annotation) in the GW normalizers via one invariant — no valid date AND no parseable result ⇒ not a sample, drop with a visible QA warning. Fixes real H272 import: `NOTES:` legend + `BOS 200` event-marker rows were parsed as data (bogus records; a 66-char value overflowed `ResultRawText` TEXT(64) and crashed the insert). Surfaced by the #272 execute-body QA campaign; rejected trailing-colon terminator (can't reach mid-block) and field-widening (masks the bug) | Accepted | 2026-07-22 |
| [107](0107-chain-of-custody-lifecycle.md) | Electronic chain-of-custody lifecycle (roadmap Phase 6): headless `core/envmon/custody.py` state machine (draft→generated→released→laboratory_received→results_received→reconciled/exception) with a per-transition audit trail (timestamp, responsible party, temperature/carrier/reason details) and pure planned-vs-received reconciliation; `reconciled` reachable only via reconcile (enforces the gate); per-event JSON store, atomic write; `envmon coc` subgroup (generate/advance/reconcile/status), reconcile exit-code 2 on discrepancy; no signature platform (slice boundary) | Accepted | 2026-07-23 |
| [108](0108-longitudinal-lab-qa-trends.md) | Longitudinal laboratory-QA trends (roadmap Phase 7, slice 1): headless `core/envmon/lab_qa_trends.py` + `envmon lab-qa-trends` consuming `Env_QCResults`-shaped CSVs (reuses `QCResultRecord`+`records_csv`); recovery (data-driven: has `PercentRecovery`; lab row limits over cited 70-130% default) + blank detection (`>= blank_rl_multiple x RL`) trended per method/matrix/analyte across events; every output row carries the configurable, cited threshold. Deferred: RPD/RL-change/qualifier dimensions, by-laboratory grouping (`Env_QCResults` has no `LabName`), headless QC exporter, XLSX. Gate "reproduce a manually reviewed historical set" recorded as a Proposed owner-sign-off item | Accepted | 2026-07-23 |
| [109](0109-outbound-wqx-export.md) | Outbound WQX/regulatory exchange (roadmap Phase 8, slice 1): headless `core/envmon/wqx_outbound.py` + `envmon export-wqx` translates canonical `AnalyticalResultRecord` CSVs to WQX submission columns (names anchored on verified `wqx_reader._COL_*` + `wqx.yaml`, media = inverse `matrix_map`); coordinates from an explicit monitoring-location metadata CSV; hard validation (identifiers, calendar-valid dates, coords, value+units for detections, limit+units for non-detects, method) routes failures to `wqx_rejections.csv` with reasons (no silent drops), opt-in qualifier domain check; deterministic `wqx_submission.csv` + `wqx_provenance.json`. DRAFT — inherits `wqx.yaml` draft status; "passes agency validator" recorded as a Proposed owner-sign-off item | Accepted | 2026-07-23 |
| [110](0110-ci-and-agent-tooling-batch.md) | Claude Code workflow tooling batch (no product code): GitHub Actions CI running the arcpy-free suite on `windows-latest` (repo is Windows-native; ubuntu unverified); `arcpy-doc-verifier` subagent enforcing the ADR-0077 dual check (valid at Pro 3.6 runtime, not deprecated at 3.5 floor) against `docs/arcpy-official-references.md`; `next_adr_number.py` preflight (local + open-PR scan, fail-soft) plus `coord reserve-adr` for atomic cross-session number reservation in the shared `claims.json`. Drafted as 0107, collided with PR #296, renumbered to a reserved 0110 | Accepted | 2026-07-23 |
| [111](0111-phase9-fieldmaps-sync-preflight.md) | Phase 9 slice 1: headless Field Maps sync preflight (Tool 7.5, `agol fieldmaps-preflight`) — pure checks over injected-gis seams reusing `audit_schema`/`sync_layer`; CLI-first per ADR-0039/0043 (owner struck the notebook option); local side from CSV/manifest snapshots, arcpy FGDB leg deferred to slice 2; gate run deferred to the #307 sandbox. `edits_where_clause` gains an `edit_field` kwarg | Accepted | 2026-07-24 |
| [112](0112-survey123-optional-add-on-roadmap.md) | Survey123 optional add-on roadmap — one `autogis` distribution with a future `survey123` extra for live portal operations; base install retains pure form/file workflows; eight sequential optional phases and four milestones prove validation/read paths before publishing/webhooks; does not reorder or block the core production roadmap | Accepted | 2026-07-25 |
| [113](0113-survey123-lifecycle-sampleid-contract.md) | Survey123 Phase 0 slice A: lifecycle SampleID contract — single owner module `core/envmon/sample_id.py` (`{location}-{YYYYMMDD}-{matrix}[-{qc}]`); planner/form/normalizer converge, the existing `QAFlags` `field_dup` choice makes `-FD` producible from the field (amends ADR-0021's calculate), normalizer populates `IsDuplicate`/`DuplicateType`/`ParentSampleID` so RPD pairing sees the duplicate, QC-class guard stops a duplicate fuzzy-consuming its primary at difflib 0.914/0.889/0.941 ≥ 0.85 incl. profile `-DUP`/`-D` markers (closes #360); `sampling_plan`/`legacy_migrator` documented as non-lifecycle | Accepted | 2026-07-25 |

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
