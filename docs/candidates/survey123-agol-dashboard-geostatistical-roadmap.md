# Survey123, AGOL, Dashboard, Report, Database, and Groundwater Geostatistical Pipeline Heavy Hitters

## Executive Summary

The strongest remaining opportunities are operational systems that connect Survey123 field capture, AGOL hosted data, dashboard outputs, report packages, and geostatistical modeling pipelines.

The highest-value additions are:

1. `RunFieldToGroundwaterModelPipeline`
2. `BuildDashboardDataMart`
3. `ReconcileSurvey123AndLabResults`
4. `BuildSurvey123XLSFormFromConfig`
5. `PublishDashboardFromSpec`
6. `AuditAGOLItemDependencies`
7. `ExportEventDatabaseSnapshot`
8. `EvaluateReportReadiness`
9. `GenerateRegulatoryTables`
10. `PromoteAGOLDataBetweenStages`

A turnkey groundwater model pipeline is realistic as a draft/review workflow, not as an unsupervised final hydrogeologic interpretation.

---

# 1. Biggest Additions

## Tier 1 heavy hitters

| Tool / Pipeline | Value |
|---|---|
| Survey123 Sampling Event Manager | Turns a monitoring event into field assignments, expected samples, sample status, and reconciliation outputs. |
| Survey123-to-Lab-to-GIS Reconciliation Pipeline | Compares field-submitted samples, COC/sample IDs, lab data, and GIS well IDs. |
| AGOL Dashboard Data Mart Builder | Generates clean dashboard tables instead of making dashboards query raw operational data. |
| Groundwater Surface Modeling Pipeline | Converts TOC/coordinate/DTW inputs into GWE points, QA, kriging/IDW/TIN outputs, contours, uncertainty surfaces, and review maps. |
| Hosted Feature Layer Schema Auditor/Publisher | Keeps AGOL layers, views, forms, dashboards, and local geodatabases synchronized. |
| Survey123 Report Packet Generator | Uses Survey123 report templates to create well inspection reports, sampling forms, incident reports, and event summaries. |
| Automated Dashboard Generator/Updater | Builds or updates AGOL dashboards from a config file: indicators, lists, serial charts, maps, filters, and item IDs. |
| Regulatory Exceedance Notification Engine | Pushes alerts when new lab results exceed screening levels or when field results fail QA. |
| Client Portal Package Builder | Publishes hosted layers, web maps, dashboards, PDFs, reports, and metadata into a controlled AGOL group. |
| Data Quality Scorecard System | Gives every site/event a pass/warning/fail score for field, lab, GIS, and report readiness. |

---

# 2. Survey123-Heavy Tools

## 2.1 Sampling Event Generator

**Tool name:** `CreateSurvey123SamplingEvent`

Generates the complete planned event before fieldwork.

### Inputs

- Site ID
- Event date or quarter
- Monitoring well network
- Required analyte groups
- Required field measurements
- Prior event status
- Access constraints
- Bottle/preservation config
- Lab method config

### Outputs

- Survey123 planned sample records
- AGOL hosted feature layer records
- Field crew assignment table
- Expected sample list
- Sample bottle count estimate
- COC draft table
- Dashboard-ready event status table

---

## 2.2 Smart Survey123 Form Builder

**Tool name:** `BuildSurvey123XLSFormFromConfig`

Automatically creates or updates an XLSForm from site/event configuration.

### Generates

- Well dropdowns filtered by site
- Relevant choices for matrix
- DTW fields
- TOC reference display
- Calculated groundwater elevation
- Sample ID builder
- Sample bottle checklist
- Photo questions
- Well condition checklist
- Purge/water quality readings
- QA warnings inside the form

---

## 2.3 Survey123 Webhook Event Router

**Tool name:** `RouteSurvey123Submission`

When a field record is submitted:

1. Validate required fields.
2. Recalculate GWE.
3. Flag anomalous DTW.
4. Update AGOL dashboard status.
5. Create a QA record.
6. Notify PM if critical condition exists.
7. Write to local/enterprise database through the harness.
8. Optionally generate a Survey123 report.

---

## 2.4 Survey123 Field-to-Lab Reconciliation

**Tool name:** `ReconcileSurvey123AndLabResults`

Compares Survey123 submitted samples, COC records, lab EDD/workbook, and GIS monitoring well table.

### Flags

- Field sample missing from lab data
- Lab sample missing from field data
- Sample ID mismatch
- Date mismatch
- Matrix mismatch
- Duplicate sample mismatch
- Wrong analyte group
- Missing depth interval for soil
- Well marked dry but lab result exists
- Lab result exists for inactive well

