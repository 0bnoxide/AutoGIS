# AutoGIS

Automation tools for ArcGIS Pro and ArcGIS Online / Survey123, delivered as a single suite:
the **Attachment Harvester** plus the **Environmental Monitoring tools**, folded into **one
`autogis` package** — one shared core with three adapters (a `click` CLI, an ArcGIS Pro `.pyt`
GUI, and the importable core itself).

---

## Feature Implementation Tracker

Current status across the 79-tool environmental monitoring roadmap. The Attachment Harvester
is a separate, fully-shipped domain not counted in the 79 tools.

| Status | Count | % of catalog |
|--------|------:|-------------:|
| Fully implemented (CLI + core module + tests) | 17 | 22% |
| Foundation laid (schema or module exists, not fully wired) | 8 | 10% |
| Not started | ~54 | 68% |
| **Total named tools (§2–11)** | **~79** | |

**Phase summary:** Phase 1 (foundation) partially complete · Phase 2 (data intake) in progress ·
Phase 3 (maps/figures) planned · Phase 4 (field survey/AGOL) pending · Phase 5 (advanced
analytics) deferred

<details>
<summary>Fully implemented (17 tools)</summary>

| Tool | Roadmap # | CLI command |
|------|-----------|-------------|
| ImportLabEDD | 2.3 | `envmon import-edd` |
| ValidateEnvironmentalDatabase | 3.1 | `envmon validate-db` |
| ReconcileSampleLocations | 3.2 | `envmon reconcile-locations` |
| ManageAnalyteDictionary | 3.3 | `envmon manage-analyte-dict` |
| ValidateAndConvertUnits | 3.5 | `envmon validate-units` |
| EvaluateDuplicateRPD | 3.6 | `envmon evaluate-rpd-qa` |
| GenerateDraftGWContours | 4.2 | `envmon gw-contours` |
| CompareMonitoringEvents | 4.7 | `envmon compare-events` |
| IdentifyMonitoringDataGaps | 4.10 | `envmon identify-data-gaps` |
| BuildAnalyticalCallouts | 5.1 | `envmon build-callouts` |
| OptimizeCalloutPlacement | 5.2 | `envmon optimize-callouts` |
| ManageCalloutPlacementOverrides | 5.3 | `envmon manage-callout-overrides` |
| PublishEnvironmentalLayersToAGOL | 6.1 | `envmon publish-layer` |
| BuildSurvey123XLSFormFromConfig | 7.1a | `envmon build-survey-form` |
| ProcessLevelLoop | 8.1 | `envmon process-level-loop` |
| EvaluateReportReadiness | 9.0b | `envmon evaluate-readiness` |
| ExportAnalyticalSummaryTables | 9.1 | `envmon export-report-format-summary-tables` |
| ValidateEnvConfig | 10.2 | `envmon validate-config` |
| UpgradeEnvMonitoringGDBSchema | 10.3 | `envmon upgrade-schema` |
| WriteRunHistory | 10.5 | internal (used by readiness gate) |

</details>

<details>
<summary>Foundation laid / partial (8 tools)</summary>

| Tool | Roadmap # | What exists | What's missing |
|------|-----------|-------------|----------------|
| BuildGroundwaterElevationEvent | 4.1 | `normalize_groundwater.py`, `build_current_event.py` | Dedicated event-builder + flags (Dry/NM/NS/anomalous) |
| BuildAnalyticalExceedanceEvent | 4.4 | `build_current_event.py` emits `Env_CurrentEventWide` | Event-mode selectors (latest/range/max), style fields |
| CreateWorkbookParserProfile | 2.1 | `excel_workbook_inspector.py`, `excel_profile_reader.py` | Profile *drafting* output |
| CreateBoringLogDatabase | 8.0a | `schema/boring.py` (7 dataclasses) + upgrade-schema tables | Standalone create/validate tool |
| SyncFieldAttachments | 6.5 | Attachment harvester (separate domain) | Envmon-side attachment index table wiring |
| ImportRTKSurveyPoints / ValidateRTKSurvey | 8.3/8.4 | `schema/survey.py` (SurveyPointRaw/SurveyPointQA) | Import + QA logic |
| UpdateWellElevationsFromLevelLoop | 8.2 | ProcessLevelLoop ships the computation | History-write + well-table update |
| Drone/Dashboard tools (8.6–8.8 / 6.7–6.11) | — | `schema/drone.py`, `schema/dashboard.py` | Every consuming tool |

</details>

<details>
<summary>Not started (~54 tools)</summary>

**Data intake (§2):** BatchImportEnvironmentalWorkbooks (2.2), MigrateLegacyMonitoringData (2.4),
RegisterSourceDocuments (2.5), ReconcileSurvey123AndLabResults (2.6), CreateSurvey123SamplingEvent (2.7)

