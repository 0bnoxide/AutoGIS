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
    "validate-config": Runtime.CLOUD,
    "manage-analyte-dict": Runtime.CLOUD,
    "validate-units": Runtime.CLOUD,
    "reconcile-locations": Runtime.HYBRID,
    "import-edd": Runtime.LOCAL,      # writes to GDB — needs arcpy
    "upgrade-schema": Runtime.LOCAL,   # phase 1.4
    "export-snapshot": Runtime.LOCAL,
    "evaluate-rpd": Runtime.CLOUD,
    "manage-screening-levels": Runtime.CLOUD,
    "optimize-callouts": Runtime.LOCAL,        # tool 5.2
    "manage-callout-overrides": Runtime.LOCAL, # tool 5.3
    "build-survey-form": Runtime.CLOUD, # tool 7.1a
    "compare-events": Runtime.CLOUD,   # tool 4.7
    "process-level-loop": Runtime.CLOUD,  # tool 8.1
    "identify-data-gaps": Runtime.CLOUD,  # tool 4.10
    "run-history-report": Runtime.CLOUD,  # tool 10.1
    "validate-schedule": Runtime.CLOUD,   # tool 10.2
    "apply-screening": Runtime.CLOUD,     # tool 3.5
    "compare-schedule-vs-actual": Runtime.CLOUD,  # tool 10.x
    "drone-checkpoint-qa": Runtime.CLOUD,  # tool 11.1
    "export-geojson": Runtime.CLOUD,  # tool 10.3
    "generate-arcade-labels": Runtime.CLOUD,  # tool 5.4
    "generate-event-changelog": Runtime.CLOUD,  # tool 9.3
    "export-lab-request": Runtime.CLOUD,  # tool 2.11 headless
    "generate-event-report": Runtime.CLOUD,  # tool 10.5
    "run-history": Runtime.CLOUD,  # tool 10.1b (query CLI)
    "import-rtk-survey": Runtime.LOCAL,  # writes to GDB — needs arcpy
    "route-survey123": Runtime.LOCAL,    # writes to GDB — needs arcpy
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
# `runtime` here is a display string (CLOUD = headless, LOCAL = needs arcpy,
# DRAFT = pre-production stub) and may differ in spelling from the Runtime enum.
from dataclasses import dataclass as _dataclass


