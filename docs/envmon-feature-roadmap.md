# Additional Tools for a Hybrid ArcGIS Environmental Monitoring Automation Toolset

## Position

Your **hybrid harness** is the right architecture: local ArcGIS Pro toolbox GUI for analysts, command-line execution for batch/repeatability, and AGOL/cloud execution for shared publishing or distributed processing.

**Counterargument:** hybrid systems can become hard to maintain if each tool has its own parameters, logging style, schema assumptions, and execution behavior.

**Improvement:** add a shared **tool registry/config layer** so every tool uses the same conventions for inputs, outputs, logging, QA status, batch IDs, site IDs, event dates, figure specs, and error handling.

Your existing environmental-monitoring examples justify that approach: the groundwater potentiometric figure needs water-level/contour logic, the groundwater quality figures need analytical callout generation, and the soil quality figure needs multi-sample tabular callouts rather than simple labels.

---

## 1. High-Value Tool Categories to Add

Organize the toolset into these major modules:

| Module | Purpose |
|---|---|
| **Data intake tools** | Normalize Excel, CSV, EDD, AGOL, Survey123, lab exports |
| **QA/QC tools** | Catch bad wells, dates, units, duplicates, exceedances, schema drift |
| **Environmental analysis tools** | GWE, analytical, soil, vapor, trend, exceedance, plume tools |
| **Cartographic automation tools** | Labels, callouts, leaders, legends, map series, exports |
| **AGOL/cloud tools** | Publish, sync, dashboard updates, hosted feature maintenance |
| **Field workflow tools** | Field Maps/Survey123 package generation and post-field reconciliation |
| **Civil/GIS handoff tools** | Export to CAD, Civil 3D support files, surfaces, contours |
| **Reporting tools** | PDF map packs, Excel summary tables, Word report appendices |
| **Administration tools** | Schema versioning, config validation, job tracking, audit logs |

---

## 2. Data Intake and Normalization Tools

### 2.1 Workbook Profile Builder

**Tool name:** `CreateWorkbookParserProfile`

Automatically inspects an unknown workbook and drafts a YAML/JSON parser profile.

**Inputs**

- Workbook path
- Optional target data type: `GW`, `SOIL`, `METALS`, `IBI`, `RPD`, `UNKNOWN`
- Optional known site ID

**Outputs**

- Draft parser profile
- Workbook structure report
- QA report

**Automates**

- Sheet discovery
- Header row detection
- Date column detection
- Sample/location column detection
- Analyte row/unit row/screening row detection
- Merged-cell context review
- Formula cell inventory

**ROI:** high. This reduces the effort needed each time you get a slightly different lab/client spreadsheet.

---

### 2.2 Environmental Workbook Batch Importer

**Tool name:** `BatchImportEnvironmentalWorkbooks`

Processes many workbooks across many sites.

**Inputs**

- Folder of workbooks
- Site lookup table
- Parser profile folder
- Target geodatabase
- Import mode: validate only, append, replace event, replace batch

**Outputs**

- Normalized tables
- Batch QA report
- Import manifest

**Key feature**

Uses filename, workbook content, or a site lookup table to route each workbook to the correct parser profile.

---

### 2.3 Lab EDD Importer

**Tool name:** `ImportLabEDD`

Many labs can provide EDD-style CSV/XLSX outputs even when the formal report workbook is ugly.

**Inputs**

- EDD file
- Lab format config
- Analyte dictionary
- Screening-level config

**Outputs**

- `Env_Samples`
- `Env_AnalyticalResults`
- `Env_ImportQA`

**Why add it**

If even one lab can provide consistent EDD exports, this becomes more reliable than report-table parsing.

---

### 2.4 Historical Data Migration Tool

**Tool name:** `MigrateLegacyMonitoringData`

Converts old project-specific spreadsheets, geodatabases, shapefiles, or joined feature classes into your normalized schema.

**Use cases**

- Older sites with years of one-off Excel tables
- Feature classes with analytical fields hard-coded as columns
- Archived map packages
- Prior report tables

**Output**

A clean historical database that your new tools can use for trend maps and time-series charts.

---

### 2.5 Attachment and Source-Document Registrar

**Tool name:** `RegisterSourceDocuments`

Creates records linking source workbooks, PDFs, lab reports, field forms, and map outputs to import batches.

**Fields**