---

## 2.5 Survey123 Well Inspection Report Generator

**Tool name:** `GenerateWellInspectionReports`

Generates standardized well inspection records.

### Outputs

- One PDF per well
- One PDF per site
- Photo appendix
- Well maintenance table
- AGOL item links
- Local report archive

---

# 3. AGOL and Dashboard Outputs

## 3.1 Dashboard Data Mart Builder

**Tool name:** `BuildDashboardDataMart`

Do not point dashboards directly at raw analytical tables. Build flattened, dashboard-specific feature layers/tables.

### Dashboard tables

```text
Dash_SiteStatus
Dash_EventStatus
Dash_WellStatus
Dash_CurrentExceedances
Dash_GWLevelSummary
Dash_AnalyticalSummary
Dash_FieldQA
Dash_LabQA
Dash_OpenIssues
Dash_ReportReadiness
```

---

## 3.2 Dashboard Config Publisher

**Tool name:** `PublishDashboardFromSpec`

Build or update dashboards from YAML.

### Config controls

- Dashboard title
- Web map item ID
- Indicator cards
- Serial charts
- Category selectors
- Date selectors
- Lists
- Embedded report links
- Filters
- Theme
- Refresh interval

---

## 3.3 AGOL Hosted View Builder

**Tool name:** `CreateHostedViewsForStakeholders`

Creates hosted feature layer views for different audiences.

| View | Filters / fields |
|---|---|
| Internal_QA_View | All fields, QA flags |
| Client_View | Approved fields only |
| Field_Crew_View | Only active wells and current event |
| Public_View | No sensitive analytical values |
| Regulatory_View | Approved exceedance/report data |

---

## 3.4 AGOL Item Dependency Auditor

**Tool name:** `AuditAGOLItemDependencies`

Checks relationships between hosted feature layers, views, web maps, dashboards, Survey123 forms, Experience Builder apps, and report items.

### Flags

- Dashboard points to deleted view
- Survey123 form points to old feature layer
- Web map references renamed layer
- Hosted view schema no longer matches source
- Stale item not modified in configured period
- Missing sharing group

---

## 3.5 Hosted Feature Layer Promotion Pipeline

**Tool name:** `PromoteAGOLDataBetweenStages`

Mimics software release environments:

```text
DEV -> QA -> PROD
```

### Workflow

1. Publish to DEV hosted feature layer.
2. Validate schema and data.
3. Promote to QA group.
4. Reviewer approves.
5. Promote to PROD dashboard/client group.

---

## 3.6 AGOL Backup and Restore System

**Tool name:** `BackupAGOLProjectItems`

Backs up hosted feature layers, hosted views, web maps, dashboards, Survey123 form items, feature report templates, item JSON, thumbnails, sharing settings, and item dependencies.

---

# 4. Turnkey Groundwater Geostatistical Model Pipeline

## Tool name

`BuildGroundwaterSurfaceModel`

## Purpose

Turn well coordinates, TOC elevations, and depth-to-water measurements into QA-controlled groundwater elevation points, prediction surfaces, uncertainty surfaces, contours, flow-direction products, dashboard layers, and report-ready maps.

---

## 4.1 Input Schema

### Required

| Field | Description |
|---|---|
| SiteID | Site identifier |
| EventID | Monitoring event |
| WellID | Monitoring well ID |
| X / Y or geometry | Well coordinates |
| TOC_Elev_ft | Top of casing elevation |
| DTW_ft | Depth to water from TOC |
| MeasurementDate | Date measured |
| MeasurementStatus | Measured, dry, NM, NS, inaccessible |
| UseForModel | Yes/no |
| HydroUnit | Shallow/deep/perched/etc., optional |
| BoundaryID | Model boundary, optional |

### Derived

```text
GWE_ft = TOC_Elev_ft - DTW_ft
```

---

## 4.2 Pipeline Stages

```text
Survey123 / Excel / AGOL / local GDB
        ↓
Normalize water-level event
        ↓
QA and hydrogeologic screening
        ↓
Build model-ready point layer
        ↓
Run candidate interpolation models
        ↓
Cross-validation / model scoring
        ↓
Select or rank model outputs
        ↓
Generate prediction raster
        ↓
Generate uncertainty raster
        ↓
Generate contours
        ↓
Generate flow vectors / gradient summary
        ↓
Publish to AGOL / dashboard / report / PDF
```

---

## 4.3 QA Before Modeling

Required QA checks:

| Check | Reason |
|---|---|
| DTW_ft < 0 | Invalid or artesian condition requiring review |
| GWE_ft > TOC_Elev_ft | Usually invalid unless artesian/survey issue |
| Dry/NM/NS used in model | Invalid |
| Fewer than 3 valid points | Cannot contour/interpolate meaningfully |
| Duplicate well/event measurements | Conflict |
| Large change from prior event | Possible measurement error |
| Wells in different screened intervals | May represent different hydrostratigraphic units |
| Wells outside boundary | Bad coordinates or wrong site |
| Local outlier relative to neighbors | Typo, separate zone, or true condition |
| TOC elevation missing | Cannot compute GWE |
| Coordinate missing | Cannot model spatially |
| Mismatched vertical datum | Critical |
| Mixed units | Critical |

---

## 4.4 Model Options

| Model | Use |
|---|---|
| TIN / linear interpolation | Small sites, few wells, transparent triangulation |
| IDW | Quick deterministic surface |
| Ordinary kriging | When spatial autocorrelation is defensible |
| Empirical Bayesian Kriging | More automated semivariogram handling and uncertainty outputs |
| Universal kriging / trend surface + residuals | Regional gradient plus local deviations |
| Spline | Smooth presentation surface, but can overshoot |
| Manual contour assist | Hydrogeologist-controlled interpretation |

---

## 4.5 Model Ranking Logic

**Tool name:** `EvaluateGroundwaterSurfaceModels`

Candidate outputs:

```text
Model_TIN
Model_IDW
Model_EBK_Prediction
Model_EBK_StandardError
Model_TrendSurface
Model_ManualControl
```

Cross-validation metrics:

| Metric | Meaning |
|---|---|
| Mean error | Bias |
| Root mean square error | Overall fit |
| Mean standardized error | Uncertainty calibration |
| RMS standardized error | Kriging uncertainty calibration |
| Percent within tolerance | Practical field tolerance |
| Hydro review flag | Professional judgment |

---

## 4.6 Turnkey Outputs

### Geodatabase outputs

```text
GW_ModelInputPoints
GW_ModelExcludedPoints
GW_ModelPredictionRaster
GW_ModelStandardErrorRaster
GW_ModelContours_Draft
GW_ModelFlowVectors_Draft
GW_ModelCrossValidation
GW_ModelQA
GW_ModelSummary
```

### AGOL outputs

```text
Hosted layer: Current GWE Points
Hosted layer: Draft GW Contours
Hosted layer: Model QA Points
Hosted imagery/tile/raster item: GWE Prediction Surface, if supported
Hosted layer/table: Model Summary
Dashboard view: Groundwater Model Review
```

---

# 5. Concentration Geostatistical Model Pipeline

## Tool name

`BuildAnalyticalConcentrationSurface`

### Inputs

- Normalized analytical results
- Selected analyte
- Event date
- Matrix
- Nondetect handling rule
- Screening level
- Site boundary

### Nondetect handling options

| Rule | Description |
|---|---|
| exclude_nondetects | Only detected values |
| use_half_rl | Use 0.5 × reporting limit |
| use_rl | Use reporting limit |
| use_zero | Generally avoid except specific agreed use |
| censored_model_placeholder | Future advanced method |

### Outputs

- Concentration prediction raster
- Exceedance probability raster
- Plume contour
- Uncertainty surface
- Detected/exceedance point layer
- QA report

---

# 6. Survey123 + Geostatistical Model Pipeline

## Tool name

`RunFieldToGroundwaterModelPipeline`

### Workflow

```text
1. Field crew submits Survey123 water-level event.
2. Webhook triggers event router.
3. Tool validates TOC, DTW, coordinates, well status.
4. Tool calculates groundwater elevation.
5. Tool updates AGOL dashboard immediately.
6. Tool syncs records to local/enterprise geodatabase.
7. Tool builds model-ready point layer.
8. Tool runs draft interpolation models.
9. Tool generates contours and uncertainty surface.
10. Tool exports draft PDF map.
11. Tool publishes review layers to AGOL.
12. Hydrogeologist reviews/approves or edits exclusions.
13. Tool regenerates final contours/map.
```

---

# 7. Suggested Survey123 Form Fields for Groundwater Modeling

## Well status section

| Field | Type |
|---|---|
| SiteID | hidden/calculated |
| EventID | select one |
| WellID | select one from feature layer |
| WellStatus | active/damaged/dry/inaccessible |
| MeasurementDateTime | dateTime |
| MeasuredBy | username |
| Photo_WellCondition | image |