**Analysis (§4):** EstimateGWFlowDirection (4.3), GenerateDraftPlumeBoundary (4.5),
GenerateWellTrendCharts (4.6), SelectSoilIntervalsForMapping (4.8), BuildMaxResultMapDataset (4.9)

**Cartography (§5):** GenerateArcadeLabelExpressions (5.4), BuildAnalyticalKey (5.5),
GenerateSiteMapSeries (5.6), BuildReportFigurePackage (5.7), UpdateLayoutDynamicText (5.8)

**AGOL / cloud (§6):** SyncAGOLFeatureLayerToGDB (6.2), UpdateAGOLWebMapFromFigureSpec (6.3),
RefreshMonitoringDashboardData (6.4), AuditAGOLSchemaAgainstLocalConfig (6.6),
BuildDashboardDataMart (6.7), PublishDashboardFromSpec (6.8), AuditAGOLItemDependencies (6.9),
PromoteAGOLDataBetweenStages (6.10), CreateHostedViewsForStakeholders (6.11)

**Field / Survey123 (§7):** BuildFieldMapsMonitoringProject (7.1), RouteSurvey123Submission (7.1b),
CreateSamplingEventPlan (7.2), ReconcileFieldAndLabData (7.3), GenerateWellInspectionPhotoReport (7.4)

**Survey / boring / RTK / drone / CAD (§8):** ImportFieldBoringLogs (8.0b), GenerateBoringLogPDFs (8.0c),
ImportRTKSurveyPoints (8.3), ValidateRTKSurvey (8.4), SurveyToWellElevationUpdate (8.5),
RegisterDroneFlight (8.6), DroneGCPCheckpointQA (8.7), ImportDroneProducts (8.8),
BuildCADExportPackage (8.9), ExportContoursForCivil3D, ValidateSurveyDeliverable

**Reporting (§9):** ExportEventDatabaseSnapshot (9.0a), BuildMonitoringReportAppendix (9.2),
GenerateEventChangeLog (9.3), IngestReviewerMapComments (9.4)

**Admin (§10):** ListAvailableEnvTools (10.1), RunEnvJobQueue (10.4), GenerateSyntheticEnvWorkbook (10.6)

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

- **Shared substrate:** `autogis.core.common` — config validation, QA reporting, logging, run history
- **Two domain modules:** `autogis.core.harvest` (Attachment Harvester) and `autogis.core.envmon`
  (36 modules) sit on top of common
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

Every tool declares a runtime class; the suite enforces it at the adapter layer.

### Headless (CLOUD / HYBRID) — run anywhere without ArcGIS Pro

| Tool | Module | Runtime | CLI command |
|------|--------|---------|-------------|
| Attachment Harvester | `core.harvest` | HYBRID | `autogis harvest` |
| Inspect Workbook | `excel_workbook_inspector` | CLOUD | `autogis envmon inspect` |
| Parser Profile Draft | `excel_profile_reader` | CLOUD | `autogis envmon parser-profile` |
| Figure Spec Template | `build_figure_spec` | CLOUD | `autogis envmon figure-spec` |
| Validate Config | `config_validator` | CLOUD | `autogis envmon validate-config` |
| Manage Analyte Dict | `analyte_dictionary` | CLOUD | `autogis envmon manage-analyte-dict` |
| Validate Units | `unit_validator` | CLOUD | `autogis envmon validate-units` |
| Reconcile Locations | `location_reconciler` | CLOUD | `autogis envmon reconcile-locations` |
| Evaluate RPD QA | `rpd_evaluator` | CLOUD | `autogis envmon evaluate-rpd-qa` |
| Compare Events | `event_comparator` | CLOUD | `autogis envmon compare-events` |
| Identify Data Gaps | `data_gap_finder` | CLOUD | `autogis envmon identify-data-gaps` |
| Process Level Loop | `level_loop` | CLOUD | `autogis envmon process-level-loop` |
| Evaluate Readiness | `readiness_gate` | CLOUD | `autogis envmon evaluate-readiness` |
| Export Summary Tables | `summary_exporter` | CLOUD | `autogis envmon export-report-format-summary-tables` |
| Build Survey Form | `survey_form_builder` | CLOUD | `autogis envmon build-survey-form` |
| Publish to AGOL | `agol_publisher` | CLOUD | `autogis agol publish-layer` |

### ArcGIS Pro primary (LOCAL) — arcpy-guarded on the CLI

| Tool | Module | Primary interface |
|------|--------|------------------|
| Import Lab EDD | `import_edd` | `.pyt` GUI |
| Import to GDB | `import_to_gdb` | `.pyt` GUI |
| Build Current Event | `build_current_event` | `.pyt` GUI |
| Build Callouts | `build_figure_dataset` | `.pyt` GUI |
| GW Contours | `groundwater_contours` | `.pyt` GUI |
| Export Figures | `export_figures`, `layout_manager` | `.pyt` GUI |
| Full Pipeline | orchestrator | `.pyt` GUI |
| Validate Database | `validate_database` | `.pyt` GUI |
| Upgrade Schema | `schema_upgrader` | `.pyt` GUI |

