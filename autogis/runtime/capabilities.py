from enum import Enum


class Runtime(Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    HYBRID = "hybrid"


# Per MERGE_PLAN §4. Names are CLI subcommand names.
TOOLS: dict[str, Runtime] = {
    "harvest": Runtime.HYBRID,
    "inspect": Runtime.CLOUD,          # tool 1
    "parser-profile": Runtime.CLOUD,   # tool 9
    "figure-spec": Runtime.CLOUD,      # tool 10
    "import-gdb": Runtime.LOCAL,       # tool 2
    "build-event": Runtime.LOCAL,      # tool 3
    "build-callouts": Runtime.LOCAL,   # tool 4
    "gw-contours": Runtime.LOCAL,      # tool 5
    "export-figures": Runtime.LOCAL,   # tool 6
    "full-pipeline": Runtime.LOCAL,    # tool 7
    "validate-db": Runtime.LOCAL,      # tool 8
    "qualify": Runtime.LOCAL,          # ADR-0091 Pro qualification runner
    "validate-config": Runtime.CLOUD,
    "manage-analyte-dict": Runtime.CLOUD,
    "validate-units": Runtime.CLOUD,
    "reconcile-locations": Runtime.HYBRID,
    "import-edd": Runtime.LOCAL,      # writes to GDB — needs arcpy
    "upgrade-schema": Runtime.LOCAL,   # tool 10.3
    "export-snapshot": Runtime.LOCAL,
    "evaluate-rpd": Runtime.CLOUD,
    "manage-screening-levels": Runtime.CLOUD,
    "optimize-callouts": Runtime.LOCAL,        # tool 5.2
    "manage-callout-overrides": Runtime.LOCAL, # tool 5.3
    "build-survey-form": Runtime.CLOUD, # tool 7.1a
    "validate-survey-form": Runtime.CLOUD,  # S123-1.1
    "diff-survey-schema": Runtime.CLOUD,    # S123-1.2
    "compare-events": Runtime.CLOUD,   # tool 4.7
    "process-level-loop": Runtime.CLOUD,  # tool 8.1
    "identify-data-gaps": Runtime.CLOUD,  # tool 4.10
    "run-history-report": Runtime.CLOUD,  # post-roadmap extra
    "validate-schedule": Runtime.CLOUD,   # post-roadmap extra
    "apply-screening": Runtime.CLOUD,     # post-roadmap extra
    "compare-schedule-vs-actual": Runtime.CLOUD,  # tool 10.x
    "drone-checkpoint-qa": Runtime.CLOUD,  # tool 8.7
    "export-geojson": Runtime.CLOUD,  # post-roadmap extra
    "generate-arcade-labels": Runtime.CLOUD,  # tool 5.4
    "generate-python-labels": Runtime.CLOUD,  # tool 5.4b
    "generate-event-changelog": Runtime.CLOUD,  # tool 9.3
    "export-lab-request": Runtime.CLOUD,  # post-roadmap extra, headless
    "coc": Runtime.CLOUD,  # Phase 6 chain-of-custody lifecycle (headless group)
    "lab-qa-trends": Runtime.CLOUD,  # Phase 7 longitudinal lab-QA (headless)
    "export-wqx": Runtime.CLOUD,  # Phase 8 outbound WQX submission (headless)
    "generate-event-report": Runtime.CLOUD,  # post-roadmap extra
    "run-history": Runtime.CLOUD,  # post-roadmap extra (query CLI)
    "import-rtk-survey": Runtime.LOCAL,  # writes to GDB — needs arcpy
    "route-survey123": Runtime.LOCAL,    # writes to GDB — needs arcpy
    "sync-survey123": Runtime.CLOUD,     # S123 Phase 2 live read-only pull (arcgis via lazy provider)
    "build-dashboard-data-mart": Runtime.LOCAL,  # truncates/repopulates GDB
    "generate-trend-charts": Runtime.CLOUD,  # tool 4.6 headless openpyxl charts
    "ingest-reviewer-comments": Runtime.CLOUD,  # tool 9.4 headless parser
    "select-soil-intervals": Runtime.CLOUD,  # tool headless stdlib tiering
    "export-comparison-excel": Runtime.CLOUD,  # post-roadmap extra, openpyxl
    "generate-job-queue": Runtime.CLOUD,  # tool 10.4 headless JSON manifest
    "register-source-doc": Runtime.CLOUD,      # tool 2.5 headless registry
    "validate-boring-logs": Runtime.CLOUD,     # tool 8.0b headless validate
    "draft-lithology-from-scan": Runtime.CLOUD,  # tool headless OCR draft
    "download-dem": Runtime.CLOUD,  # OpenTopography DEM fetch — stdlib urllib, headless
    "import-boring-logs": Runtime.LOCAL,       # tool 8.0b GDB write
    "create-boring-log-db": Runtime.CLOUD,     # tool 8.0a headless SQLite scaffold
    "gen-boring-logs": Runtime.CLOUD,          # tool 8.0c headless Markdown/CSV logs
    "index-field-attachments": Runtime.CLOUD,  # tool 6.5 envmon-side index, headless
    "register-drone-flight": Runtime.LOCAL,    # tool 8.6 GDB write
    "validate-drone-products": Runtime.CLOUD,  # tool 8.8 headless validate
    "import-drone-products": Runtime.LOCAL,    # tool 8.8 GDB write
    "condition-dem": Runtime.LOCAL,  # DEMConditioningPipeline raster ops — needs arcpy
    "compare-drone-surfaces": Runtime.LOCAL,  # CompareDroneSurfaces raster diff — needs arcpy
    "survey-to-well-elevation": Runtime.LOCAL,  # tool 8.5 GDB write (--gdb path)
    "rtk-control-check": Runtime.CLOUD,  # RTK control-network check, headless
    "portfolio-metrics": Runtime.CLOUD,  # cross-site readiness rollup, headless
    "event-status": Runtime.CLOUD,  # roadmap Phase 2 staleness checker, headless
    "evaluate-gw-models": Runtime.CLOUD,  # model prediction cross-validation, headless
    "export-survey-cad": Runtime.CLOUD,  # feature-code CSV/GeoJSON export, headless
    "well-inspection-report": Runtime.CLOUD,  # Markdown well inspection report, headless
    "update-well-elevations": Runtime.LOCAL,  # tool 8.2 GDB write (--gdb path)
    "draft-plume-boundary": Runtime.LOCAL,    # tool 4.5 GDB write (--gdb path)
    "build-cad-package": Runtime.LOCAL,  # tool 8.9 Export-to-CAD — needs arcpy
    "export-civil3d": Runtime.CLOUD,     # CLI point outputs headless; Pro .pyt adds TIN LandXML (ADR-0089)
    "transform-landxml": Runtime.CLOUD,  # LandXML Project-style CRS/Z transform
    "update-layout-text": Runtime.LOCAL,  # tool 5.8 APRX layout edit — needs arcpy
    "build-fieldmaps": Runtime.LOCAL,  # tool 7.1 GDB layer/field provisioning — needs arcpy
    "sync-to-gdb": Runtime.LOCAL,  # tool 6.2 GDB upsert (--gdb path); agol group
    "generate-inspection-report": Runtime.CLOUD,  # tool 7.4 headless photo workbook (openpyxl + Pillow)
    "gen-map-series": Runtime.LOCAL,  # tool 5.6 batch figure-packet export — needs arcpy
    "run-gw-model-pipeline": Runtime.LOCAL,  # Phase-5 slice 1 — TIN/IDW LOO CV, needs arcpy
    "approve-gw-model": Runtime.LOCAL,  # Phase-5 slice 1 — GW_ModelRun field edit, needs arcpy
    "build-conc-surface": Runtime.LOCAL,  # Phase-5 slice 2 — raster interpolation, needs arcpy
    "reconcile-event": Runtime.CLOUD,  # Survey123 Phase 3 five-source event reconciliation (headless)
    "photos": Runtime.CLOUD,  # harvest photo-metadata suite (headless group)
}


def requires_arcpy(name: str) -> bool:
    runtime = TOOLS.get(name)
    if runtime is None:
        raise KeyError(
            f"Unknown tool '{name}': not registered in capabilities.TOOLS. "
            f"Register it before calling requires_arcpy().")
    return runtime is Runtime.LOCAL


# ---------------------------------------------------------------------------
# Tool discovery registry (Tool 10.1 ListAvailableEnvTools)
# ---------------------------------------------------------------------------
# This is a SEPARATE, additive source of human-facing metadata for the
# `envmon list-tools` command. It deliberately does NOT replace TOOLS /
# requires_arcpy above (those drive the runtime guard and must stay stable).
# `runtime` here is a display string (CLOUD = headless, HYBRID = headless with
# an arcpy-guarded branch, LOCAL = needs arcpy) and may differ in spelling
# from the Runtime enum. Pre-production tools are marked by
# ToolCapability.status == "draft", never by the runtime column (#468).
from dataclasses import dataclass as _dataclass

# The only legal values of ToolCapability.runtime — derived from the Runtime
# enum so the display vocabulary cannot drift from the one the guard enforces.
RUNTIME_CLASSES: tuple[str, ...] = tuple(r.name for r in Runtime)


@_dataclass
class ToolCapability:
    """Human-facing metadata for one CLI command (discovery only)."""
    command: str
    name: str = ""
    roadmap_id: str = ""
    runtime: str = "CLOUD"     # CLOUD | HYBRID | LOCAL (see RUNTIME_CLASSES)
    status: str = "stable"     # stable | draft | planned | deprecated
    domain: str = ""           # intake|qa|analysis|cartography|field|agol|reporting|admin
    description: str = ""
    plan_path: str = ""


# (command, name, roadmap_id, runtime, status, domain, description)
_REGISTRY_SEED = [
    ("inspect", "InspectWorkbook", "1", "CLOUD", "stable", "intake",
     "Inspect an Excel workbook's structure"),
    ("parser-profile", "ParserProfile", "9", "CLOUD", "stable", "admin",
     "Read/validate a parser profile workbook"),
    ("figure-spec", "FigureSpec", "10", "CLOUD", "stable", "cartography",
     "Load and validate a figure spec"),
    ("validate-config", "ValidateEnvConfig", "10.2", "CLOUD", "stable", "admin",
     "Validate env config + filename patterns"),
    ("init-site", "InitSite", "", "CLOUD", "stable", "admin",
     "Scaffold a new site's config skeleton (site/event/parser/figure) from templates"),
    ("validate-recipe", "ValidateWorkflowRecipe", "", "CLOUD", "stable", "admin",
     "Validate a saved linear workflow-recipe YAML (Phase 5)"),
    ("run-recipe", "RunWorkflowRecipe", "", "CLOUD", "stable", "admin",
     "Run a saved workflow recipe headlessly, step by step (Phase 5)"),
    ("manage-analyte-dict", "ManageAnalyteDict", "3.3", "CLOUD", "stable", "admin",
     "Inspect/edit the analyte dictionary"),
    ("manage-screening-levels", "ManageScreeningLevels", "3.4", "CLOUD", "draft",
     "admin", "Manage screening levels (DRAFT pre-production stub)"),
    ("validate-units", "ValidateUnits", "3.5", "CLOUD", "stable", "qa",
     "Validate and convert result units"),
    ("reconcile-locations", "ReconcileSampleLocations", "3.2", "HYBRID", "stable",
     "qa", "Reconcile sample location IDs against the well list"),
    ("evaluate-rpd-qa", "EvaluateRPDQA", "3.6", "CLOUD", "stable", "qa",
     "Evaluate duplicate RPD QA from records"),
    ("evaluate-rpd", "EvaluateRPD", "", "CLOUD", "stable", "qa",
     "Evaluate relative percent difference for duplicates"),
    ("evaluate-readiness", "EvaluateReportReadiness", "9.0b", "CLOUD", "stable",
     "qa", "Evaluate report readiness against QA history"),
    ("event-status", "EventStatus", "2", "CLOUD", "stable", "qa",
     "Classify event artifacts current/stale/missing/failed/awaiting-review"),
    ("identify-data-gaps", "IdentifyMonitoringDataGaps", "4.10", "CLOUD",
     "stable", "qa", "Identify missing wells/analytes/events"),
    ("compare-schedule-vs-actual", "CompareScheduleVsActual", "", "CLOUD",
     "stable", "qa", "Compare planned vs actual sampling"),
    ("validate-field-completeness", "ValidateFieldDataCompleteness", "", "CLOUD",
     "stable", "qa", "Validate field data completeness"),
    ("generate-qc-summary", "GenerateQCSampleSummary", "", "CLOUD", "stable",
     "qa", "Summarize QC samples (blanks, spikes, duplicates)"),
    ("export-summary", "ExportAnalyticalSummary", "", "CLOUD", "stable",
     "reporting", "Export analytical summary CSV"),
    ("export-report-format-summary-tables", "ExportSummaryTables", "9.1", "CLOUD",
     "stable", "reporting", "Export formatted summary-table workbook"),
    ("export-geojson", "ExportGeoJSON", "", "CLOUD", "stable", "reporting",
     "Export results to GeoJSON"),
    ("export-geopackage", "ExportEnvGeoPackage", "", "CLOUD", "stable",
     "reporting", "Export env data to a GeoPackage"),
    ("export-snapshot", "ExportEventSnapshot", "9.0a", "LOCAL", "stable",
     "reporting", "Export an event snapshot"),
    ("generate-event-report", "GenerateMonitoringEventReport", "", "CLOUD",
     "stable", "reporting", "Generate a monitoring event report"),
    ("generate-reg-tables", "GenerateRegulatoryTables", "", "CLOUD", "stable",
     "reporting", "Build regulatory comparison tables"),
    ("generate-site-narrative", "GenerateSiteNarrative", "", "CLOUD", "stable",
     "reporting", "Generate a site narrative draft"),
    ("build-report-package", "BuildReportFigurePackage", "5.7", "CLOUD", "stable",
     "reporting", "Assemble a deliverable figure package"),
    ("verify-report-package", "VerifyReportPackage", "", "CLOUD", "stable",
     "reporting", "Verify report-package paths and SHA-256 manifest hashes"),
    ("build-report-appendix", "BuildMonitoringReportAppendix", "9.2", "CLOUD",
     "stable", "reporting", "Build multi-sheet analytical appendix workbook"),
    ("run-history-report", "RunHistorySummaryReport", "", "CLOUD", "stable",
     "admin", "Summarize run history"),
    ("run-history", "RunHistoryQuery", "", "CLOUD", "stable", "admin",
     "Query the run-history log"),
    ("validate-schedule", "ValidateScheduleYAML", "", "CLOUD", "stable",
     "admin", "Validate a monitoring schedule YAML"),
    ("compare-events", "CompareMonitoringEvents", "4.7", "CLOUD", "stable",
     "analysis", "Compare two monitoring events"),
    ("apply-screening", "ApplyScreening", "", "CLOUD", "stable", "analysis",
     "Apply screening levels to normalized results"),
    ("build-max-result-dataset", "BuildMaxResultDataset", "4.9", "CLOUD", "stable",
     "analysis", "Build cross-event max-detected dataset"),
    ("build-compliance-table", "BuildComplianceSummaryTable", "", "CLOUD",
     "stable", "analysis", "Build cross-event compliance matrix"),
    ("build-exceedance-event", "BuildAnalyticalExceedanceEvent",
     "4.4", "CLOUD", "stable", "analysis",
     "Build exceedance event dataset with ratio/tier enrichment"),
    ("list-tools", "ListAvailableEnvTools", "10.1", "CLOUD", "stable", "admin",
     "List available envmon + agol tools with capability metadata"),
    ("build-dashboard-data-mart", "BuildDashboardDataMart", "6.7", "LOCAL",
     "stable", "analysis", "Build dashboard mart tables and refresh JSON"),
    ("estimate-gw-flow-direction", "EstimateGWFlowDirection", "4.3", "CLOUD",
     "stable", "analysis", "Estimate groundwater flow direction from 3+ wells"),
    ("gw-level-summary", "BuildGroundwaterLevelSummary", "", "CLOUD",
     "stable", "analysis",
     "Per-well GW level/DTW/trend summary from elevation history"),
    ("build-gwe-event", "BuildGroundwaterElevationEvent", "4.1", "CLOUD",
     "stable", "analysis",
     "Per-event GW-elevation contour layer with exclusion flags"),
    ("gen-synthetic-workbook", "GenerateSyntheticEnvWorkbook", "10.6", "CLOUD",
     "stable", "admin",
     "Generate a seeded synthetic environmental workbook for parser hardening"),
    ("build-analytical-key", "BuildAnalyticalKey", "5.5", "CLOUD",
     "stable", "cartography",
     "Build the analytical key/legend table (analyte, units, screening, NE)"),
    ("merge-event-results", "MergeEventResults", "", "CLOUD", "stable",
     "intake", "Merge multiple event result CSVs"),
    ("import-edd", "ImportLabEDD", "2.3", "LOCAL", "stable", "intake",
     "Import lab EDD CSV/XLSX into the GDB"),
    ("import-gdb", "ImportToGDB", "2", "LOCAL", "stable", "intake",
     "Import normalized tables into a file GDB"),
    ("export-lab-request", "ExportLabAnalyticalRequest", "", "CLOUD",
     "stable", "intake", "Export a lab analytical request workbook"),
    ("upgrade-schema", "UpgradeGDBSchema", "10.3", "LOCAL", "stable", "admin",
     "Additive upgrade of the GDB schema"),
    ("build-event", "BuildCurrentEvent", "3", "LOCAL", "stable", "cartography",
     "Build the wide current-event table"),
    ("build-callouts", "BuildCallouts", "5.1", "LOCAL", "stable", "cartography",
     "Build analytical callout boxes"),
    ("optimize-callouts", "BuildCalloutsHullCollision", "5.2", "LOCAL", "deprecated",
     "cartography",
     "Hull-collision callout placement -- folded into build-callouts "
     "--use-hull-collision / the BuildCallouts .pyt parameter (ADR-0020); "
     "this command always raises and redirects, it never runs"),
    ("manage-callout-overrides", "ManageCalloutOverrides", "5.3", "LOCAL",
     "stable", "cartography",
     "CRUD for Env_CalloutPlacementOverrides (list/lock/unlock/clear)"),
    ("gw-contours", "GroundwaterContours", "5", "LOCAL", "stable", "analysis",
     "Generate draft groundwater contour features"),
    ("export-figures", "ExportFigures", "6", "LOCAL", "stable", "cartography",
     "Export figure layouts"),
    ("full-pipeline", "FullPipeline", "7", "LOCAL", "stable", "admin",
     "Run the end-to-end local pipeline"),
    ("validate-db", "ValidateDatabase", "8", "LOCAL", "stable", "qa",
     "Validate the geodatabase contents"),
    ("qualify", "QualifyArcGISPro", "", "LOCAL", "stable", "admin",
     "Qualify the installed ArcGIS Pro runtime and Python toolbox"),
    ("build-survey-form", "BuildSurvey123Form", "7.1a", "CLOUD", "stable",
     "field", "Build a Survey123 XLSForm"),
    ("validate-survey-form", "ValidateSurveyForm", "S123-1.1", "CLOUD",
     "stable", "field",
     "Static XLSForm validation: structure, choices, references, the "
     "ADR-0113 SampleID contract, and site/event config cross-checks"),
    ("diff-survey-schema", "DiffSurveySchema", "S123-1.2", "CLOUD",
     "stable", "field",
     "Classify XLSForm changes vs a baseline form and/or a saved "
     "feature-layer spec as safe, review-required, or destructive"),
    ("validate-rtk-survey", "ValidateRTKSurvey", "", "CLOUD", "stable", "field",
     "Validate an RTK survey point file"),
    ("import-rtk-survey", "ImportRTKSurveyPoints", "", "LOCAL", "stable",
     "field", "Import RTK survey points into the GDB"),
    ("route-survey123", "RouteSurvey123Submission", "7.1b", "LOCAL", "stable",
     "field", "Route a Survey123 submission into the GDB"),
    ("sync-survey123", "SyncSurvey123Submissions", "", "CLOUD", "stable",
     "field", "Pull new/changed Survey123 submissions into staging (live, read-only)"),
    ("reconcile-survey123-lab", "ReconcileSurvey123Lab", "2.6", "CLOUD", "stable",
     "qa", "Reconcile Survey123 field data against lab results"),
    ("reconcile-event", "ReconcileMonitoringEvent", "", "CLOUD", "stable", "qa",
     "Five-source event reconciliation: plan/Survey123/COC/lab/GDB presence "
     "matrix with per-sample outcomes and zero-residual balance"),
    ("process-level-loop", "ProcessLevelLoop", "8.1", "CLOUD", "stable",
     "field", "Process a differential level loop"),
    ("drone-checkpoint-qa", "DroneGCPCheckpointQA", "8.7", "CLOUD", "stable",
     "field", "QA drone GCP/checkpoint residuals"),
    ("generate-trend-charts", "GenerateWellTrendCharts", "4.6", "CLOUD",
     "stable", "reporting",
     "Excel LineChart trend workbook per location/analyte"),
    ("ingest-reviewer-comments", "IngestReviewerMapComments", "9.4", "CLOUD",
     "stable", "reporting",
     "Ingest reviewer markups (CSV/GeoJSON/XLSX) into a tracked comment table"),
    ("select-soil-intervals", "SelectSoilIntervalsForMapping", "4.8", "CLOUD",
     "stable", "cartography",
     "Assign HOTSPOT/DETECT/ND/NO_DATA tiers to soil intervals for mapping"),
    ("export-comparison-excel", "ExportComparisonResultsToExcel", "", "CLOUD",
     "stable", "reporting",
     "Export compare-events records to a trend-coloured Excel workbook"),
    ("generate-job-queue", "GenerateRunJobQueue", "10.4", "CLOUD", "stable",
     "admin", "Generate an ordered batch job-queue JSON from a manifest"),
    ("register-source-doc", "RegisterSourceDocuments", "2.5", "CLOUD", "stable",
     "intake", "Register an ingested source document (SHA-256 audit registry)"),
    ("register-drone-flight", "RegisterDroneFlight", "8.6", "LOCAL", "stable",
     "field", "Register a drone flight from an inventory YAML"),
    ("new-flight-yaml", "NewFlightYaml", "8.6a", "CLOUD", "stable",
     "admin", "Write a ready-to-edit drone flight inventory YAML template"),
    ("validate-drone-products", "ImportDroneProducts", "8.8", "CLOUD", "stable",
     "field", "Validate a drone product manifest (headless)"),
    ("import-drone-products", "ImportDroneProducts", "8.8", "LOCAL", "stable",
     "field", "Import drone deliverables into the GDB raster catalog"),
    ("validate-boring-logs", "ImportFieldBoringLogs", "8.0b", "CLOUD", "stable",
     "intake", "Validate a boring-log CSV package (headless)"),
    ("draft-lithology-from-scan", "DraftLithologyFromScan", "", "CLOUD", "draft",
     "intake", "DRAFT: OCR a scanned boring log into a draft lithology.csv (headless)"),
    ("download-dem", "DownloadOpenTopographyDEM", "", "CLOUD", "stable",
     "intake", "Download an OpenTopography DEM GeoTIFF for an AOI (headless)"),
    ("import-boring-logs", "ImportFieldBoringLogs", "8.0b", "LOCAL", "stable",
     "intake", "Import a boring-log CSV package into the GDB"),
    ("survey-to-well-elevation", "SurveyToWellElevationUpdate", "8.5", "LOCAL",
     "stable", "field", "Push QA-passed RTK elevations to MonitoringWells.TOC_ft"),
    ("update-well-elevations", "UpdateWellElevationsFromLevelLoop", "8.2", "LOCAL",
     "stable", "field", "Push adjusted level-loop elevations to MonitoringWells.TOC_ft"),
    ("draft-plume-boundary", "GenerateDraftPlumeBoundary", "4.5", "LOCAL",
     "stable", "cartography", "Draft plume-extent polygon (hull) from exceedance points"),
    ("rtk-control-check", "RTKControlCheckReport", "", "CLOUD", "stable", "field",
     "Compare RTK-surveyed control shots to published benchmarks"),
    ("portfolio-metrics", "GeneratePortfolioMetrics", "", "CLOUD", "stable", "admin",
     "Roll up per-site report readiness across a multi-site run history"),
    ("evaluate-gw-models", "EvaluateGroundwaterSurfaceModels", "", "CLOUD", "stable",
     "analysis", "Cross-validate interpolation model predictions against observed values"),
    ("export-survey-cad", "ExportSurveyToCADGIS", "", "CLOUD", "stable", "field",
     "Export RTK survey points to feature-code-mapped CSV/GeoJSON layers"),
    ("well-inspection-report", "GenerateWellInspectionReports", "", "CLOUD", "stable",
     "reporting", "Generate Markdown well inspection reports + site summary"),
    ("create-boring-log-db", "CreateBoringLogDatabase", "8.0a", "CLOUD", "stable",
     "intake", "Create/validate the normalized boring-log SQLite database"),
    ("gen-boring-logs", "GenerateBoringLogPDFs", "8.0c", "CLOUD", "stable",
     "reporting", "Assemble boring-log Markdown docs, appendix, photo log and sample CSV"),
    ("generate-subsurface-profile", "GenerateSubsurfaceProfileFromBorings", "",
     "CLOUD", "stable", "cartography",
     "Render a subsurface profile figure from borings projected onto a line"),
    ("gen-sticklogs", "GenerateBoringSticklogs", "",
     "CLOUD", "stable", "cartography",
     "Render a 2D sticklog figure per boring from the boring-log database"),
    ("condition-dem", "DEMConditioningPipeline", "", "LOCAL", "stable",
     "analysis", "Void-fill/smooth a drone DEM and derive hillshade/slope/contours"),
    ("compare-drone-surfaces", "CompareDroneSurfaces", "", "LOCAL", "stable",
     "analysis", "Raster-diff a drone DEM against a prior flight or LandXML design surface"),
    ("index-field-attachments", "SyncFieldAttachments", "6.5", "CLOUD", "stable",
     "agol", "Index a harvester manifest into the AttachmentIndex table"),
    # `agol` group commands (unified discovery, ADR-0092). Group-qualified
    # command strings ("agol <name>") because these live under the top-level
    # `agol` click group, not `envmon`.
    ("agol publish-layer", "PublishEnvironmentalLayersToAGOL", "6.1", "CLOUD",
     "stable", "agol", "Publish or overwrite a hosted AGOL feature service"),
    ("agol sync-to-gdb", "SyncAGOLFeatureLayerToGDB", "6.2", "LOCAL", "stable",
     "agol", "Download hosted feature layer edits into the local FGDB "
     "(--out-csv dump is headless; --gdb upsert needs arcpy)"),
    ("agol update-webmap", "UpdateAGOLWebMapFromFigureSpec", "6.3", "CLOUD",
     "stable", "agol", "Push a figure spec's display config into an AGOL web map"),
    ("agol refresh-dashboard", "RefreshMonitoringDashboardData", "6.4", "CLOUD",
     "stable", "agol", "Push local Dash_* data-mart tables to hosted AGOL layers"),
    ("agol audit-schema", "AuditAGOLSchemaAgainstLocalConfig", "6.6", "CLOUD",
     "stable", "agol", "Compare a hosted AGOL feature layer schema against a "
     "local spec"),
    ("agol publish-dashboard", "PublishDashboardFromSpec", "6.8", "CLOUD",
     "stable", "agol", "Compile a YAML dashboard spec and create-or-update the "
     "AGOL Dashboard item"),
    ("agol audit-dependencies", "AuditAGOLItemDependencies", "6.9", "CLOUD",
     "stable", "agol", "Find items that reference/depend on an AGOL item"),
    ("agol promote", "PromoteAGOLDataBetweenStages", "6.10", "CLOUD", "stable",
     "agol", "Promote an AGOL layer's data between DEV/QA/PROD stages"),
    ("agol create-views", "CreateHostedViewsForStakeholders", "6.11", "CLOUD",
     "stable", "agol", "Create/update audience-specific hosted views "
     "(sensitive-field leak is blocking)"),
    ("agol fieldmaps-preflight", "FieldMapsSyncPreflight", "", "CLOUD",
     "stable", "field", "Read-only Field Maps sync preflight report "
     "(pending edits, replica age, drift, attachments, duplicates, "
     "conflicts)"),
    ("build-cad-package", "BuildCADExportPackage", "8.9", "LOCAL", "stable",
     "cartography", "Export GIS layers to a DWG/DXF CAD file (arcpy Export-to-CAD, "
     "ADR-0088) with mapped CAD layer name/color/linetype on scratch copies, "
     "plus a projection note and mapping report (ADR-0089)"),
    ("export-civil3d", "ExportContoursForCivil3D", "8.10", "CLOUD", "stable",
     "cartography", "Export PNEZD point CSV + projection note + LandXML CgPoints "
     "headlessly (ADR-0088), or an existing Pro TIN as a triangulated LandXML "
     "surface through the .pyt toolbox (ADR-0089)"),
    ("transform-landxml", "TransformLandXMLSurface", "8.10a", "CLOUD", "stable",
     "cartography", "Project one LandXML TIN surface from a geographic or "
     "projected authority-coded CRS to a projected EPSG CRS, select or infer "
     "the geographic transformation, and scale Z while preserving faces"),
    ("draft-parser-profile", "DraftParserProfile", "2.1", "CLOUD", "stable",
     "admin", "Inspect a workbook and write a draft parser profile YAML"),
    ("batch-import-workbooks", "BatchImportWorkbooks", "2.2", "CLOUD", "stable",
     "intake", "Batch-import multiple EDD workbooks from a manifest CSV"),
    ("draft-edd-profile", "DraftEDDProfile", "2.3a", "CLOUD", "stable",
     "admin", "Inspect a sample lab EDD and write a draft LabEDD profile YAML"),
    ("validate-lab-profile", "ValidateLabProfile", "2.3b", "CLOUD", "stable",
     "qa", "Validate a LabEDD profile YAML is well-formed"),
    ("migrate-legacy-data", "MigrateLegacyData", "2.4", "CLOUD", "stable",
     "intake", "Convert wide-format legacy CSV to long-format result records"),
    ("generate-arcade-labels", "GenerateArcadeLabels", "5.4", "CLOUD", "stable",
     "cartography", "Generate Arcade label expressions for ArcGIS Pro layers"),
    ("generate-python-labels", "GeneratePythonLabels", "5.4b", "CLOUD", "stable",
     "cartography", "Generate Python label expressions for ArcGIS Pro layers"),
    ("create-sampling-plan", "CreateSamplingPlan", "7.2", "CLOUD", "stable",
     "field", "Generate planned sample list and bottle count for an event"),
    ("reconcile-field-lab", "ReconcileFieldLab", "7.3", "CLOUD", "stable",
     "qa", "Compare field records to lab results, flag mismatches"),
    ("generate-event-changelog", "GenerateEventChangelog", "9.3", "CLOUD",
     "stable", "reporting",
     "Generate structured changelog from two monitoring event CSVs"),
    ("update-layout-text", "UpdateLayoutDynamicText", "5.8", "LOCAL", "stable",
     "cartography", "Update APRX layout text elements from a YAML values file"),
    ("build-fieldmaps", "BuildFieldMapsMonitoringProject", "7.1", "LOCAL",
     "stable", "field",
     "Create/refresh Field Maps monitoring layers + editable field schema"),
    ("create-sampling-event", "CreateSurvey123SamplingEvent", "2.7", "CLOUD",
     "stable", "field",
     "Generate a pre-field sampling event plan workbook (expected samples, "
     "crew, COC draft)"),
    ("coc", "ChainOfCustodyLifecycle", "", "CLOUD", "stable", "field",
     "Advance a sampling event's COCs through generated -> released -> "
     "laboratory-received -> results-received -> reconciled/exception with a "
     "per-transition audit trail and planned-vs-received reconciliation (Phase 6)"),
    ("lab-qa-trends", "LongitudinalLabQATrends", "", "CLOUD", "stable", "reporting",
     "Longitudinal lab-QA trends across events: out-of-limit percent-recovery "
     "and blank-detection frequencies per method/matrix/analyte, with the "
     "configurable, cited threshold applied (Phase 7 slice 1)"),
    ("export-wqx", "OutboundWQXExport", "", "CLOUD", "draft", "reporting",
     "Map canonical results to WQX submission columns with identifier/coordinate/"
     "unit/method/qualifier validation; valid rows -> submission CSV, invalid -> "
     "rejections CSV, plus source/config provenance (Phase 8 slice 1, DRAFT)"),
    ("photos", "HarvestPhotoMetadataTools", "", "CLOUD", "stable", "reporting",
     "EXIF-driven photo-metadata tools over a harvest output folder: GPS/heading "
     "points (CSV/GeoJSON), photo<->feature distance/date QA, Google Earth KMZ, "
     "and a photographic log appendix (xlsx/html/docx)"),
    ("generate-inspection-report", "GenerateWellInspectionPhotoReport", "7.4",
     "CLOUD", "stable", "reporting",
     "Per-well inspection photo workbook (XLSX) from harvested attachments "
     "+ an inspection CSV (photo embedding needs Pillow)"),
    ("gen-map-series", "GenerateSiteMapSeries", "5.6", "LOCAL", "stable",
     "cartography",
     "Batch figure-packet exporter across sites/events (plan headless via "
     "--dry-run)"),
    ("run-gw-model-pipeline", "RunFieldToGroundwaterModelPipeline", "", "LOCAL",
     "stable", "analysis",
     "Multi-model (TIN/IDW) draft GW contours + leave-one-out cross-validation "
     "ranking persisted to GW_ModelRun (Phase-5 slice 1, ADR-0085)"),
    ("approve-gw-model", "BuildGroundwaterSurfaceModel", "", "LOCAL",
     "stable", "analysis",
     "Record the hydrogeologist's approved model on a GW_ModelRun (single-"
     "method runs via run-gw-model-pipeline; ADR-0085 decision 3)"),
    ("build-conc-surface", "BuildAnalyticalConcentrationSurface", "", "LOCAL",
     "stable", "analysis",
     "DRAFT interpolated concentration raster (IDW/EBK) per analyte with "
     "nondetect policy + boundary clip (Phase-5 slice 2, ADR-0085)"),
]

TOOL_REGISTRY: list = [
    ToolCapability(command=c, name=n, roadmap_id=rid, runtime=rt, status=st,
                   domain=dom, description=desc)
    for (c, n, rid, rt, st, dom, desc) in _REGISTRY_SEED
]
