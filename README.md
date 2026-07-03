# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123, delivered as a single suite:
the **Attachment Harvester** plus the **Environmental Monitoring tools**, folded into **one
`autogis` package** — one shared core with three adapters (a `click` CLI, an ArcGIS Pro `.pyt`
GUI, and the importable core itself).

---

## Feature Implementation Tracker

Status against the 79-tool environmental monitoring roadmap, as of **2026-07-03**. The
Attachment Harvester is a separate, fully-shipped domain not counted in the 79 tools.

| Status | Count | Notes |
|--------|------:|-------|
| Fully implemented (CLI command + core module + tests) | ~100 | ~79 numbered roadmap tools + 21 headless post-roadmap tools |
| Foundation laid (partial code, not fully wired) | 0 | |
| **Planned** (spec / plan written, not yet coded) | 0 | BatchEDDImport folded into Tool 2.2 `batch-import-workbooks` — see ADR-0048 |
| Not started (no spec or plan) | 0 | excludes §11 AI tools + geostatistical Phase 5 |
| **Catalog total (§2–11)** | **~79** | |

The codebase now ships **103 `core/envmon/` + 10 `core/agol/` modules (113 total)**,
**107 registered CLI commands** (leaf commands under `envmon`/`agol`/top-level; 110 if the 4
`manage-callout-overrides` subcommands are counted individually), and a **1522-test** arcpy-free
suite. For the authoritative per-tool breakdown see
[`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) (the headline counts
here have advanced past that snapshot — a large batch of tools merged 2026-06-28 through
2026-07-02, PRs #81/#84/#88/#92/#93/#95/#96/#102/#118/#119).

<details>
<summary>Fully implemented — headless (CLOUD / HYBRID)</summary>

| Tool | Roadmap # | CLI command |
|------|-----------|-------------|
| InspectWorkbook | 1 | `envmon inspect` |
| CreateWorkbookParserProfile (draft reader) | 9 | `envmon parser-profile` |
| FigureSpecTemplate | 10 | `envmon figure-spec` |
| ValidateEnvConfig | 10.2 | `envmon validate-config` |
| ManageAnalyteDictionary | 3.3 | `envmon manage-analyte-dict` |
| ManageScreeningLevels | 3.x | `envmon manage-screening-levels` |
| ReconcileSampleLocations | 3.2 | `envmon reconcile-locations` *(HYBRID)* |
| ValidateAndConvertUnits | 3.5 | `envmon validate-units` |
| EvaluateDuplicateRPD | 3.6 | `envmon evaluate-rpd-qa` / `envmon evaluate-rpd` |
| ApplyScreeningLevels | 3.x | `envmon apply-screening` |
| CompareMonitoringEvents | 4.7 | `envmon compare-events` |
| IdentifyMonitoringDataGaps | 4.10 | `envmon identify-data-gaps` |
| CompareScheduleVsActual | — | `envmon compare-schedule-vs-actual` |
| ProcessLevelLoop | 8.1 | `envmon process-level-loop` |
| ValidateRTKSurvey | 8.4 | `envmon validate-rtk-survey` |
| DroneGCPCheckpointQA | 8.7 | `envmon drone-checkpoint-qa` |
| ReconcileSurvey123AndLabResults | 2.6 | `envmon reconcile-survey123-lab` |
| BuildSurvey123XLSFormFromConfig | 7.1a | `envmon build-survey-form` |
| EvaluateReportReadiness | 9.0b | `envmon evaluate-readiness` |
| ExportAnalyticalSummaryTables | 9.1 | `envmon export-report-format-summary-tables` / `envmon export-summary` |
| GenerateMonitoringEventReport | — | `envmon generate-event-report` |
| ExportGeoJSONResults | — | `envmon export-geojson` |
| ValidateScheduleYAML | — | `envmon validate-schedule` |
| RunHistoryReport / Query | 10.1 | `envmon run-history-report` / `envmon run-history` |
| WriteRunHistory | 10.5 | not implemented -- `RunHistory.write()` exists (`core/common/run_history.py`) but has no production caller; `run_history.csv` is user-populated today (see ADR-0017 status update, issue #104) |
| PublishEnvironmentalLayersToAGOL | 6.1 | `agol publish-layer` |
| BuildGroundwaterElevationEvent | 4.1 | `envmon build-gwe-event` |
| EstimateGWFlowDirection | 4.3 | `envmon estimate-gw-flow-direction` (DRAFT) |
| BuildAnalyticalExceedanceEvent | 4.4 | `envmon build-exceedance-event` |
| GenerateWellTrendCharts | 4.6 | `envmon generate-trend-charts` |
| SelectSoilIntervalsForMapping | 4.8 | `envmon select-soil-intervals` |
| BuildMaxResultMapDataset | 4.9 | `envmon build-max-result-dataset` |
| GenerateArcadeLabelExpressions | 5.4 | `envmon generate-arcade-labels` |
| GeneratePythonLabelExpressions | 5.4b | `envmon generate-python-labels` |
| BuildAnalyticalKey | 5.5 | `envmon build-analytical-key` |
| BuildReportFigurePackage | 5.7 | `envmon build-report-package` |
| RegisterSourceDocuments | 2.5 | `envmon register-source-doc` |
| BatchImportEnvironmentalWorkbooks | 2.2 | `envmon batch-import-workbooks` |
| MigrateLegacyMonitoringData | 2.4 | `envmon migrate-legacy-data` |
| CreateSurvey123SamplingEvent | 2.7 | `envmon create-sampling-event` |
| SurveyToWellElevationUpdate | 8.5 | `envmon survey-to-well-elevation` *(HYBRID — `--gdb` write path is LOCAL)* |
| RegisterDroneFlight | 8.6 | `envmon register-drone-flight` *(HYBRID — GDB write path is LOCAL)* |
| ImportDroneProducts | 8.8 | `envmon validate-drone-products` (headless QA half; the GDB-writing half is LOCAL — see below) |
| ImportFieldBoringLogs | 8.0b | `envmon validate-boring-logs` (headless QA half; the GDB-writing half is LOCAL — see below) |
| CreateBoringLogDatabase | 8.0a | `envmon create-boring-log-db` |
| GenerateBoringLogPDFs | 8.0c | `envmon gen-boring-logs` (Markdown/CSV assembly; PDF conversion is a downstream step) |
| SyncFieldAttachments | 6.5 | `envmon index-field-attachments` (envmon-side index; the AGOL download half is the shipped attachment harvester) |
| CreateSamplingEventPlan | 7.2 | `envmon create-sampling-plan` |
| ReconcileFieldAndLabData | 7.3 | `envmon reconcile-field-lab` |
| GenerateWellInspectionPhotoReport | 7.4 | `envmon generate-inspection-report` (photo embedding needs Pillow — `pip install "autogis[report]"`) |
| BuildMonitoringReportAppendix | 9.2 | `envmon build-report-appendix` |
| GenerateEventChangeLog | 9.3 | `envmon generate-event-changelog` |
| IngestReviewerMapComments | 9.4 | `envmon ingest-reviewer-comments` |
| GenerateSyntheticEnvWorkbook | 10.6 | `envmon gen-synthetic-workbook` |
| RunEnvJobQueue | 10.4 | `envmon generate-job-queue` |
| GenerateDraftPlumeBoundary | 4.5 | `envmon draft-plume-boundary` *(HYBRID — `--gdb` write path is LOCAL; DRAFT output)* |
| RefreshMonitoringDashboardData | 6.4 | `agol refresh-dashboard` |
| AuditAGOLSchemaAgainstLocalConfig | 6.6 | `agol audit-schema` |
| PublishDashboardFromSpec | 6.8 | `agol publish-dashboard` |
| AuditAGOLItemDependencies | 6.9 | `agol audit-dependencies` |
| PromoteAGOLDataBetweenStages | 6.10 | `agol promote` |
| UpdateWellElevationsFromLevelLoop | 8.2 | `envmon update-well-elevations` *(HYBRID — `--gdb` write path is LOCAL)* |
| UpdateAGOLWebMapFromFigureSpec | 6.3 | `agol update-webmap` (visibility + definition-query config only; no popup/label/symbology in the canonical FigureSpec) |
| CreateHostedViewsForStakeholders | 6.11 | `agol create-views` |
| SyncAGOLFeatureLayerToGDB | 6.2 | `agol sync-to-gdb` *(HYBRID — `--gdb` upsert path is LOCAL; attribute sync only — attachments stay with `autogis harvest` + `envmon index-field-attachments`)* |

Post-roadmap extras (not counted in the 79-tool catalog):

| Tool | CLI command |
|------|-------------|
| GWLevelSummary | `envmon gw-level-summary` |
| BuildComplianceSummaryTable | `envmon build-compliance-table` |
| ExportEnvDataToGeoPackage | `envmon export-geopackage` |
| ExportLabAnalyticalRequest | `envmon export-lab-request` |
| GenerateQCSampleSummary | `envmon generate-qc-summary` |
| GenerateRegulatorySubmissionTables | `envmon generate-reg-tables` |
| GenerateSiteNarrative | `envmon generate-site-narrative` |
| ListAvailableEnvTools | `envmon list-tools` |
| MergeEventResults | `envmon merge-event-results` |
| ValidateFieldDataCompleteness | `envmon validate-field-completeness` |
| ExportComparisonExcel | `envmon export-comparison-excel` |
| DraftParserProfileFromWorkbook | `envmon draft-parser-profile` |
| RTKControlCheckReport | `envmon rtk-control-check` |
| GeneratePortfolioMetrics | `envmon portfolio-metrics` |
| EvaluateGroundwaterSurfaceModels | `envmon evaluate-gw-models` |
| ExportSurveyToCADGIS | `envmon export-survey-cad` |
| GenerateWellInspectionReports | `envmon well-inspection-report` |

</details>

<details>
<summary>Fully implemented — ArcGIS Pro (LOCAL)</summary>

| Tool | Roadmap # | CLI command (arcpy-guarded; primary UI is the `.pyt`) |
|------|-----------|--------------------------------------------------------|
| ImportLabEDD | 2.3 | `envmon import-edd` |
| ImportToGDB | 2/3 | `envmon import-gdb` |
| BuildCurrentEvent | 4 | `envmon build-event` |
| BuildAnalyticalCallouts | 5.1 | `envmon build-callouts` |
| OptimizeCalloutPlacement | 5.2 | `envmon optimize-callouts` |
| ManageCalloutPlacementOverrides | 5.3 | `envmon manage-callout-overrides` |
| GenerateDraftGWContours | 4.2 | `envmon gw-contours` |
| ExportFigures | 6 | `envmon export-figures` |
| FullPipeline | 7 | `envmon full-pipeline` |
| ValidateEnvironmentalDatabase | 3.1 | `envmon validate-db` |
| UpgradeEnvMonitoringGDBSchema | 10.3 | `envmon upgrade-schema` |
| ExportEventDatabaseSnapshot | 9.0a | `envmon export-snapshot` |
| ImportRTKSurveyPoints | 8.3 | `envmon import-rtk-survey` |
| RouteSurvey123Submission | 7.1b | `envmon route-survey123` |
| ImportDroneProducts | 8.8 | `envmon import-drone-products` (GDB-writing half; see `validate-drone-products` above) |
| ImportFieldBoringLogs | 8.0b | `envmon import-boring-logs` (GDB-writing half; see `validate-boring-logs` above) |
| BuildDashboardDataMart | 6.7 | `envmon build-dashboard-data-mart` |
| BuildCADExportPackage | 8.9 | `envmon build-cad-package` (mapping/CRS logic only; arcpy Export-to-CAD call not yet wired — see issue #105) |
| ExportContoursForCivil3D | 8.2 | `envmon export-civil3d` (PNEZD CSV + projection note headless; `--landxml` guarded, arcpy leg not yet wired — see issue #105) |
| UpdateLayoutDynamicText | 5.8 | `envmon update-layout-text` (CLI-first per ADR-0039; wraps the shipped `layout_manager.update_layout_text`) |
| BuildFieldMapsMonitoringProject | 7.1 | `envmon build-fieldmaps` (CLI-first per ADR-0039; plan is arcpy-free + headless via `--dry-run`, GDB provisioning needs arcpy; publish via `agol publish-layer`) |
| GenerateSiteMapSeries | 5.6 | `envmon gen-map-series` (CLI-first per ADR-0039; planner + `--dry-run` are arcpy-free; export loop replays the ExportFigures chain) |

</details>

<details>
<summary>Foundation laid / partial</summary>

| Tool | Roadmap # | What exists | What's missing |
|------|-----------|-------------|----------------|
| *(none currently)* | | | |

Note: BuildGroundwaterElevationEvent (4.1), BuildAnalyticalExceedanceEvent (4.4),
UpdateWellElevationsFromLevelLoop (8.2), CreateHostedViewsForStakeholders (6.11, the
last of the Dashboard-consuming-tools group), and UpdateLayoutDynamicText (5.8) have
all shipped (see *Fully implemented* above).

</details>

<details>
<summary>Planned — spec and/or implementation plan written, not yet coded</summary>

Specs live in [`docs/superpowers/specs/`](docs/superpowers/specs/);
plans in [`docs/superpowers/plans/`](docs/superpowers/plans/).

**Post-roadmap / infrastructure** (not counted in the 79-tool catalog)

BatchEDDImport is no longer a separate planned tool — it was **folded into
Tool 2.2 `batch-import-workbooks`** (2026-07-03): the existing command gained
an alternate `--edd-dir`/`--profile`/`--site`/`--pattern` input mode instead
of a new module/command (ADR-0048; the 2026-06-28 plan is superseded).

Note: SessionCoordinationTier1 has shipped (`.claude/coordination/coord_cli.py`,
`hook_check.py`, `registry.py` — see the *Worktrees & session coordination* section of
`CLAUDE.md`); it is separate infrastructure tooling, not an `autogis envmon` CLI command, so it
is not carried in the tables above. A remediation follow-up (parallel-session edge cases) is
still design-only.

</details>

<details>
<summary>Not started — no spec or implementation plan</summary>

**No roadmap tools remain here** outside the two phase-gated groups below —
SyncAGOLFeatureLayerToGDB (6.2), the last one, shipped 2026-07-03 (`agol sync-to-gdb`,
ADR-0044).

ValidateSurveyDeliverable needs no new code: it was folded into the shipped
`ValidateRTKSurvey` (8.4) — see
[`docs/superpowers/specs/2026-06-28-roadmap-duplicate-tools-fold-decision.md`](docs/superpowers/specs/2026-06-28-roadmap-duplicate-tools-fold-decision.md).

**AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec, AIMapReviewChecklist
— all deferred pending LLM seam design

**Conditional / geostatistical (Phase 5):** 8 tools (kriging / EBK / surface modeling) — blocked on
architecture review; see `docs/CONDITIONAL_TOOLS_REVIEW.md`

**These two groups are a separate future development phase, not a backlog to pick from.**
Do not start implementation on any tool listed above without an explicit phase-gate
decision — the codebase is refined thoroughly first. See `CLAUDE.md` for the standing
policy.

</details>

Full roadmap detail: [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) ·
[`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md)