- `DocumentID`
- `SiteID`
- `EventDate`
- `DocumentType`
- `PathOrURL`
- `Hash`
- `ImportBatchID`
- `ReviewedBy`
- `ReviewStatus`

**Why it matters**

It gives you auditability. You can answer: "Which workbook produced this map?"

---

## 3. QA/QC Tools

### 3.1 Universal Environmental Data Validator

**Tool name:** `ValidateEnvironmentalDatabase`

Runs all QA rules against the database.

| QA check | Severity |
|---|---|
| Missing site ID | Error |
| Missing location ID | Error |
| Unknown location not in well/boring layer | Error |
| Duplicate location/date/analyte | Warning or error |
| Unknown analyte alias | Warning |
| Unknown units | Warning |
| Nondetect parsed as numeric zero | Critical |
| Exceedance without screening level | Warning |
| Groundwater elevation above measuring point | Error |
| Dry well used for contouring | Error |
| Formula error from workbook | Error |
| Callout collision | Warning |
| Missing required map layer | Error |

**Output**

- QA feature/table
- Markdown report
- CSV report
- JSON summary for command/cloud harness

---

### 3.2 Well/Location Reconciliation Tool

**Tool name:** `ReconcileSampleLocations`

Compares source workbook location IDs against GIS features.

**Handles**

- `MW-1` vs `MW-01`
- `MW1` vs `MW-1`
- `HSS-11` vs `HSS11`
- Abandoned/destroyed wells
- Duplicate sample IDs
- Parent/duplicate sample matching

**Output**

- Match table
- Suggested aliases
- Unmatched sample locations
- GIS wells missing from event

**High ROI:** this directly targets one of the most common join-failure problems.

---

### 3.3 Analyte Dictionary Manager

**Tool name:** `ManageAnalyteDictionary`

GUI/CLI tool to maintain canonical analyte names, aliases, abbreviations, units, method groups, and default display order.

**Example**

| Alias | Canonical | Abbrev | Group |
|---|---|---|---|
| Total Xylenes | Xylenes | X | VPH |
| Methyl tert-butyl ether | MTBE | MTBE | VPH |
| C11-C22 Aromatics | C11-C22 Aromatics | C11-C22 | EPH |

**Why add it**

The analytical callout tools will only be as reliable as the analyte dictionary.

---

### 3.4 Screening-Level Manager

**Tool name:** `ManageScreeningLevels`

Maintains regulatory thresholds by:

- state/program,
- matrix,
- analyte,
- units,
- effective date,
- source citation,
- site-specific override.

**Supports**

- MDEQ RBSL
- EPA RSL
- site-specific cleanup levels
- client-specific thresholds
- Montana/Arizona/Colorado/etc. jurisdiction configs

**Important design point**

Do not hard-code screening levels into scripts. Put them in a versioned config/table.

---

### 3.5 Unit Normalization and Conversion Validator

**Tool name:** `ValidateAndConvertUnits`

Checks and optionally converts units.

**Examples**

- `µg/L` to `mg/L`
- `ug/L` to `µg/L`
- `mg/kg` retained for soil
- `ft bgs` retained for depths

**Rules**

- Convert only when explicit conversion is configured.
- QA error when units are unknown.
- Preserve raw source unit.

---

### 3.6 Duplicate/RPD Evaluator

**Tool name:** `EvaluateDuplicateRPD`

Parses parent/duplicate pairs and evaluates RPD.

**Inputs**

- Analytical results
- Duplicate mapping table
- RPD criteria config

**Outputs**

- RPD table
- Flags by analyte
- QA report

**Useful because**

Your source workbook includes an RPD-style sheet. A dedicated tool prevents formula errors like `#VALUE!` from becoming invisible QA problems.

---

## 4. Environmental Analysis Tools

### 4.1 Groundwater Elevation Event Builder

**Tool name:** `BuildGroundwaterElevationEvent`

Creates event-specific groundwater elevation records and mapping fields.

**Outputs**

- `Env_CurrentWaterLevelEvent`
- label fields
- contour inclusion/exclusion summary
- hydrograph-ready table

**Flags**

- `Dry`
- `NM`
- `NS`
- anomalous groundwater elevation
- excluded from contouring
- perched/separate zone if configured

---

### 4.2 Draft Potentiometric Contour Generator

**Tool name:** `GenerateDraftGWContours`

Generates reviewable contours.

**Inputs**