## Elevation section

| Field | Type |
|---|---|
| TOC_Elev_ft | read-only pulled from well table |
| DTW_ft | decimal |
| ProductThickness_ft | decimal optional |
| GWE_ft | calculated |
| PriorGWE_ft | read-only |
| GWE_Delta_ft | calculated |
| QA_Flag | calculated |
| UseForModel | yes/no |
| ExclusionReason | select one |

---

# 8. Dashboard Concepts

## 8.1 Field Event Dashboard

Cards:

- Planned wells
- Sampled wells
- Dry wells
- Inaccessible wells
- Missing samples
- Field QA warnings
- Photos submitted
- Percent complete

Maps:

- Wells by status
- Current field crew submissions
- Access issues
- Wells needing resampling

---

## 8.2 Lab Results Dashboard

Cards:

- Lab data received
- Unmatched lab samples
- Exceedance count
- New detections
- Missing analytes
- RPD failures
- Report readiness

Charts:

- Exceedances by analyte
- Detections by site
- Current vs prior event
- QA errors by category

---

## 8.3 Groundwater Model Review Dashboard

Cards:

- Valid model points
- Excluded wells
- Model method
- RMSE
- Max standard error
- Review status

Layers:

- Model input points
- Excluded wells
- GWE contours
- Standard error raster/layer
- Flow arrow
- Model boundary

Reviewer actions:

- Approve model
- Request exclusion
- Add review comment
- Lock contour set

---

## 8.4 Portfolio Dashboard

For many small sites.

Metrics:

- Active sites
- Events due this month
- Events sampled
- Lab results pending
- Figures pending
- Reports pending
- Open QA issues
- Exceedance sites
- Client-ready packages

---

# 9. Database and Report Output Tools

## 9.1 Database Snapshot Exporter

**Tool name:** `ExportEventDatabaseSnapshot`

Creates a frozen database snapshot for a report event.

### Output

```text
H281_2026Q2_ReportSnapshot.gdb
```

### Contents

- Wells
- Samples
- Analytical results
- Water levels
- Callouts
- Contours
- QA
- Exported figures
- Model summary

---

## 9.2 Regulatory Table Generator

**Tool name:** `GenerateRegulatoryTables`

Generates report-ready analytical tables.

### Supports

- Current event only
- Historical by well
- Exceedances highlighted
- Nondetect formatting
- Qualifiers
- RBSL comparison
- Duplicate/RPD section
- Field parameter table
- Water level table

### Outputs

- Excel workbook
- Word-ready tables
- PDF tables
- CSV for audit

---

## 9.3 Client Deliverable API Package

**Tool name:** `BuildClientDeliverablePackage`

Creates a complete structured package.

```text
ClientPackage/
  Figures/
  Tables/
  GIS/
  Dashboards/
  Reports/
  SourceData/
  QA/
  Manifest.json
```

---

## 9.4 Report Readiness Gate

**Tool name:** `EvaluateReportReadiness`

Single pass/fail gate.

### Checks

| Category | Example |
|---|---|
| Field | All required wells sampled or explained |
| Lab | All expected analyses received |
| GIS | All figures exported |
| QA | No blocking errors |
| Model | Hydro review complete |
| Dashboard | AGOL layers refreshed |
| Report | Tables generated |

---

# 10. Advanced AGOL/Survey123 Architecture

Recommended system layout:

```text
Survey123 Field Forms
        ↓
AGOL Hosted Feature Layers
        ↓
Webhook / Power Automate / Make / Custom Endpoint
        ↓
Hybrid Harness Job Router
        ↓
Local or Cloud Processing
        ↓
Authoritative Environmental GDB
        ↓
Dashboard Data Mart
        ↓
Hosted Views / Web Maps / Dashboards
        ↓
Reports / PDFs / Client Packages
```

---

# 11. Additional Tool Ideas by Execution Mode

## Local ArcGIS Pro toolbox tools

| Tool | Purpose |
|---|---|
| BuildGroundwaterSurfaceModel | QA, interpolation, contours, uncertainty |
| BuildAnalyticalConcentrationSurface | Plume/threshold surfaces |
| GenerateRegulatoryTables | Report-ready Excel outputs |
| ExportEventDatabaseSnapshot | Reproducible report snapshot |
| BuildReportFigurePackage | Figures + tables + QA |
| ValidateReportReadiness | Final pass/fail gate |

## Command-line harness tools