---

## Architecture

### One core, three adapters

- **Shared substrate:** `autogis.core.common` — config validation, QA reporting, logging, run
  history, and the schema dataclass package
- **Domain modules:** `autogis.core.harvest` (Attachment Harvester), `autogis.core.envmon`
  (97 modules), and `autogis.core.agol` (publishing, 9 modules) sit on top of common
- **Three adapters:** `autogis.adapters.cli` (Click CLI) and `autogis.adapters.toolbox.pyt`
  (ArcGIS Pro GUI) both construct and validate the *same* config dataclasses and call the *same*
  core functions — the two interfaces cannot drift

### Design invariants

- **Arcpy-free core** (ADR-0002): importing any `core` module succeeds without `arcpy` or `arcgis`
  installed. Both are lazy-imported inside function bodies. `arcgis` is the optional `cloud` extra;
  `arcpy` ships with ArcGIS Pro and is never a pip dependency.
- **Config as code** (ADR-0009): all configuration through validated dataclasses; no magic strings
  or config drift between adapters.
- **Idempotent imports**: re-running any import tool does not duplicate data.
- **Source-cell traceability**: every analytical result links back to its originating Excel row/column.

---

## Runtime Matrix

Every tool declares a runtime class; the suite enforces it at the adapter layer. Runtime classes
and backing modules below are taken directly from `autogis/runtime/capabilities.py` and
`autogis/adapters/cli.py`.