- Event water levels
- Use-for-contour flag
- Boundary
- Interpolation method
- Contour interval
- Exclusion table

**Outputs**

- Draft contours
- Contour input points
- QA report
- Optional flow arrow feature

**Guardrail**

The tool should mark outputs as `DRAFT_REVIEW_REQUIRED`.

---

### 4.3 Groundwater Flow Direction Helper

**Tool name:** `EstimateGWFlowDirection`

Computes a draft flow direction from selected wells or a fitted plane.

**Inputs**

- Valid water-level points
- Optional user-selected control wells
- Site boundary

**Outputs**

- Draft flow arrow
- Gradient estimate
- QA confidence rating

**Caution**

This should never silently generate a final professional interpretation.

---

### 4.4 Analytical Exceedance Event Builder

**Tool name:** `BuildAnalyticalExceedanceEvent`

Creates map-ready exceedance records.

**Supports**

- specific event date,
- latest event,
- date range,
- maximum exceedance,
- only detected,
- only exceeding,
- all analytes,
- custom analyte list.

**Outputs**

- `Env_CurrentEventWide`
- `HasDetection`
- `HasExceedance`
- analyte display fields
- analyte style fields

---

### 4.5 Plume Boundary Assist Tool

**Tool name:** `GenerateDraftPlumeBoundary`

Creates draft concentration plume polygons.

**Inputs**

- Analyte
- Event date
- Result field
- Threshold
- Interpolation method
- Boundary/clipping layer
- Manual control points, optional

**Outputs**

- Draft plume polygons
- Isoconcentration contours
- QA report

**Use cautiously**

Good for draft figure prep, not final interpretation without review.

---

### 4.6 Trend Analysis Tool

**Tool name:** `GenerateWellTrendCharts`

Creates hydrographs or concentration trend plots.

**Inputs**

- Site ID
- Well IDs
- Analytes
- Date range
- Matrix
- Output folder

**Outputs**

- PNG charts
- PDF chart packet
- trend summary CSV
- optional AGOL dashboard-ready table

**Useful additions**

- Mann-Kendall trend flag
- latest vs prior event comparison
- exceedance timeline

---

### 4.7 Event Comparison Tool

**Tool name:** `CompareMonitoringEvents`

Compares current event to previous event.

**Outputs**

| Field | Description |
|---|---|
| `CurrentResult` | Latest value |
| `PreviousResult` | Prior event value |
| `Delta` | Numeric change |
| `PercentChange` | Percent change |
| `TrendClass` | Increased, decreased, stable, new detection, no longer detected |
| `CurrentExceedance` | yes/no |
| `PriorExceedance` | yes/no |

**Map use**

Symbolize wells by increase/decrease or new exceedance.

---

### 4.8 Soil Sample Interval Selector

**Tool name:** `SelectSoilIntervalsForMapping`

For soil analytical maps, chooses which intervals appear in callouts.

**Rules**

- all depths,
- shallowest,
- deepest,
- highest result,
- highest exceedance,
- configured interval list,
- excavation confirmation samples only.

**Output**

Map-ready sample selection table.

---

### 4.9 Maximum Result Mapper

**Tool name:** `BuildMaxResultMapDataset`

Creates one record per location showing maximum result over a date range or project history.

**Useful for**

- closure reports,
- risk maps,
- excavation planning,
- remedial design support.

---

### 4.10 Data Gap Identifier

**Tool name:** `IdentifyMonitoringDataGaps`

Finds wells or analytes missing from expected monitoring events.

**Inputs**

- monitoring schedule config,
- required analyte list,
- well network,
- date range.

**Outputs**

- missing samples,
- missed analytes,
- dry/inaccessible wells,
- map layer of data gaps.

---

## 5. Cartographic Automation Tools

### 5.1 Analytical Callout Builder

You already have this concept. Expand it into multiple templates.

**Tool name:** `BuildAnalyticalCallouts`

Templates:

| Template | Purpose |
|---|---|
| `compact_key_value` | Small analytical callouts |
| `gw_vph_eph_table` | ZT42-style groundwater table |
| `soil_multi_depth_table` | ZT42-style soil callout |
| `metals_table` | Metals results |
| `ibi_table` | Intrinsic biodegradation indicators |
| `exceedance_only` | Compact exceedance callout |
| `custom_analyte_grid` | User-defined analyte combination |

---

### 5.2 Callout Placement Optimizer

