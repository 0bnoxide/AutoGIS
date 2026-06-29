# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123, delivered as a single suite:
the **Attachment Harvester** plus the **Environmental Monitoring tools**, folded into **one
`autogis` package** — one shared core with three adapters (a `click` CLI, an ArcGIS Pro `.pyt`
GUI, and the importable core itself).

---

## Feature Implementation Tracker

Status against the 79-tool environmental monitoring roadmap, as of **2026-06-28**. The
Attachment Harvester is a separate, fully-shipped domain not counted in the 79 tools.

| Status | Count | Notes |
|--------|------:|-------|
| Fully implemented (CLI command + core module + tests) | ~40 | ~34 numbered roadmap tools + 6 headless post-roadmap tools |
| Foundation laid (partial code, not fully wired) | ~4 | |
| **Planned** (spec / plan written, not yet coded) | ~17 | roadmap tools; plus 11 post-roadmap extras — see *Planned* list below |
| Not started (no spec or plan) | ~18 | excludes §11 AI tools + geostatistical Phase 5 |
| **Catalog total (§2–11)** | **~79** | |

The codebase now ships **50 `core/envmon/` modules**, **~43 registered CLI commands**, and a
**560-test** arcpy-free suite. For the authoritative per-tool breakdown see
[`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) (the headline counts
here have advanced past that snapshot).

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
| WriteRunHistory | 10.5 | internal (`core/common/run_history.py`, used by the readiness gate) |
| PublishEnvironmentalLayersToAGOL | 6.1 | `agol publish-layer` |

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

</details>

<details>
<summary>Foundation laid / partial</summary>

| Tool | Roadmap # | What exists | What's missing |
|------|-----------|-------------|----------------|
| BuildGroundwaterElevationEvent | 4.1 | `normalize_groundwater.py`, `build_current_event.py` | Dedicated event-builder + flags (Dry/NM/NS/anomalous) |
| CreateBoringLogDatabase | 8.0a | `schema/boring.py` (7 dataclasses) + upgrade-schema tables | Standalone create/validate tool |
| SyncFieldAttachments | 6.5 | Attachment harvester (separate domain) | Envmon-side attachment index table wiring |
| Dashboard consuming tools (6.8–6.11) | — | `schema/dashboard.py` (10 dataclasses) | Every consuming tool (6.7 BuildDashboardDataMart has a plan) |

Note: BuildAnalyticalExceedanceEvent (4.4) and UpdateWellElevationsFromLevelLoop (8.2) have
moved to *Planned* — both have specs/plans and partial code foundations.

</details>

<details>
<summary>Planned — spec and/or implementation plan written, not yet coded</summary>

Specs live in [`docs/superpowers/specs/`](docs/superpowers/specs/);
plans in [`docs/superpowers/plans/`](docs/superpowers/plans/).

**Data intake (§2)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| CreateSurvey123SamplingEvent | 2.7 | spec + plan |

**Analysis (§4)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| BuildAnalyticalExceedanceEvent | 4.4 | spec + plan *(partial code foundation)* |
| EstimateGWFlowDirection | 4.3 | spec + plan |
| BuildMaxResultMapDataset | 4.9 | spec + plan |

**Cartography (§5)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| BuildAnalyticalKey | 5.5 | plan |
| BuildReportFigurePackage | 5.7 | spec + plan |

**AGOL / cloud (§6)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| BuildDashboardDataMart | 6.7 | spec + plan |
| AuditAGOLItemDependencies | 6.9 | plan |

**Field / Survey123 (§7)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| GenerateWellInspectionPhotoReport | 7.4 | spec + plan |

**Survey / boring / drone (§8)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| ImportFieldBoringLogs | 8.0b | plan |
| UpdateWellElevationsFromLevelLoop | 8.2 | plan *(partial code foundation)* |
| SurveyToWellElevationUpdate | 8.5 | spec + plan |
| RegisterDroneFlight | 8.6 | plan |
| ImportDroneProducts | 8.8 | spec + plan |

**Reporting (§9)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| BuildMonitoringReportAppendix | 9.2 | spec + plan |
| IngestReviewerMapComments | 9.4 | spec + plan |

**Admin (§10)**

| Tool | Roadmap # | Artifact |
|------|-----------|---------|
| RunEnvJobQueue | 10.4 | plan |

**Post-roadmap / infrastructure** (not counted in the 79-tool catalog)

| Tool | Artifact |
|------|---------|
| BatchEDDImport (HYBRID) | plan |
| BuildComplianceSummaryTable | spec + plan |
| ExportEnvDataToGeoPackage | spec + plan |
| ExportLabAnalyticalRequest | spec + plan |
| GenerateQCSampleSummary | spec + plan |
| GenerateRegulatorySubmissionTables | spec + plan |
| GenerateSiteNarrative | spec + plan |
| ListAvailableEnvTools | spec + plan |
| MergeEventResults | spec + plan |
| ValidateFieldDataCompleteness | spec + plan |
| SessionCoordinationTier1 | spec + plan |

</details>

<details>
<summary>Not started — no spec or implementation plan</summary>

**Data intake (§2):** BatchImportEnvironmentalWorkbooks (2.2), MigrateLegacyMonitoringData (2.4),
RegisterSourceDocuments (2.5)

**Analysis (§4):** GenerateDraftPlumeBoundary (4.5), GenerateWellTrendCharts (4.6),
SelectSoilIntervalsForMapping (4.8)

**Cartography (§5):** GenerateArcadeLabelExpressions (5.4), GenerateSiteMapSeries (5.6),
UpdateLayoutDynamicText (5.8)

**AGOL / cloud (§6):** SyncAGOLFeatureLayerToGDB (6.2), UpdateAGOLWebMapFromFigureSpec (6.3),
RefreshMonitoringDashboardData (6.4), AuditAGOLSchemaAgainstLocalConfig (6.6),
PublishDashboardFromSpec (6.8), PromoteAGOLDataBetweenStages (6.10),
CreateHostedViewsForStakeholders (6.11)

**Field / Survey123 (§7):** BuildFieldMapsMonitoringProject (7.1), CreateSamplingEventPlan (7.2),
ReconcileFieldAndLabData (7.3)

**Survey / boring / drone / CAD (§8):** GenerateBoringLogPDFs (8.0c),
BuildCADExportPackage (8.9), ExportContoursForCivil3D, ValidateSurveyDeliverable

**Reporting (§9):** GenerateEventChangeLog (9.3)

**Admin (§10):** GenerateSyntheticEnvWorkbook (10.6)

**AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec, AIMapReviewChecklist
— all deferred pending LLM seam design

**Conditional / geostatistical (Phase 5):** 8 tools (kriging / EBK / surface modeling) — blocked on
architecture review; see `docs/CONDITIONAL_TOOLS_REVIEW.md`

</details>

Full roadmap detail: [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) ·
[`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md)