### Headless (CLOUD / HYBRID) — run anywhere without ArcGIS Pro

| Command | Runtime | Backing module |
|---------|---------|----------------|
| `autogis harvest` | HYBRID | `core/harvest/` |
| `autogis envmon inspect` | CLOUD | `core/envmon/excel_workbook_inspector.py` |
| `autogis envmon parser-profile` | CLOUD | `core/envmon/excel_profile_reader.py` |
| `autogis envmon figure-spec` | CLOUD | `core/common/config.py` (`FigureSpec`) |
| `autogis envmon validate-config` | CLOUD | `core/envmon/validate_config.py` |
| `autogis envmon manage-analyte-dict` | CLOUD | `core/envmon/manage_analyte_dict.py` |
| `autogis envmon manage-screening-levels` | CLOUD | `core/envmon/manage_screening_levels.py` |
| `autogis envmon reconcile-locations` | HYBRID | `core/envmon/reconcile_locations.py` |
| `autogis envmon validate-units` | CLOUD | `core/envmon/validate_units.py` |
| `autogis envmon evaluate-rpd-qa` | CLOUD | `core/envmon/evaluate_rpd_qa.py` |
| `autogis envmon evaluate-rpd` | CLOUD | `core/envmon/evaluate_rpd.py` |
| `autogis envmon apply-screening` | CLOUD | `core/envmon/apply_screening.py` |
| `autogis envmon compare-events` | CLOUD | `core/envmon/compare_events.py` |
| `autogis envmon identify-data-gaps` | CLOUD | `core/envmon/data_gaps.py` |
| `autogis envmon compare-schedule-vs-actual` | CLOUD | `core/envmon/schedule_vs_actual.py` |
| `autogis envmon validate-schedule` | CLOUD | `core/envmon/validate_schedule.py` |
| `autogis envmon process-level-loop` | CLOUD | `core/envmon/level_loop.py` |
| `autogis envmon validate-rtk-survey` | CLOUD | `core/envmon/validate_rtk_survey.py` |
| `autogis envmon drone-checkpoint-qa` | CLOUD | `core/envmon/drone_checkpoint_qa.py` |
| `autogis envmon reconcile-survey123-lab` | CLOUD | `core/envmon/reconcile_survey123_lab.py` |
| `autogis envmon build-survey-form` | CLOUD | `core/envmon/survey123_form_builder.py` |
| `autogis envmon evaluate-readiness` | CLOUD | `core/envmon/evaluate_readiness.py` |
| `autogis envmon export-summary` | CLOUD | `core/envmon/export_summary.py` |
| `autogis envmon export-report-format-summary-tables` | CLOUD | `core/envmon/export_summary_tables.py` |
| `autogis envmon generate-event-report` | CLOUD | `core/envmon/generate_event_report.py` |
| `autogis envmon export-geojson` | CLOUD | `core/envmon/export_geojson.py` |
| `autogis envmon run-history-report` | CLOUD | `core/envmon/history_report.py` |
| `autogis envmon run-history` | CLOUD | `core/common/run_history.py` |
| `autogis agol publish-layer` | — (AGOL auth) | `core/agol/publish.py` |
| `autogis envmon build-gwe-event` | CLOUD | `core/envmon/build_gwe_event.py` |
| `autogis envmon gw-level-summary` | CLOUD | `core/envmon/gw_level_summary.py` |
| `autogis envmon estimate-gw-flow-direction` | CLOUD | `core/envmon/estimate_gw_flow_direction.py` (DRAFT) |
| `autogis envmon build-exceedance-event` | CLOUD | `core/envmon/build_exceedance_event.py` |
| `autogis envmon generate-trend-charts` | CLOUD | `core/envmon/well_trend_charts.py` |
| `autogis envmon select-soil-intervals` | CLOUD | `core/envmon/soil_interval_selector.py` |
| `autogis envmon export-comparison-excel` | CLOUD | `core/envmon/export_comparison_excel.py` |
| `autogis envmon build-max-result-dataset` | CLOUD | `core/envmon/max_result_dataset.py` |
| `autogis envmon generate-arcade-labels` | CLOUD | `core/envmon/arcade_label_generator.py` |
| `autogis envmon generate-python-labels` | CLOUD | `core/envmon/python_label_generator.py` |
| `autogis envmon build-analytical-key` | CLOUD | `core/envmon/build_analytical_key.py` |
| `autogis envmon build-report-package` | CLOUD | `core/envmon/report_figure_package.py` |
| `autogis envmon register-source-doc` | CLOUD | `core/envmon/source_registry.py` |
| `autogis envmon batch-import-workbooks` | CLOUD | `core/envmon/batch_workbook_importer.py` |
| `autogis envmon migrate-legacy-data` | CLOUD | `core/envmon/legacy_migrator.py` |
| `autogis envmon draft-parser-profile` | CLOUD | `core/envmon/excel_workbook_inspector.py` |
| `autogis envmon create-sampling-plan` | CLOUD | `core/envmon/sampling_plan.py` |
| `autogis envmon reconcile-field-lab` | CLOUD | `core/envmon/field_lab_reconciler.py` |
| `autogis envmon build-report-appendix` | CLOUD | `core/envmon/report_appendix_builder.py` |
| `autogis envmon generate-event-changelog` | CLOUD | `core/envmon/event_changelog.py` |
| `autogis envmon ingest-reviewer-comments` | CLOUD | `core/envmon/ingest_reviewer_comments.py` |
| `autogis envmon gen-synthetic-workbook` | CLOUD | `core/envmon/synthetic_workbook.py` |
| `autogis envmon generate-job-queue` | CLOUD | `core/envmon/job_queue.py` |
| `autogis envmon build-compliance-table` | CLOUD | `core/envmon/compliance_summary.py` |
| `autogis envmon export-geopackage` | CLOUD | `core/envmon/geopackage_exporter.py` |
| `autogis envmon export-lab-request` | CLOUD | `core/envmon/lab_request_exporter.py` |
| `autogis envmon generate-qc-summary` | CLOUD | `core/envmon/qc_sample_summary.py` |
| `autogis envmon generate-reg-tables` | CLOUD | `core/envmon/regulatory_table_builder.py` |
| `autogis envmon generate-site-narrative` | CLOUD | `core/envmon/site_narrative_generator.py` |
| `autogis envmon list-tools` | CLOUD | `core/envmon/tool_registry.py` |
| `autogis envmon merge-event-results` | CLOUD | `core/envmon/event_results_merger.py` |
| `autogis envmon validate-field-completeness` | CLOUD | `core/envmon/field_completeness_validator.py` |
| `autogis envmon validate-drone-products` | CLOUD | `core/envmon/import_drone_products.py` (QA-only half; GDB write is LOCAL) |
| `autogis envmon validate-boring-logs` | CLOUD | `core/envmon/import_boring_logs.py` (QA-only half; GDB write is LOCAL) |
| `autogis envmon create-boring-log-db` | CLOUD | `core/envmon/create_boring_log_database.py` |
| `autogis envmon index-field-attachments` | CLOUD | `core/envmon/index_field_attachments.py` |
| `autogis envmon survey-to-well-elevation --wells-csv` | HYBRID | `core/envmon/survey_to_well_elevation.py` (`--gdb` write path is LOCAL) |
| `autogis envmon register-drone-flight --dry-run` | HYBRID | `core/envmon/register_drone_flight.py` (GDB write path is LOCAL) |
| `autogis envmon rtk-control-check` | CLOUD | `core/envmon/rtk_control_check.py` |
| `autogis envmon portfolio-metrics` | CLOUD | `core/envmon/portfolio_metrics.py` |
| `autogis envmon evaluate-gw-models` | CLOUD | `core/envmon/evaluate_gw_models.py` |
| `autogis envmon export-survey-cad` | CLOUD | `core/envmon/export_survey_cad.py` |
| `autogis envmon well-inspection-report` | CLOUD | `core/envmon/well_inspection_report.py` |
| `autogis envmon generate-inspection-report` | CLOUD | `core/envmon/well_inspection_photo_report.py` (photo embedding needs Pillow) |