**Tool name:** `OptimizeCalloutPlacement`

Runs after callout generation.

**Functions**

- detect overlapping callout boxes,
- detect leaders crossing boxes,
- detect callouts outside map frame,
- try alternate quadrants,
- write suggested overrides,
- flag unresolved collisions.

**Output**

- updated placement table,
- collision QA layer,
- before/after score.

---

### 5.3 Manual Callout Override Manager

**Tool name:** `ManageCalloutPlacementOverrides`

A GUI tool for maintaining override points.

**Workflow**

1. User manually moves override anchor points.
2. Tool writes offsets/anchors to override table.
3. Callouts regenerate from overrides.
4. Final placement survives future data refreshes.

**This is important.** Without it, automatic regeneration will erase manual cartographic refinement.

---

### 5.4 Label Expression Generator

**Tool name:** `GenerateArcadeLabelExpressions`

Creates Arcade expressions from figure specs.

**Use cases**

- simple water-level labels,
- compact analytical labels,
- fallback labels when callout features are not generated,
- AGOL web map popups/labels.

**Outputs**

- `.txt` Arcade expressions,
- field mapping,
- layer configuration JSON.

---

### 5.5 Legend and Analytical Key Builder

**Tool name:** `BuildAnalyticalKey`

Creates or updates an analytical key/table for map layouts.

**Inputs**

- figure spec,
- analyte dictionary,
- screening level source,
- units,
- detected/exceedance style config.

**Outputs**

- layout text,
- table graphics,
- optional geodatabase table,
- QA if analytes lack abbreviations.

---

### 5.6 Map Series Generator

**Tool name:** `GenerateSiteMapSeries`

Builds figure packets across many sites/events.

**Examples**

- one PDF per site,
- one PDF per map type,
- combined report appendix,
- historical event map series.

**Inputs**

- site list,
- event list,
- figure spec folder,
- output folder.

---

### 5.7 Export Package Builder

**Tool name:** `BuildReportFigurePackage`

Creates a structured deliverable folder.

```text
Exports/
  SiteID/
    2026_Q2/
      PDFs/
      PNGs/
      QA/
      Tables/
      SourceDataManifest/
      APRX/
```

**Adds**

- export log,
- file manifest,
- import batch summary,
- map QA summary.

---

### 5.8 Dynamic Text Updater

**Tool name:** `UpdateLayoutDynamicText`

Batch-updates:

- site name,
- address,
- figure number,
- event date,
- project number,
- prepared by,
- reviewed by,
- report date,
- notes,
- regulatory basis.

---

## 6. AGOL/Cloud Tools

### 6.1 Hosted Feature Layer Publisher

**Tool name:** `PublishEnvironmentalLayersToAGOL`

Publishes or updates hosted layers.

**Inputs**

- local geodatabase or service definition,
- AGOL item config,
- sharing settings,
- overwrite mode.

**Outputs**

- hosted feature layer URL/item ID,
- publish log,
- QA report.

**Use cases**

- internal web maps,
- client dashboards,
- field review maps,
- monitoring network status maps.

---

### 6.2 AGOL Sync/Downloader

**Tool name:** `SyncAGOLFeatureLayerToGDB`

Downloads hosted feature layer edits into local FGDB.

**Use cases**

- field-collected well status,
- sample collection status,
- access constraints,
- photo attachments,
- staff comments.

---

### 6.3 Web Map Updater

**Tool name:** `UpdateAGOLWebMapFromFigureSpec`

Updates layer visibility, definition queries, popups, labels, and symbology in a web map.

**Good for**

- dashboard map refresh,
- event-specific web map views,
- client portal updates.

---

### 6.4 Dashboard Data Refresh Tool

**Tool name:** `RefreshMonitoringDashboardData`

Builds dashboard-specific tables:

- latest exceedances,
- wells sampled this event,
- missing samples,
- concentration trends,
- groundwater elevation summary,
- QA status.

---

### 6.5 AGOL Attachment Manager

**Tool name:** `SyncFieldAttachments`

Downloads and catalogs:

- field photos,
- well condition photos,
- sampling forms,
- lab reports,
- site sketches.

**Outputs**

- local document folder,
- attachment index table,
- related records in geodatabase.

---

### 6.6 Hosted Layer Schema Auditor

**Tool name:** `AuditAGOLSchemaAgainstLocalConfig`

Compares hosted feature schemas against your local schema/config.