| Tool | Purpose |
|---|---|
| RunFieldToGroundwaterModelPipeline | End-to-end event model |
| BatchPublishDashboardDataMarts | Update many dashboards |
| BackupAGOLProjectItems | Nightly backup |
| AuditAGOLItemDependencies | Detect broken web maps/dashboards |
| PromoteAGOLDataBetweenStages | DEV/QA/PROD release control |
| GeneratePortfolioMetrics | Multi-site status table |

## AGOL/cloud-triggered tools

| Tool | Purpose |
|---|---|
| RouteSurvey123Submission | Webhook event processing |
| UpdateSamplingDashboardStatus | Immediate status refresh |
| NotifyCriticalFieldIssue | Email/Teams notification |
| GenerateSurvey123FeatureReport | Field report PDF |
| SyncHostedLayerToAuthoritativeGDB | Cloud-to-local sync |
| PublishReviewLayers | Push draft model outputs to review map |

---

# 12. Most Valuable New Heavy Hitters

| Rank | Tool | Why it matters |
|---:|---|---|
| 1 | RunFieldToGroundwaterModelPipeline | Turns Survey123 water levels into draft GWE contours/model outputs. |
| 2 | BuildDashboardDataMart | Makes dashboards stable and fast. |
| 3 | ReconcileSurvey123AndLabResults | Catches field/lab/GIS mismatches early. |
| 4 | BuildSurvey123XLSFormFromConfig | Standardizes field forms across sites/events. |
| 5 | PublishDashboardFromSpec | Makes dashboards reproducible. |
| 6 | AuditAGOLItemDependencies | Prevents broken web maps/dashboards/forms. |
| 7 | ExportEventDatabaseSnapshot | Makes report outputs reproducible. |
| 8 | EvaluateReportReadiness | Gives PMs a clear go/no-go status. |
| 9 | GenerateRegulatoryTables | Reuses normalized data for report tables. |
| 10 | PromoteAGOLDataBetweenStages | Brings release discipline to AGOL content. |

---

# 13. Groundwater Model Pipeline in Concrete Terms

## Tool chain

```text
CreateSurvey123SamplingEvent
RouteSurvey123Submission
BuildGroundwaterElevationEvent
ValidateGWModelInputs
BuildGroundwaterSurfaceModel
EvaluateGroundwaterSurfaceModels
GenerateDraftGWContours
PublishGWModelReviewDashboard
HydroReviewApproveModel
ExportFinalPotentiometricMap
ArchiveEventDatabaseSnapshot
```

## Core config

```yaml
groundwater_model:
  site_id: H281
  event_id: 2026-Q2
  vertical_datum: NAVD88
  elevation_units: ft
  dtw_reference: TOC
  gwe_formula: TOC_Elev_ft - DTW_ft

  minimum_valid_points: 3
  default_use_for_model: true

  exclusion_rules:
    exclude_statuses: [DRY, NM, NS, NA]
    require_toc_elevation: true
    require_coordinates: true
    max_prior_event_delta_ft_warning: 2.0
    max_prior_event_delta_ft_error: 5.0

  model_candidates:
    - name: TIN
      enabled: true
    - name: IDW
      enabled: true
    - name: EBK
      enabled: true
      transformation_type: NONE
      output_types: [PREDICTION, STANDARD_ERROR]
    - name: EBK_Probability
      enabled: false
      threshold_type: EXCEED
      probability_threshold: 4810.0

  contour:
    interval_ft: 0.5
    clip_to_boundary: true
    smooth_contours: false
    review_status: DRAFT

  outputs:
    publish_to_agol: true
    export_pdf: true
    update_dashboard: true
    create_snapshot_gdb: true
```

---

# 14. Practical Warning on Turnkey Geostatistics

A turnkey groundwater model is realistic for draft production, QA, and repeatable outputs. It is not realistic as a fully autonomous final hydrogeologic interpretation.

Separate outputs by status:

| Output | Status |
|---|---|
| Computed GWE points | Production-ready after QA |
| Draft interpolation raster | Draft |
| Draft contours | Draft |
| Draft flow arrow | Draft |
| Standard error surface | Analytical support |
| Final potentiometric surface map | Only after hydrogeologist/PM review |

---

# 15. Recommended Next Build

Build `RunFieldToGroundwaterModelPipeline` as a staged tool, not one monolithic script.

Start with:

1. `BuildGroundwaterElevationEvent`
2. `ValidateGWModelInputs`
3. `GenerateDraftGWContours`
4. `BuildGroundwaterModelReviewDashboard`

Then add EBK/kriging and uncertainty surfaces once the QA and review process is stable.