### ArcGIS Pro primary (LOCAL) — arcpy-guarded on the CLI

| Command | Backing module |
|---------|----------------|
| `autogis envmon import-gdb` | `core/envmon/import_to_gdb.py` |
| `autogis envmon build-event` | `core/envmon/build_current_event.py` |
| `autogis envmon build-callouts` | `core/envmon/build_figure_dataset.py` |
| `autogis envmon optimize-callouts` | `core/envmon/callout_collision.py`, `callout_geometry.py` |
| `autogis envmon manage-callout-overrides` | `core/envmon/manage_callout_overrides.py` |
| `autogis envmon gw-contours` | `core/envmon/groundwater_contours.py` |
| `autogis envmon export-figures` | `core/envmon/export_figures.py` |
| `autogis envmon full-pipeline` | `core/envmon/import_to_gdb.py` (orchestrator) |
| `autogis envmon validate-db` | `core/envmon/validate_database.py` |
| `autogis envmon upgrade-schema` | `core/envmon/upgrade_schema.py` |
| `autogis envmon export-snapshot` | `core/envmon/export_snapshot.py` |
| `autogis envmon import-edd` | `core/envmon/edd_importer.py` |
| `autogis envmon import-rtk-survey` | `core/envmon/import_rtk_survey.py` |
| `autogis envmon route-survey123` | `core/envmon/normalize_survey123.py` |
| `autogis envmon import-drone-products` | `core/envmon/import_drone_products.py` |
| `autogis envmon import-boring-logs` | `core/envmon/import_boring_logs.py` |
| `autogis envmon build-dashboard-data-mart` | `core/envmon/dashboard_data_mart.py` |
| `autogis envmon survey-to-well-elevation --gdb` | `core/envmon/survey_to_well_elevation.py` (HYBRID command; headless via `--wells-csv`) |
| `autogis envmon register-drone-flight` (non-dry-run) | `core/envmon/register_drone_flight.py` (HYBRID command; headless via `--dry-run`) |