**Flags**

- missing fields,
- type mismatches,
- domain mismatches,
- broken relationships,
- unexpected fields,
- field aliases that changed.

---

## 7. Field Workflow Tools

### 7.1 Field Maps Project Builder

**Tool name:** `BuildFieldMapsMonitoringProject`

Creates or refreshes layers for field crews.

**Layers**

- monitoring wells,
- sample status,
- water-level measurements,
- access notes,
- photo points,
- issue flags.

**Fields**

- `Sampled`
- `SampleDate`
- `Sampler`
- `DTW`
- `PurgeVolume`
- `AccessIssue`
- `WellCondition`
- `PhotoRequired`
- `Notes`

---

### 7.2 Sampling Event Planner

**Tool name:** `CreateSamplingEventPlan`

Generates a planned sampling event.

**Inputs**

- well network,
- required analyte groups,
- sampling frequency,
- prior event data,
- access constraints.

**Outputs**

- planned sample list,
- bottle count estimate,
- field map layer,
- chain-of-custody draft table,
- missing-prior-data warnings.

---

### 7.3 Field Data Reconciliation Tool

**Tool name:** `ReconcileFieldAndLabData`

Compares field sample records to lab results.

**Flags**

- lab sample not in field records,
- field sample missing lab result,
- date mismatch,
- sample ID mismatch,
- duplicate mismatch,
- matrix mismatch,
- location mismatch.

**High ROI:** catches common reporting mistakes before map production.

---

### 7.4 Well Inspection Photo Report Tool

**Tool name:** `GenerateWellInspectionPhotoReport`

Uses attachments and well status fields to generate photo logs.

**Outputs**

- PDF photo log,
- Word appendix,
- photo index table.

---

## 8. Civil 3D / CAD / Survey Handoff Tools

### 8.1 Export GIS Layers to CAD Package

**Tool name:** `BuildCADExportPackage`

Creates Civil 3D-ready DWG/DXF exports.

**Inputs**

- selected GIS layers,
- layer mapping config,
- coordinate system,
- output DWG folder.

**Outputs**

- CAD export,
- layer mapping report,
- projection note,
- QA report.

**Use cases**

- site base maps,
- excavation extents,
- well locations,
- contours,
- plume boundaries.

---

### 8.2 Create Civil 3D Contour/Surface Support Files

**Tool name:** `ExportContoursForCivil3D`

Exports draft groundwater contours or surface inputs.

**Outputs**

- contour polylines,
- point CSV,
- LandXML/TIN support if implemented,
- metadata report.

---

### 8.3 Survey Import Validator

**Tool name:** `ValidateSurveyDeliverable`

Checks survey CSV/CAD/GIS data before import.

**Flags**

- duplicate point IDs,
- missing elevations,
- invalid codes,
- coordinate outliers,
- wrong units,
- wrong coordinate system,
- missing control points.

---

### 8.4 Drone Orthomosaic/DSM Registrar

**Tool name:** `RegisterDroneSurveyProducts`

Catalogs drone deliverables.

**Tracks**

- orthomosaic,
- DSM,
- DEM,
- point cloud,
- control report,
- processing date,
- coordinate system,
- accuracy notes.

---

## 9. Reporting and Deliverable Automation Tools

### 9.1 Analytical Summary Table Exporter

**Tool name:** `ExportAnalyticalSummaryTables`

Generates Excel tables from normalized results.

**Supports**

- current event,
- historical by well,
- exceedance-only,
- analyte group,
- soil by depth,
- GW by monitoring event,
- duplicate/RPD summary.

**Output**

- formatted Excel workbook,
- CSV tables,
- QA summary.

---

### 9.2 Report Appendix Builder

**Tool name:** `BuildMonitoringReportAppendix`

Combines:

- exported maps,
- analytical tables,
- QA summaries,
- trend charts,
- photo logs.

**Outputs**

- PDF appendix package,
- file manifest.

---

### 9.3 Change Log Generator

**Tool name:** `GenerateEventChangeLog`

Creates a human-readable summary:

```text
Imported Q2 2026 groundwater event.
38 samples imported.
7 detected benzene results.
3 benzene exceedances.
2 wells dry.
1 unmatched location ID.
Draft contours generated from 9 wells.
2 callout collisions require review.
```

Useful for project managers and reviewers.

---

### 9.4 Reviewer Markup Ingest Tool