Pro-guarded commands fail with a clear error when `arcpy` is absent, pointing users to the
`.pyt` toolbox inside ArcGIS Pro.

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
python -m pytest -q           # 362 passing tests
```

---

## CLI Reference

`autogis` exposes the Harvester at the top level and envmon tools under an `envmon` sub-group.
`autogis-harvest` is preserved as a legacy alias.

### Attachment Harvester

```bash
autogis harvest --config my-job.yaml
autogis harvest --config my-job.yaml --incremental
autogis harvest --config my-job.yaml --where "Status = 'Complete'" --out ./batch
```

### Headless envmon tools

```bash
# Workbook inspection
autogis envmon inspect <workbook.xlsx>
autogis envmon parser-profile <workbook.xlsx>
autogis envmon figure-spec <output.yaml>

# Validation & QA
autogis envmon validate-config <site-config.yaml>
autogis envmon validate-units <samples.csv>
autogis envmon reconcile-locations <workbook.xlsx>
autogis envmon manage-analyte-dict
autogis envmon evaluate-rpd-qa <duplicates.csv>

# Analysis & reporting
autogis envmon compare-events <event_db>
autogis envmon identify-data-gaps <event_db>
autogis envmon process-level-loop <survey.csv>
autogis envmon evaluate-readiness <event_db>
autogis envmon export-report-format-summary-tables <event_db>

# Field data
autogis envmon build-survey-form <config.yaml>

# Publishing
autogis agol publish-layer <config.yaml>
```

### Pro-guarded tools (require arcpy)

```bash
autogis envmon import-edd <lab-results.csv>
autogis envmon import-gdb <config.yaml>
autogis envmon build-current-event <config.yaml>
autogis envmon validate-db <geodatabase>
autogis envmon upgrade-schema <geodatabase>
# tools 5–8 follow the same pattern
```

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
    ├─ Import to GDB               Tool 3
    ├─ Build current event         Tool 4
    └─ Validate database           Tool 11
    ↓
Analysis & cartography (Pro)
    ├─ GW contours                 Tool 4.2
    ├─ Analytical callouts         Tool 5.1
    ├─ Optimize placement          Tool 5.2
    └─ Export figures              Tool 6
    ↓
Publish / report (headless)
    ├─ Publish to AGOL             autogis agol publish-layer
    ├─ Export summary tables       autogis envmon export-report-format-summary-tables
    └─ Evaluate readiness          autogis envmon evaluate-readiness
```

---

## Project Structure

```
autogis/
├── core/
│   ├── common/          # Config, QA, logging, run history, schema dataclasses
│   ├── harvest/         # Attachment Harvester (arcpy-free)
│   └── envmon/          # Environmental monitoring — 36 modules
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
└── tests/               # 362 arcpy-free unit tests
```

### Key modules

| Path | Purpose |
|------|---------|
| `core/common/config.py` | `HarvestConfig`, `SiteConfig`, `ParserProfile`, `FigureSpec` — canonical dataclasses |
| `core/common/schema/` | 5 modules (boring, dashboard, drone, envmon, survey) exporting ~29 typed dataclasses |
| `core/envmon/` | 36 modules: inspectors, importers, validators, reconcilers, event builders, analysis, callout/contour tools |
| `adapters/cli.py` | Click CLI — constructs config dataclasses, guards LOCAL tools, dispatches to core |
| `runtime/` | `arcpy_available()`, `local_runtime_ok()`, `capability_required()` decorators |

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
Tools 3–8 (Pro-based) are not exercised in CI. Run them on a copy of real data inside Pro before
trusting outputs.

**Incremental harvest depends on feature service metadata.**
`--incremental` relies on `GlobalID` and `EditDate` fields. If absent, falls back to a full re-download.

---

## Documentation

| Document | Contents |
|----------|---------|
| [`docs/pro-install.md`](docs/pro-install.md) | Full Pro setup: env clone, toolbox registration, cache/reload |
| [`docs/ROADMAP_STATUS_2026-06-27.md`](docs/ROADMAP_STATUS_2026-06-27.md) | Feature completion status by tool |
| [`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`](docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md) | Phase 1–4 sequencing (~70 weeks) |
| [`docs/adr/`](docs/adr/) | Architecture decision records — invariants, schema, config strategy |

---

## Contributing

Test baseline: **362 passing tests**. All core logic is arcpy-free and CI-able.

```bash
python -m pytest -q
python -m pytest --cov=autogis --cov-report=term-missing

ruff check autogis/
mypy autogis/
```

See [`docs/adr/README.md`](docs/adr/README.md) for architectural guidelines before adding new tools.