LOCAL commands guard on `arcpy` and redirect to the `.pyt` toolbox inside ArcGIS Pro when it is
absent. `import-edd`, `import-rtk-survey`, `route-survey123`, `import-drone-products`,
`import-boring-logs`, and `build-dashboard-data-mart` are LOCAL-only and will print the standard
guard message if run headless — use the `.pyt` toolbox or the guarded CLI inside Pro.

---

## Installation

### Headless / cloud

For the Attachment Harvester and all CLOUD-class envmon tools:

```bash
pip install autogis[cloud]    # pulls in the arcgis Python API
```

### ArcGIS Pro

`arcpy` ships with Pro and is not pip-installable. Install `autogis` editable into a cloned
`arcgispro-py3` conda environment so the toolbox can import the package like any library:

```bash
# inside a cloned arcgispro-py3 environment
pip install -e .
```

See [`docs/pro-install.md`](docs/pro-install.md) for the complete setup guide — cloning the
environment, registering the `.pyt`, and the toolbox cache/reload gotcha.

### Development

```bash
pip install -e ".[dev]"
python -m pytest -q           # 1522 tests (see: python -m pytest --collect-only -q)
```

---

## CLI Reference

`autogis` exposes the Harvester at the top level and envmon tools under an `envmon` sub-group;
publishing lives under an `agol` sub-group. `autogis-harvest` is preserved as a legacy alias.