**Tool name:** `IngestReviewerMapComments`

If reviewers mark up PDFs or provide comment spreadsheets, ingest them into a review tracking table.

**Fields**

- figure,
- comment,
- reviewer,
- status,
- assigned to,
- resolved date,
- resolution note.

---

## 10. Administration and DevOps-Style Tools

### 10.1 Tool Registry Viewer

**Tool name:** `ListAvailableEnvTools`

Lists all tools available through:

- command harness,
- ArcGIS Pro toolbox,
- AGOL/cloud harness.

**Outputs**

- tool name,
- version,
- execution mode,
- required inputs,
- last modified,
- owner,
- status.

---

### 10.2 Config Validator

**Tool name:** `ValidateEnvConfig`

Checks all YAML/JSON configs before running.

**Validates**

- parser profile syntax,
- figure spec syntax,
- analyte dictionary references,
- screening level references,
- layout names,
- layer names,
- required fields,
- output filename patterns.

**This is one of the highest-value additions.**

---

### 10.3 Schema Migration Tool

**Tool name:** `UpgradeEnvMonitoringGDBSchema`

Version-controls your geodatabase schema.

**Example**

```text
Schema v1.2 → v1.3:
- Add IsEstimated field
- Add SourceCell field
- Add FigureSpecID to callout layers
- Add DisplayColorClass domain
```

**Prevents**

- old project databases failing silently,
- field missing errors,
- inconsistent tool behavior.

---

### 10.4 Job Runner and Queue Manager

**Tool name:** `RunEnvJobQueue`

Runs multiple jobs from a manifest.

Example manifest:

```yaml
jobs:
  - site_id: H281
    workbook: H281_Glasgow_Data_Tables.xlsx
    figures: [GWE, GW_ANALYTICAL]
  - site_id: ZT42
    workbook: ZT42_Data.xlsx
    figures: [SOIL_ANALYTICAL, GW_ANALYTICAL]
```

**Execution modes**

- local command line,
- ArcGIS Pro toolbox,
- scheduled task,
- cloud/AGOL where applicable.

---

### 10.5 Run History Dashboard Table

**Tool name:** `WriteRunHistory`

Every tool execution writes a record.

**Fields**

- `RunID`
- `ToolName`
- `ToolVersion`
- `ExecutionMode`
- `User`
- `StartTime`
- `EndTime`
- `Status`
- `SiteID`
- `EventDate`
- `InputHash`
- `OutputPaths`
- `ErrorCount`
- `WarningCount`

This makes the system auditable.

---

### 10.6 Automated Test Data Generator

**Tool name:** `GenerateSyntheticEnvWorkbook`

Creates fake but realistic workbooks for testing.

**Includes**

- merged headers,
- formulas,
- nondetects,
- qualifiers,
- missing dates,
- unknown wells,
- RPD values,
- soil depths,
- metals,
- IBI data.

**Why useful**

You can test parser hardening without exposing project data.

---

## 11. AI-Assisted Tools to Add

### 11.1 AI Parser Profile Draft Assistant

**Tool name:** `AIDraftParserProfile`

Uses an LLM to inspect workbook structure summaries and propose parser YAML.

**Guardrail**

The AI should only draft config. The deterministic parser still performs the import.

**Input**

- workbook inspection JSON
- example profile
- sheet preview values

**Output**

- draft parser profile
- confidence notes
- fields requiring human confirmation.

---

### 11.2 AI QA Explanation Generator

**Tool name:** `AIExplainQAReport`

Turns machine QA into a readable summary.

Example:

```text
The import completed with 2 errors and 14 warnings. The blocking errors are:
1. MW-07 appears in the workbook but not in the monitoring well feature class.
2. Benzene has results in µg/L, but the configured screening level is in mg/L and no conversion rule exists.
```

Useful for less technical staff.

---

### 11.3 AI Figure Spec Assistant

**Tool name:** `AIDraftFigureSpec`

Generates a draft figure spec from:

- selected analytes,
- desired map type,
- example figure style,
- site config.

**Output**

- YAML figure spec
- callout template
- required layer list.

---

### 11.4 AI Map Review Assistant

**Tool name:** `AIMapReviewChecklist`

Given map export metadata and QA results, generate a review checklist.

Checks:

- missing title/date,
- empty required layers,
- too many callout collisions,
- unresolved QA errors,
- contour review status,
- missing analytical key,
- unmatched wells.