---

## Architecture

### One core, three adapters

- **Shared substrate:** `autogis.core.common` — config validation, QA reporting, logging, run
  history, and the schema dataclass package
- **Domain modules:** `autogis.core.harvest` (Attachment Harvester), `autogis.core.envmon`
  (50 modules), and `autogis.core.agol` (publishing) sit on top of common
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

LOCAL commands guard on `arcpy` and redirect to the `.pyt` toolbox inside ArcGIS Pro when it is
absent. `import-edd`, `import-rtk-survey`, and `route-survey123` are LOCAL-only and will print
the standard guard message if run headless — use the `.pyt` toolbox or the guarded CLI inside Pro.

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
python -m pytest -q           # 560 passing tests
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

# Field & survey
autogis envmon build-survey-form --site <site.yaml> --analytes <analytes.yaml> --event <event.yaml> --out <form.xlsx>
autogis envmon validate-rtk-survey <points.csv>
autogis envmon drone-checkpoint-qa --checkpoints <gcps.csv>
autogis envmon reconcile-survey123-lab --survey <s123.csv> --edd <lab.csv> --edd-profile <profile.yaml> --site <id>

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

> `import-edd`, `import-rtk-survey`, and `route-survey123` are also Pro-only; the `.pyt` toolbox
> is the primary UI for all LOCAL commands.

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
│   ├── envmon/          # Environmental monitoring — 50 modules
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
└── tests/               # 560 arcpy-free unit tests
```

### Key modules

| Path | Purpose |
|------|---------|
| `core/common/config.py` | `HarvestConfig`, `SiteConfig`, `ParserProfile`, `FigureSpec` — canonical dataclasses |
| `core/common/run_history.py` | `RunHistory` / `RunRecord` — append-only CSV run log |
| `core/common/schema/` | 5 modules (boring, dashboard, drone, envmon, survey) exporting ~30 typed dataclasses |
| `core/envmon/` | 50 modules: inspectors, importers, validators, reconcilers, event builders, analysis, callout/contour/survey/drone tools |
| `adapters/cli.py` | Click CLI — constructs config dataclasses, guards LOCAL tools, dispatches to core |
| `runtime/capabilities.py` | `TOOLS` runtime map, `requires_arcpy()`, `require_runtime()` guards |

---

## Caveats

Read before relying on this suite in production.

**H281 parser profile is an unverified DRAFT.**
`autogis/config/parser_profiles/H281_Glasgow_DataTables.yaml` was built from the written spec
only; the real workbook was not available. It ships with a DRAFT banner and `_TODO` markers.
Tool 1 + human review is mandatory before the first import — compare every row/column anchor
against the Tool 1 report, fix the `_TODO`s, and clear the DRAFT banner before importing real data.

**Screening levels ship null.**
Files under `autogis/config/screening_levels/` contain placeholder null values and `_TODO`
source citations. Populate them before production. No regulatory number is invented in code;
screening comparison stays tri-state (NULL = not evaluable) until the levels are filled.

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
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | Design specs — 45 features (architecture, algorithm, data-model decisions) |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Implementation plans — 76 features (step-by-step execution guides) |
| [`docs/adr/`](docs/adr/) | Architecture decision records — invariants, schema, config strategy (latest: ADR-0028) |

---

## Contributing

Test baseline: **560 passing tests**. All core logic is arcpy-free and CI-able.

```bash
python -m pytest -q
python -m pytest --cov=autogis --cov-report=term-missing

ruff check autogis/
mypy autogis/
```

See [`docs/adr/README.md`](docs/adr/README.md) for architectural guidelines before adding new tools.