### Attachment Harvester

```bash
autogis harvest --config my-job.yaml
autogis harvest --config my-job.yaml --incremental
autogis harvest --config my-job.yaml --where "Status = 'Complete'" --out ./batch
```

### Headless envmon tools

```bash
# Workbook inspection & config
autogis envmon inspect <workbook.xlsx>
autogis envmon parser-profile <workbook.xlsx>
autogis envmon figure-spec <output.yaml>
autogis envmon validate-config <site-config.yaml>

# Validation & QA
autogis envmon validate-units --analytes <analyte-dict.yaml> --screening <levels.yaml>
autogis envmon reconcile-locations <site-config.yaml> <workbook.xlsx> --profile <profile.yaml>
autogis envmon manage-analyte-dict
autogis envmon manage-screening-levels
autogis envmon evaluate-rpd-qa --samples-csv <samples.csv> --results-csv <results.csv>
autogis envmon apply-screening --results-csv <results.csv> --screening <levels.yaml> --output <out.csv>

# Analysis & reporting
autogis envmon compare-events --results-csv <results.csv> --output <out.csv>
autogis envmon identify-data-gaps --schedule <schedule.yaml> --results-csv <results.csv>
autogis envmon compare-schedule-vs-actual --schedule <schedule.yaml> --results-csv <results.csv> --output <out.csv>
autogis envmon process-level-loop --observations-csv <survey.csv> --run-id <id> --site-id <id> --survey-date <YYYY-MM-DD> --benchmark-id <pt> --known-elevation <z>
autogis envmon evaluate-readiness --site-id <id> --run-history <run_history.csv>
autogis envmon generate-event-report --site <id> --event <id> --output <report.md>
autogis envmon export-geojson --results-csv <results.csv> --coords-csv <coords.csv> --output <out.geojson>
autogis envmon export-report-format-summary-tables --results-csv <results.csv> --output <out.xlsx>
autogis envmon run-history --run-history <run_history.csv> --format table
autogis envmon portfolio-metrics --run-history <run_history.csv> --required-tool import-edd --required-tool validate-units
autogis envmon evaluate-gw-models --observations <predictions.csv> --tolerance-ft 0.5

# Field & survey
autogis envmon build-survey-form --site <site.yaml> --analytes <analytes.yaml> --event <event.yaml> --out <form.xlsx>
autogis envmon validate-rtk-survey <points.csv>
autogis envmon drone-checkpoint-qa --checkpoints <gcps.csv>
autogis envmon rtk-control-check --control-points <control.csv> --horizontal-tolerance-ft 0.05 --vertical-tolerance-ft 0.10
autogis envmon export-survey-cad <points.csv> --feature-code-map <map.yaml> --output-dir <out>
autogis envmon well-inspection-report --wells-csv <wells.csv> --site <id> --output-dir <out> --maintenance-log-csv <log.csv>
autogis envmon generate-inspection-report --inspections <inspections.csv> --manifest <manifest.csv> --harvest-dir <dir> --site <id> --out <report.xlsx>
autogis envmon reconcile-survey123-lab --survey <s123.csv> --edd <lab.csv> --edd-profile <profile.yaml> --site <id>
autogis envmon survey-to-well-elevation <rtk.csv> --site <id> --wells-csv <wells.csv>       # headless
autogis envmon register-drone-flight <flight.yaml> --gdb <gdb> --dry-run                    # headless
autogis envmon validate-boring-logs <input_dir>
autogis envmon validate-drone-products --manifest <products.csv> --flight-id <id>
autogis envmon create-boring-log-db <boring.sqlite>                # --validate to check an existing DB
autogis envmon index-field-attachments <manifest.csv> --db <envmon.sqlite>

# Batch intake & planning
autogis envmon draft-parser-profile <workbook.xlsx> --output <profile.yaml>
autogis envmon batch-import-workbooks --manifest <manifest.csv> --output-dir <out>
autogis envmon migrate-legacy-data --input-csv <legacy.csv> --output <out.csv>
autogis envmon register-source-doc --file <doc.pdf> --site <id> --event <id> --tool <name>
autogis envmon create-sampling-plan --wells-csv <wells.csv> --analyte-groups <groups.yaml> --event-date <YYYY-MM-DD> --samples-output <samples.csv> --bottles-output <bottles.csv>
autogis envmon reconcile-field-lab --field-csv <field.csv> --lab-csv <lab.csv> --output <out.csv>

# Analysis & cartography extras
autogis envmon build-gwe-event --water-levels <levels.csv> --event-date <YYYY-MM-DD> --out <out.csv>
autogis envmon gw-level-summary --elevations-csv <history.csv> --event-date <YYYY-MM-DD> --output <out.csv>
autogis envmon estimate-gw-flow-direction --wells-csv <wells.csv> --site-id <id> --event-date <YYYY-MM-DD> --run-id <id> --output <out.csv>
autogis envmon build-exceedance-event --results <results.csv> --screening-levels <levels.yaml> --out <out.csv>
autogis envmon generate-trend-charts --history-csv <history.csv> --out <charts.xlsx>
autogis envmon select-soil-intervals --results-csv <soil.csv> --out <out.csv>
autogis envmon build-analytical-key --analyte-dict <analytes.yaml> --screening-levels <levels.yaml> --matrix GW
autogis envmon generate-arcade-labels --analytes "Benzene,PCE" --out <labels.json>
autogis envmon generate-python-labels --analytes "Benzene,PCE" --out <labels.json>

# Reporting extras
autogis envmon build-report-appendix --results <results.csv> --out <out.xlsx>
autogis envmon generate-event-changelog --prior-csv <prior.csv> --current-csv <current.csv> --out <changelog.csv>
autogis envmon ingest-reviewer-comments <comments.xlsx> --out <out.csv>
autogis envmon generate-job-queue --manifest <manifest.yaml> --output <queue.json>
autogis envmon gen-synthetic-workbook --site-id <id> --out <synthetic.xlsx>
autogis envmon list-tools

# Publishing
autogis agol publish-layer --source <data> --title "<service title>"
```