@_dataclass
class ToolCapability:
    """Human-facing metadata for one CLI command (discovery only)."""
    command: str
    name: str = ""
    roadmap_id: str = ""
    runtime: str = "CLOUD"     # CLOUD | LOCAL | DRAFT
    status: str = "stable"     # stable | draft | planned
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
    ("validate-config", "ValidateEnvConfig", "", "CLOUD", "stable", "admin",
     "Validate env config + filename patterns"),
    ("manage-analyte-dict", "ManageAnalyteDict", "", "CLOUD", "stable", "admin",
     "Inspect/edit the analyte dictionary"),
    ("manage-screening-levels", "ManageScreeningLevels", "", "DRAFT", "draft",
     "admin", "Manage screening levels (DRAFT pre-production stub)"),
    ("validate-units", "ValidateUnits", "", "CLOUD", "stable", "qa",
     "Validate and convert result units"),
    ("reconcile-locations", "ReconcileSampleLocations", "", "CLOUD", "stable",
     "qa", "Reconcile sample location IDs against the well list"),
    ("evaluate-rpd-qa", "EvaluateRPDQA", "", "CLOUD", "stable", "qa",
     "Evaluate duplicate RPD QA from records"),
    ("evaluate-rpd", "EvaluateRPD", "", "CLOUD", "stable", "qa",
     "Evaluate relative percent difference for duplicates"),
    ("evaluate-readiness", "EvaluateReportReadiness", "", "CLOUD", "stable",
     "qa", "Evaluate report readiness against QA history"),
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
    ("export-report-format-summary-tables", "ExportSummaryTables", "", "CLOUD",
     "stable", "reporting", "Export formatted summary-table workbook"),
    ("export-geojson", "ExportGeoJSON", "10.3", "CLOUD", "stable", "reporting",
     "Export results to GeoJSON"),
    ("export-geopackage", "ExportEnvGeoPackage", "", "CLOUD", "stable",
     "reporting", "Export env data to a GeoPackage"),
    ("export-snapshot", "ExportEventSnapshot", "", "LOCAL", "stable",
     "reporting", "Export an event snapshot"),
    ("generate-event-report", "GenerateMonitoringEventReport", "10.5", "CLOUD",
     "stable", "reporting", "Generate a monitoring event report"),
    ("generate-reg-tables", "GenerateRegulatoryTables", "", "CLOUD", "stable",
     "reporting", "Build regulatory comparison tables"),
    ("generate-site-narrative", "GenerateSiteNarrative", "", "CLOUD", "stable",
     "reporting", "Generate a site narrative draft"),
    ("build-report-package", "BuildReportFigurePackage", "", "CLOUD", "stable",
     "reporting", "Assemble a deliverable figure package"),
    ("build-report-appendix", "BuildMonitoringReportAppendix", "9.2", "CLOUD",
     "stable", "reporting", "Build multi-sheet analytical appendix workbook"),
    ("run-history-report", "RunHistorySummaryReport", "10.1", "CLOUD", "stable",
     "admin", "Summarize run history"),
    ("run-history", "RunHistoryQuery", "10.1b", "CLOUD", "stable", "admin",
     "Query the run-history log"),
    ("validate-schedule", "ValidateScheduleYAML", "10.2", "CLOUD", "stable",
     "admin", "Validate a monitoring schedule YAML"),
    ("compare-events", "CompareMonitoringEvents", "4.7", "CLOUD", "stable",
     "analysis", "Compare two monitoring events"),
    ("apply-screening", "ApplyScreening", "3.5", "CLOUD", "stable", "analysis",
     "Apply screening levels to normalized results"),
    ("build-max-result-dataset", "BuildMaxResultDataset", "", "CLOUD", "stable",
     "analysis", "Build cross-event max-detected dataset"),
    ("build-compliance-table", "BuildComplianceSummaryTable", "", "CLOUD",
     "stable", "analysis", "Build cross-event compliance matrix"),
    ("build-analytical-exceedance-event", "BuildAnalyticalExceedanceEvent",
     "4.4", "CLOUD", "stable", "analysis",
     "Build exceedance event dataset with ratio/tier enrichment"),
    ("build-dashboard-data-mart", "BuildDashboardDataMart", "", "CLOUD",
     "stable", "analysis", "Build denormalized dashboard mart tables"),
    ("estimate-gw-flow-direction", "EstimateGWFlowDirection", "", "CLOUD",
     "stable", "analysis", "Estimate groundwater flow direction from 3+ wells"),
    ("merge-event-results", "MergeEventResults", "", "CLOUD", "stable",
     "intake", "Merge multiple event result CSVs"),
    ("import-edd", "ImportLabEDD", "2.3", "LOCAL", "stable", "intake",
     "Import lab EDD CSV/XLSX into the GDB"),
    ("import-gdb", "ImportToGDB", "2", "LOCAL", "stable", "intake",
     "Import normalized tables into a file GDB"),
    ("export-lab-request", "ExportLabAnalyticalRequest", "2.11", "CLOUD",
     "stable", "intake", "Export a lab analytical request workbook"),
    ("upgrade-schema", "UpgradeGDBSchema", "1.4", "LOCAL", "stable", "admin",
     "Additive upgrade of the GDB schema"),
    ("build-event", "BuildCurrentEvent", "3", "LOCAL", "stable", "cartography",
     "Build the wide current-event table"),
    ("build-callouts", "BuildCallouts", "4", "LOCAL", "stable", "cartography",
     "Build analytical callout boxes"),
    ("optimize-callouts", "OptimizeCalloutPlacement", "5.2", "LOCAL", "stable",
     "cartography", "Optimize callout placement"),
    ("manage-callout-overrides", "ManageCalloutOverrides", "5.3", "LOCAL",
     "stable", "cartography", "Manage manual callout placement overrides"),
    ("gw-contours", "GroundwaterContours", "5", "LOCAL", "stable", "analysis",
     "Generate draft groundwater contour features"),
    ("export-figures", "ExportFigures", "6", "LOCAL", "stable", "cartography",
     "Export figure layouts"),
    ("full-pipeline", "FullPipeline", "7", "LOCAL", "stable", "admin",
     "Run the end-to-end local pipeline"),
    ("validate-db", "ValidateDatabase", "8", "LOCAL", "stable", "qa",
     "Validate the geodatabase contents"),
    ("build-survey-form", "BuildSurvey123Form", "7.1a", "CLOUD", "stable",
     "field", "Build a Survey123 XLSForm"),
    ("validate-rtk-survey", "ValidateRTKSurvey", "", "CLOUD", "stable", "field",
     "Validate an RTK survey point file"),
    ("import-rtk-survey", "ImportRTKSurveyPoints", "", "LOCAL", "stable",
     "field", "Import RTK survey points into the GDB"),
    ("route-survey123", "RouteSurvey123Submission", "", "LOCAL", "stable",
     "field", "Route a Survey123 submission into the GDB"),
    ("reconcile-survey123-lab", "ReconcileSurvey123Lab", "", "CLOUD", "stable",
     "qa", "Reconcile Survey123 field data against lab results"),
    ("process-level-loop", "ProcessLevelLoop", "8.1", "CLOUD", "stable",
     "field", "Process a differential level loop"),
    ("drone-checkpoint-qa", "DroneGCPCheckpointQA", "11.1", "CLOUD", "stable",
     "field", "QA drone GCP/checkpoint residuals"),
]

TOOL_REGISTRY: list = [
    ToolCapability(command=c, name=n, roadmap_id=rid, runtime=rt, status=st,
                   domain=dom, description=desc)
    for (c, n, rid, rt, st, dom, desc) in _REGISTRY_SEED
]