---

## 12. Prioritized Short List

For the most immediate ROI, add these first:

| Priority | Tool | Why |
|---:|---|---|
| 1 | `ValidateEnvConfig` | Prevents failed runs from bad YAML/JSON |
| 2 | `ReconcileSampleLocations` | Fixes the most common join/import issue |
| 3 | `ManageAnalyteDictionary` | Stabilizes all analytical tools |
| 4 | `ManageScreeningLevels` | Stabilizes exceedance logic |
| 5 | `BatchImportEnvironmentalWorkbooks` | Scales across many small sites |
| 6 | `BuildCurrentEventTables` enhancements | Enables flexible analyte combinations |
| 7 | `OptimizeCalloutPlacement` | Reduces manual cartographic cleanup |
| 8 | `RunEnvJobQueue` | Lets the harness process many tasks reliably |
| 9 | `ExportAnalyticalSummaryTables` | Produces report-ready tables from the same data |
| 10 | `WriteRunHistory` | Adds auditability and troubleshooting |

---

## 13. Suggested Toolset Architecture

Use a shared core package:

```text
envmon/
  core/
    config.py
    registry.py
    logging.py
    qa.py
    schema.py
    paths.py
  parsers/
    excel.py
    lab_edd.py
    fieldmaps.py
  analysis/
    groundwater.py
    analytical.py
    soil.py
    trends.py
    rpd.py
  cartography/
    callouts.py
    placement.py
    labels.py
    layouts.py
    export.py
  agol/
    publish.py
    sync.py
    webmaps.py
    dashboards.py
  cad/
    export_cad.py
    civil3d.py
  tools/
    pyt_tools.py
    cli_tools.py
    cloud_jobs.py
```

Then expose the same functions through:

```text
ArcGIS Pro Toolbox GUI
        ↓
same Python core
        ↑
Command-line harness
        ↑
AGOL/cloud harness
```

Avoid writing separate logic for each execution environment.

---

## 14. Tool Registry Concept

Add a `tools.yaml` registry:

```yaml
tools:
  ValidateEnvConfig:
    version: 1.0.0
    modes: [cli, pro_toolbox, cloud]
    category: administration
    requires_arcpy: false
    writes_gdb: false
    description: Validate YAML/JSON configuration files.

  BuildAnalyticalCallouts:
    version: 1.0.0
    modes: [cli, pro_toolbox]
    category: cartography
    requires_arcpy: true
    writes_gdb: true
    description: Generate analytical callout boxes, grid lines, leaders, and text anchors.

  PublishEnvironmentalLayersToAGOL:
    version: 1.0.0
    modes: [cli, cloud]
    category: agol
    requires_arcpy: false
    writes_gdb: false
    description: Publish or update hosted feature layers.
```

This allows your harness to know:

- what can run where,
- what requires ArcPy,
- what writes to a geodatabase,
- what can run in cloud,
- what is safe for batch processing.

---

## 15. Best Next Build Sequence

### Phase 1 — Stabilize the Framework

1. `ValidateEnvConfig`
2. `WriteRunHistory`
3. `ValidateEnvironmentalDatabase`
4. `UpgradeEnvMonitoringGDBSchema`
5. `RunEnvJobQueue`

### Phase 2 — Improve Data Reliability

6. `ReconcileSampleLocations`
7. `ManageAnalyteDictionary`
8. `ManageScreeningLevels`
9. `ValidateAndConvertUnits`
10. `EvaluateDuplicateRPD`

### Phase 3 — Improve Production Output

11. `OptimizeCalloutPlacement`
12. `ManageCalloutPlacementOverrides`
13. `BuildAnalyticalKey`
14. `GenerateSiteMapSeries`
15. `BuildReportFigurePackage`

### Phase 4 — Expand Deliverables

16. `GenerateWellTrendCharts`
17. `CompareMonitoringEvents`
18. `ExportAnalyticalSummaryTables`
19. `BuildMonitoringReportAppendix`
20. `PublishEnvironmentalLayersToAGOL`

---

## Recommended Immediate Addition

Build **`ValidateEnvConfig`** next.

It is not flashy, but it will prevent the most failures as the toolset grows. After that, build **`ReconcileSampleLocations`** and **`OptimizeCalloutPlacement`**. Those three will improve reliability, reduce manual edits, and make the hybrid harness easier to trust.