### Pro-guarded tools (require arcpy)

Run inside ArcGIS Pro / the `.pyt` toolbox. When run headless these guard on `arcpy`:

```bash
autogis envmon import-gdb <site-config.yaml> <workbook.xlsx>
autogis envmon build-event <site-config.yaml>
autogis envmon validate-db <geodatabase>
autogis envmon upgrade-schema <geodatabase>
autogis envmon export-snapshot <geodatabase>
# build-callouts, optimize-callouts, gw-contours, export-figures, full-pipeline follow the same pattern
```

> `import-edd`, `import-rtk-survey`, `route-survey123`, `import-drone-products`,
> `import-boring-logs`, and `build-dashboard-data-mart` are also Pro-only; the `.pyt` toolbox is
> the primary UI for all LOCAL commands. `survey-to-well-elevation --gdb` and
> `register-drone-flight` (non-dry-run) are HYBRID: headless without `--gdb` /
> with `--dry-run`, Pro-only when writing to the geodatabase.

---

## Attachment Harvester

Bulk-downloads photos and attachments from a feature layer for field-inspection workflows.
Runs without ArcGIS Pro via the AGOL REST API.

Copy `autogis/config/inspection-job.example.yaml` and edit the key fields:

```yaml
connection:
  profile: my-agol-profile    # stored ArcGIS profile, or null to use env vars

layer:
  item_id: "1a2b3c4d5e6f"     # feature layer item ID (or use `url` instead)
  where: "1=1"

output:
  directory: "./downloads"
  group_template: "{Status}"
  filename_template: "{InspectionID}_{OBJECTID}_{name}"

options:
  incremental: true
```

Each run writes photos plus `manifest.csv` and `manifest.json` into the output directory and
prints `Downloaded: X  Skipped: Y  Failed: Z`. Re-running skips files already on disk, so
failed downloads retry cleanly.

Never put passwords in the config file. Use a stored ArcGIS profile or the `AGOL_USER` /
`AGOL_PASS` environment variables.

---

## Environmental Monitoring Tools

Converts irregular Excel workbooks into a normalized file geodatabase, QA reports, analytical
callout feature classes, groundwater labels, DRAFT potentiometric contours, and exported PDF/PNG
figures — with full source-cell traceability and idempotent imports.

### Pipeline overview

```
Excel/CSV workbooks
    ↓
Headless prep (any machine)
    ├─ Workbook inspection         autogis envmon inspect
    ├─ Parser profile drafting     autogis envmon parser-profile
    ├─ Config validation           autogis envmon validate-config
    ├─ Unit validation             autogis envmon validate-units
    └─ Location reconciliation     autogis envmon reconcile-locations
    ↓
ArcGIS Pro / .pyt toolbox
    ├─ Import to GDB               autogis envmon import-gdb
    ├─ Build current event         autogis envmon build-event
    └─ Validate database           autogis envmon validate-db
    ↓
Analysis & cartography (Pro)
    ├─ GW contours                 autogis envmon gw-contours
    ├─ Analytical callouts         autogis envmon build-callouts
    ├─ Optimize placement          autogis envmon optimize-callouts
    └─ Export figures              autogis envmon export-figures
    ↓
QA, publish & report (headless)
    ├─ Compare vs prior event      autogis envmon compare-events
    ├─ Schedule vs actual          autogis envmon compare-schedule-vs-actual
    ├─ Event report (Markdown)     autogis envmon generate-event-report
    ├─ Publish to AGOL             autogis agol publish-layer
    └─ Evaluate readiness          autogis envmon evaluate-readiness
```

---

## Project Structure

```
autogis/
├── core/
│   ├── common/          # Config, QA, logging, run history, schema dataclasses
│   ├── harvest/         # Attachment Harvester (arcpy-free)
│   ├── envmon/          # Environmental monitoring — 97 modules
│   └── agol/            # AGOL publishing
├── adapters/
│   ├── cli.py           # Click CLI — all commands registered here
│   ├── toolbox.pyt      # ArcGIS Pro GUI
│   └── toolbox_core.py  # Seam between .pyt and core
├── config/
│   ├── inspection-job.example.yaml
│   ├── parser_profiles/        # Excel format definitions (YAML)
│   ├── screening_levels/       # Regulatory thresholds — ship null, populate before production
│   └── figure_specs/           # Cartography layout templates
├── runtime/             # arcpy / arcgis session providers + capability guards
└── tests/               # 1522 arcpy-free tests
```

### Key modules

| Path | Purpose |
|------|---------|
| `core/common/config.py` | `HarvestConfig`, `SiteConfig`, `ParserProfile`, `FigureSpec` — canonical dataclasses |
| `core/common/run_history.py` | `RunHistory` / `RunRecord` — append-only CSV run log |
| `core/common/schema/` | 5 modules (attachments, boring, drone, envmon, survey) exporting ~21 typed dataclasses |
| `core/envmon/` | 97 modules: inspectors, importers, validators, reconcilers, event builders, analysis, callout/contour/survey/drone tools |
| `adapters/cli.py` | Click CLI — constructs config dataclasses, guards LOCAL tools, dispatches to core |
| `runtime/capabilities.py` | `TOOLS` runtime map, `requires_arcpy()`, `require_runtime()` guards |

---

## Caveats

Read before relying on this suite in production.

**H281 parser profile is an unverified DRAFT — but the layout family it assumes is now
real-world cross-checked.**
`autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml` was built from the written spec
only; the real Glasgow workbook still hasn't been seen, so it still ships with a DRAFT banner
and `_TODO` markers. Its row-anchor guesses were corrected against a real, structurally-similar
workbook from a different site (Holiday Stationstore #272 / Circle K Store 2746272, Havre, MT)
via Tool 1 plus targeted verification — see that profile's banner for what changed and what's
still an unverified guess. Two fully anchor-verified sibling profiles now exist for that real
site: `H272_Havre_GW_Elevation.yaml` (verified *and* dispatchable — `GW_WATER_LEVEL_ONLY` is
already wired) and `H272_Havre_GW_Analytical.yaml` (anchors verified against the real workbook,
but not yet dispatchable — no `data_type` currently handles a GW-analytical-only sheet; see
that profile's banner for the concrete gap and what's needed to close it). Tool 1 + human
review is still mandatory before the first import of the actual Glasgow workbook — compare
every row/column anchor against the Tool 1 report, fix the remaining `_TODO`s, and clear the
DRAFT banner only once that specific file has been checked.

**Screening levels are partially populated.**
`autogis/config/screening_levels/screening_levels.yaml`'s GW section now carries real,
cited values for the 12 VPH/EPH fraction analytes (Benzene, Toluene, Ethylbenzene, Xylenes,
MTBE, Naphthalene, and the C5-C8/C9-C12/C9-C10/C9-C18/C19-C36/C11-C22 fractions) — sourced
from Montana DEQ's Tier 1 Risk-Based Screening Levels (RBSL) for groundwater (MDEQ, 2018),
verified against a real client workbook carrying that same table. TPH and TEH stay `value:
null` deliberately — Montana sets no bulk criterion for those, only for the fractions above,
so `null` there means "not applicable," not "not yet sourced." Everything else (metals, all
SOIL-matrix entries, EDB, 1,2-DCA) is still an unpopulated `_TODO` stub — no source workbook
has surfaced values for those yet. No regulatory number is invented in code; screening
comparison stays tri-state (NULL = not evaluable) until each remaining level is filled.

**`average_parent_and_duplicate` is statistically dubious with nondetects.**
It exists because the spec demands it. Every averaged value is flagged with a QA WARNING — keep
the flag.

**arcpy code paths are un-CI-able.**
The LOCAL (Pro-based) tools are not exercised in CI. Run them on a copy of real data inside Pro
before trusting outputs.

**Incremental harvest depends on feature service metadata.**
`--incremental` relies on `GlobalID` and `EditDate` fields. If absent, falls back to a full re-download.

---

## Documentation

| Document | Contents |
|----------|---------|
| [`docs/pro-install.md`](docs/pro-install.md) | Full Pro setup: env clone, toolbox registration, cache/reload |
| [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) | Feature completion status by tool (snapshot; headline counts above are current) |
| [`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md) | Phase 1–4 sequencing |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | Design specs — 43 features (architecture, algorithm, data-model decisions) |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Implementation plans — 86 features (step-by-step execution guides) |
| [`docs/adr/`](docs/adr/) | Architecture decision records — invariants, schema, config strategy, per-batch decisions (current list: the index in [`docs/adr/README.md`](docs/adr/README.md)) |
| [`docs/adr/logs/`](docs/adr/logs/) | Daily agent-decision logs — autonomous judgment calls recorded for audit (a supplement to ADRs, not a substitute) |

---

## Contributing

Test baseline: **1522 tests** (`python -m pytest --collect-only -q`). All core logic is
arcpy-free and CI-able.

```bash
python -m pytest -q
python -m pytest --cov=autogis --cov-report=term-missing

ruff check autogis/
mypy autogis/
```

See [`docs/adr/README.md`](docs/adr/README.md) for architectural guidelines before adding new tools.
