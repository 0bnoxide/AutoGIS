# Boring Log Documentation, GUI, RTK, Drone DEM/Imagery, and Level Loop Automation Ideas

## Executive Summary

This document brainstorms additional automation tools and implementation patterns for a hybrid environmental/CAD/GIS toolset that can run through ArcGIS Pro toolboxes, command-line harnesses, AGOL/cloud workflows, and local desktop GUI applications.

The strongest opportunities are:

1. **Boring log documentation pipeline**: field collection, photo/sample tracking, stratigraphy normalization, boring log PDFs, GIS/Civil 3D outputs, QA, and report appendices.
2. **Boring/well construction data model**: normalized lithology, samples, PID, groundwater observations, well construction, backfill, screen, casing, and abandonment records.
3. **Custom desktop GUI hub**: a simplified operator-facing interface that wraps ArcGIS, Civil 3D, RTK survey, drone, and environmental workflows without forcing staff into raw scripts.
4. **RTK survey QA pipeline**: point import, coordinate system validation, occupation checks, control residuals, duplicate shots, feature coding, and CAD/GIS export.
5. **Drone DEM/orthomosaic processing pipeline**: flight manifest, GCP/CP management, photogrammetry outputs, DEM/DSM QA, volume/surface comparison, and report-ready deliverables.
6. **Level rod loop processing tool**: closure calculation, adjustment, benchmark comparison, water-level measurement integration, survey documentation, and QA reporting.
7. **Cross-domain deliverable generator**: produces GIS layers, Civil 3D support files, figures, tables, QA reports, and archive packages from the same controlled database.

The recommended design is not one large monolithic application. Use a shared Python core with separate interfaces:

- ArcGIS Pro Python toolbox for GIS analysts.
- Command-line harness for repeatable/batch processing.
- AGOL/cloud functions for Survey123 and dashboard workflows.
- Optional desktop GUI for field/data technicians.
- Civil 3D export modules for CAD deliverables.

---

# 1. Boring Log Documentation Workflows

## 1.1 Tool: `CreateBoringLogDatabase`

### Purpose

Create the normalized geodatabase or SQLite/PostgreSQL schema needed to store boring log data, field observations, lab samples, stratigraphy, and well construction details.

### Core tables

#### `BoringLocations`

| Field | Description |
|---|---|
| `ProjectID` | Project identifier |
| `SiteID` | Site identifier |
| `BoringID` | Boring or well ID |
| `LocationType` | Boring, monitoring well, piezometer, test pit, CPT, hand auger |
| `Northing` | Coordinate |
| `Easting` | Coordinate |
| `GroundElevation` | Ground surface elevation |
| `TOC_Elevation` | Top of casing elevation, if converted to well |
| `CoordinateSystem` | Horizontal datum/projection |
| `VerticalDatum` | Vertical datum |
| `DrillingStartDate` | Start date |
| `DrillingEndDate` | End date |
| `Driller` | Drilling subcontractor |
| `LoggedBy` | Field logger/geologist |
| `TotalDepth` | Final boring depth |
| `CompletionType` | Backfilled, monitoring well, abandoned, piezometer |
| `Status` | Proposed, drilled, surveyed, logged, reviewed, finalized |

#### `LithologyIntervals`

| Field | Description |
|---|---|
| `BoringID` | Parent boring |
| `TopDepth` | Top depth |
| `BottomDepth` | Bottom depth |
| `USCS` | Unified Soil Classification System group symbol |
| `PrimaryMaterial` | Sand, clay, silt, gravel, fill, bedrock, etc. |
| `SecondaryMaterial` | Secondary material |
| `Color` | Munsell or plain language color |
| `Moisture` | Dry, moist, wet, saturated |
| `DensityConsistency` | Loose/dense/soft/stiff/etc. |
| `Plasticity` | None/low/medium/high |
| `Odor` | None, petroleum, solvent, sulfur, etc. |
| `Staining` | None/light/moderate/heavy |
| `PID_ppm` | PID reading, where interval-level |
| `Description` | Full lithologic description |
| `GraphicPattern` | Symbol/pattern code |
| `Reviewed` | QA review flag |

#### `Samples`

| Field | Description |
|---|---|
| `SampleID` | Sample identifier |
| `BoringID` | Parent boring |
| `SampleType` | Grab, split spoon, Shelby, rock core, soil analytical, duplicate |
| `TopDepth` | Sample top depth |
| `BottomDepth` | Sample bottom depth |
| `Recovery` | Recovery length or percent |
| `BlowCounts` | SPT blow counts |
| `LabSubmitted` | Yes/no |
| `Matrix` | Soil, groundwater, vapor, sediment |
| `AnalyticalGroup` | VPH, EPH, metals, VOCs, etc. |
| `PhotoID` | Linked photo |
| `COCNumber` | Chain of custody |

#### `WellConstruction`

| Field | Description |
|---|---|
| `BoringID` | Parent boring/well |
| `ComponentType` | Casing, screen, sand pack, bentonite, grout, cap, surface seal |
| `TopDepth` | Component top |
| `BottomDepth` | Component bottom |
| `Diameter` | Diameter |
| `Material` | PVC, stainless, sand, bentonite, grout |
| `SlotSize` | Screen slot size |
| `Notes` | Notes |

#### `GroundwaterObservations`

| Field | Description |
|---|---|
| `BoringID` | Parent boring |
| `ObservationDateTime` | Observation time |
| `DepthToWater` | Depth to water |
| `ObservationType` | During drilling, after drilling, stabilized, not encountered |
| `ReferencePoint` | Ground surface, TOC, casing, etc. |
| `Notes` | Notes |

#### `Photos`

| Field | Description |
|---|---|
| `PhotoID` | Photo identifier |
| `BoringID` | Parent boring |
| `SampleID` | Optional sample link |
| `Depth` | Optional depth |
| `PhotoPath` | Local/AGOL path |
| `Caption` | Caption |
| `TakenBy` | User |
| `DateTime` | Timestamp |

---

## 1.2 Tool: `ImportFieldBoringLogs`

### Purpose

Import boring logs from field spreadsheets, Survey123 forms, tablets, CSVs, or structured JSON into the normalized boring log database.

### Supported sources

- Survey123 drilling/boring forms.
- Excel field logs.
- CSV exports from third-party logging apps.
- gINT-style exports.
- OpenGround-style exports if available.
- Manual entry GUI output.

### QA checks

| Check | Severity |
|---|---|
| Missing boring ID | Error |
| Duplicate boring ID | Error/warning depending on project |
| Interval gaps | Error |
| Interval overlaps | Error |
| Total depth mismatch | Warning/error |
| Sample interval outside boring depth | Error |
| Well screen outside boring depth | Error |
| Missing ground elevation | Warning |
| Missing coordinates | Warning/error depending on use |
| Missing logged-by field | Warning |
| Invalid USCS code | Warning |
| PID reading nonnumeric | Warning |
| Groundwater depth deeper than total depth | Error |
| Well construction component overlap | Warning |

---

## 1.3 Tool: `GenerateBoringLogPDFs`

### Purpose

Generate standardized boring log PDFs from normalized database records.

### Outputs

- One boring log PDF per boring.
- Combined boring log appendix PDF.
- Photo log appendix.
- Sample summary table.
- Well construction diagrams.
- QA report.

### Log sections

- Project/site header.
- Location map inset or coordinate box.
- Drilling method.
- Driller/logger/date.
- Ground elevation and coordinates.
- Lithologic column.
- USCS/pattern column.
- Sample intervals.
- PID readings.
- Groundwater observations.
- Well construction diagram.
- Remarks.
- Review/approval block.

### Implementation approaches

#### Option A: Python report generator

Use Python to create PDFs directly from data using a report layout library. Best for reproducible outputs but requires more layout development.

#### Option B: Word template mail merge style

Generate a DOCX from a template and convert to PDF. Easier for staff to edit templates.

#### Option C: ArcGIS layout-based boring logs

Use ArcGIS Pro layouts and map frames only where the boring log has spatial components. This is less ideal for full boring logs but can work for simple logs.

#### Option D: Dedicated geotechnical software integration

Export normalized data to a format compatible with existing geotechnical tools and use those tools for final logs.

---

## 1.4 Tool: `GenerateSubsurfaceProfileFromBorings`

### Purpose

Create subsurface profile graphics along an alignment from boring/well data.

### Inputs

- Borings/wells feature class.
- Alignment or profile line.
- Lithology intervals.
- Groundwater observations.
- Screen intervals.
- Vertical exaggeration.
- Projection distance tolerance.

### Outputs

- Projected boring sticks.
- Lithology bars.
- Water table markers.
- Screen/casing symbols.
- Profile labels.
- CAD/GIS export.

### Heavy ROI

This bridges boring logs, ArcGIS Pro figures, and Civil 3D/geotechnical profile exhibits.

---

## 1.5 Tool: `BoringLogReviewDashboard`

### Purpose

AGOL dashboard or local dashboard table showing log completion and QA status.

### Dashboard metrics

- Proposed borings.
- Drilled borings.
- Logs received.
- Logs QA passed.
- Missing photos.
- Missing coordinates.
- Missing lab sample links.
- Logs ready for report.
- Open reviewer comments.

---

## 1.6 Tool: `BoringLogCommentResolutionTracker`

### Purpose

Track review comments for boring logs.

### Fields

| Field | Description |
|---|---|
| `CommentID` | Unique comment |
| `BoringID` | Target boring |
| `Reviewer` | Reviewer |
| `CommentText` | Comment |
| `Severity` | Info/warning/error |
| `AssignedTo` | Responsible person |
| `Status` | Open/resolved/deferred |
| `ResolutionNote` | Resolution |
| `ResolvedDate` | Date |

---

# 2. Survey123 Boring Log Workflows

## 2.1 Tool: `BuildSurvey123BoringLogForm`

### Purpose

Generate a Survey123 XLSForm for boring log collection.

### Form sections

1. Project and boring metadata.
2. Drilling method and equipment.
3. Location and elevation.
4. Lithology interval repeat.
5. Soil sample repeat.
6. PID reading repeat.
7. Groundwater observation repeat.
8. Well construction repeat.
9. Photo attachments.
10. Daily drilling notes.
11. QA checklist.

### Useful form calculations

- Interval continuity checks.
- Bottom depth greater than top depth.
- Sample depth within boring total depth.
- Well screen depth within boring depth.
- Auto-generated sample IDs.
- Total boring depth from maximum interval bottom.
- Required photo prompts for selected conditions.

---

## 2.2 Tool: `SyncSurvey123BoringLogs`

### Purpose

Download Survey123 boring log records, repeats, and attachments into the authoritative boring log database.

### Outputs

- Normalized boring data.
- Photo catalog.
- QA report.
- Updated log status dashboard.

---

## 2.3 Tool: `GenerateDailyDrillingReport`

### Purpose

Generate daily drilling reports from Survey123 submissions.

### Content

- Borings advanced.
- Footage drilled.
- Samples collected.
- Problems encountered.
- Water encountered.
- Photos.
- Crew/equipment.
- Weather.
- Safety notes.

---

# 3. GUI Implementations

## 3.1 Recommended GUI architecture

Create a thin GUI shell over the same Python core used by the command harness and ArcGIS Pro toolbox.

```text
GUI / ArcGIS Toolbox / CLI / AGOL Trigger
        ↓
Shared Python Core
        ↓
Project Config + Data Store + QA + Outputs
```

Avoid writing separate logic for GUI and toolbox tools.

---

## 3.2 GUI option comparison

| Framework | Best use | Notes |
|---|---|---|
| PySide6 / PyQt | Full desktop application | Most flexible, strongest option for complex workflows |
| Tkinter | Lightweight internal utilities | Built into Python, less polished |
| Streamlit | Browser-based local dashboard | Good for review/status panels, less ideal inside ArcGIS |
| NiceGUI | Python web GUI | Good for internal local web apps |
| ArcGIS Python Toolbox | GIS analyst workflow | Best inside ArcGIS Pro, limited custom UI |
| Experience Builder / Dashboards | AGOL users | Best for cloud review/status, not heavy processing |

---

## 3.3 GUI: `Project Automation Hub`

### Purpose

A launcher for all major workflows.

### Tabs

1. **Project Setup**
   - Select project folder.
   - Select site config.
   - Validate folder structure.
   - Create geodatabase.
   - Register coordinate system.

2. **Environmental Monitoring**
   - Import workbook.
   - Validate data.
   - Build figures.
   - Export map package.

3. **Boring Logs**
   - Import field logs.
   - Validate intervals.
   - Generate boring logs.
   - Generate profile sticks.

4. **Survey / RTK**
   - Import point CSV.
   - Validate coordinate system.
   - QA control shots.
   - Export GIS/CAD points.

5. **Drone / DEM**
   - Register flight.
   - Import orthomosaic/DSM/DEM.
   - QA GCPs/checkpoints.
   - Compare surfaces.
   - Generate volume report.

6. **AGOL / Dashboard**
   - Publish/update layers.
   - Refresh dashboard data marts.
   - Backup AGOL items.
   - Audit item dependencies.

7. **Reports**
   - Build figure package.
   - Build appendix package.
   - Export QA reports.

8. **Run History**
   - View jobs.
   - Open logs.
   - Re-run failed jobs.
   - Export audit trail.

---

## 3.4 GUI implementation details

### Important features

- Project config selector.
- Drag-and-drop input files.
- Parameter validation before execution.
- Dry-run mode.
- Progress bar.
- Live log window.
- QA results table.
- Open output folder button.
- Open in ArcGIS Pro button.
- Retry failed task.
- Save/load run profiles.
- Export run manifest.

### Job manifest pattern

Every GUI run should create a manifest:

```yaml
run_id: 20260625_153011
workflow: boring_log_pdf_generation
project_id: ExampleProject
site_id: ExampleSite
inputs:
  source_database: C:/Projects/Example/site.gdb
  boring_ids: [B-01, B-02, B-03]
outputs:
  pdf_folder: C:/Projects/Example/Reports/BoringLogs
settings:
  validate_only: false
  overwrite_existing: true
```

---

# 4. RTK Survey Workflows

## 4.1 Tool: `ImportRTKSurveyPoints`

### Purpose

Import RTK survey points from CSV, TXT, shapefile, GeoPackage, or collector export into a standardized survey feature class.

### Input fields

- Point ID.
- Northing/easting or latitude/longitude.
- Elevation.
- Feature code.
- Description.
- HRMS/VRMS or horizontal/vertical precision.
- Fix type.
- Correction source.
- Occupation time.
- Rod height.
- Date/time.
- Operator.

### Output feature class

`SurveyPoints_Raw` and `SurveyPoints_QA`

---

## 4.2 Tool: `ValidateRTKSurvey`

### QA checks

| Check | Severity |
|---|---|
| Duplicate point IDs | Error/warning |
| Missing elevation | Warning/error |
| HRMS/VRMS above tolerance | Warning/error |
| Float/fixed status not acceptable | Error |
| Point outside site boundary | Warning |
| Coordinate system mismatch | Error |
| Elevation datum mismatch | Error |
| Control point residual above tolerance | Error |
| Repeat shot difference above tolerance | Warning/error |
| Feature code unknown | Warning |
| Rod height missing | Warning |
| Time gap or suspicious sequence | Info/warning |

---

## 4.3 Tool: `RTKControlCheckReport`

### Purpose

Compare observed RTK control shots to published/project control values.

### Outputs

- Control residual table.
- Pass/fail summary.
- Control point map.
- Survey QA PDF.

### Metrics

- Horizontal residual.
- Vertical residual.
- Northing/easting residuals.
- Elevation residual.
- RMS error.
- Max residual.
- Pass/fail by tolerance.

---

## 4.4 Tool: `FeatureCodeTranslator`

### Purpose

Translate RTK feature codes into GIS layers, symbols, and CAD layers.

### Example config

```yaml
feature_codes:
  MW:
    target_layer: MonitoringWells
    symbol: monitoring_well
    cad_layer: C-WELL-MONI
  GCP:
    target_layer: DroneControlPoints
    symbol: control_point
    cad_layer: V-SURV-GCP
  EP:
    target_layer: EdgeOfPavement
    geometry: polyline
    cad_layer: C-ROAD-EDGE
```

---

## 4.5 Tool: `ExportSurveyToCADGIS`

### Outputs

- GIS point/line/polygon layers.
- Civil 3D point CSV.
- LandXML if needed.
- DWG/DXF export.
- Layer mapping report.
- QA report.

---

# 5. Level Rod Loop Workflows

## 5.1 Tool: `ProcessLevelLoop`

### Purpose

Process differential level notes and calculate adjusted elevations.

### Input methods

- CSV from digital level.
- Manual field-book entry.
- Survey123 form.
- Excel level notes.

### Input fields

- Setup ID.
- Point ID.
- Backsight.
- Intermediate sight.
- Foresight.
- Turning point.
- Benchmark ID.
- Known benchmark elevation.
- Rod reading units.
- Notes.

---

## 5.2 Calculations

### Standard level loop logic

- Height of instrument.
- Elevation per point.
- Total backsight.
- Total foresight.
- Misclosure.
- Loop length or number of setups.
- Allowable closure tolerance.
- Adjustment per setup or per distance.
- Adjusted elevations.

### QA flags

| Check | Flag |
|---|---|
| Misclosure exceeds tolerance | Error |
| Missing backsight/foresight | Error |
| Negative or impossible reading | Error |
| Duplicate turning point issue | Warning |
| Benchmark mismatch | Error |
| Excessive sight length imbalance | Warning |
| Unclosed loop | Warning/error |

---

## 5.3 Tool: `LevelLoopAdjustmentReport`

### Outputs

- Raw level notes table.
- Adjustment table.
- Adjusted benchmark/well elevations.
- Closure summary.
- QA report.
- PDF survey memo.
- GIS/CAD updated elevation table.

---

## 5.4 Tool: `UpdateWellElevationsFromLevelLoop`

### Purpose

Push adjusted TOC/ground elevations into the monitoring well database.

### Safeguards

- Create elevation history records instead of overwriting silently.
- Require approval flag for replacing active elevations.
- Track survey method and source loop.
- Preserve prior elevations.

### Elevation history table

| Field | Description |
|---|---|
| `LocationID` | Well/point |
| `ElevationType` | TOC, ground, casing mark, benchmark |
| `Elevation` | Elevation |
| `VerticalDatum` | Datum |
| `SurveyDate` | Date |
| `SurveyMethod` | RTK, level loop, total station |
| `SourceRunID` | Source processing run |
| `ApprovedForUse` | Yes/no |
| `Superseded` | Yes/no |

---

# 6. Drone DEM / Drone Imagery Workflows

## 6.1 Tool: `RegisterDroneFlight`

### Purpose

Create a formal record for each drone flight and photogrammetry deliverable.

### Fields

| Field | Description |
|---|---|
| `FlightID` | Unique flight ID |
| `ProjectID` | Project |
| `SiteID` | Site |
| `FlightDate` | Date |
| `Pilot` | Pilot |
| `DroneModel` | Aircraft |
| `Sensor` | Camera/sensor |
| `FlightAltitude` | Altitude |
| `OverlapForward` | Forward overlap |
| `OverlapSide` | Side overlap |
| `GCPUsed` | Yes/no |
| `CheckpointCount` | Count |
| `ProcessingSoftware` | Software |
| `OutputCRS` | Horizontal CRS |
| `VerticalDatum` | Vertical datum |
| `OrthomosaicPath` | Output path |
| `DSMPath` | Output path |
| `DEMPath` | Output path |
| `PointCloudPath` | Output path |
| `QAStatus` | Status |

---

## 6.2 Tool: `ImportDroneProducts`

### Inputs

- Orthomosaic.
- DSM.
- DEM/DTM.
- Point cloud.
- GCP/checkpoint CSV.
- Processing quality report.
- Boundary polygon.

### Outputs

- Raster catalog or mosaic dataset.
- Site orthomosaic layer.
- DEM/DSM layers.
- GCP/checkpoint feature classes.
- QA report.

---

## 6.3 Tool: `DroneGCPCheckpointQA`

### Purpose

Evaluate photogrammetry accuracy using checkpoints.

### Checks

- GCPs used vs checkpoints held out.
- Horizontal residuals.
- Vertical residuals.
- RMSE horizontal.
- RMSE vertical.
- Max residual.
- Checkpoints outside tolerance.
- Coordinate system mismatch.
- Units mismatch.
- Vertical datum mismatch.

### Outputs

- Residual table.
- Residual map.
- Accuracy report.
- Pass/fail QA status.

---

## 6.4 Tool: `DEMConditioningPipeline`

### Purpose

Prepare drone DEM/DSM outputs for analysis.

### Steps

1. Clip to project boundary.
2. Reproject if necessary.
3. Set vertical units.
4. Fill small voids if configured.
5. Smooth or filter only if configured.
6. Derive hillshade.
7. Derive slope.
8. Derive contours.
9. Generate QA rasters.
10. Register processed outputs.

### Outputs

- Clean DEM.
- Hillshade.
- Slope raster.
- Contours.
- Metadata JSON.
- QA report.

---

## 6.5 Tool: `CompareDroneSurfaces`

### Purpose

Compare surfaces between drone flights or against design surfaces.

### Use cases

- Landfill volume change.
- Stockpile volume.
- Cut/fill tracking.
- Surface settlement.
- Erosion/deposition.
- Construction progress.
- Mine/reclamation monitoring.

### Inputs

- Baseline DEM.
- Current DEM.
- Boundary polygons.
- No-data masks.
- Minimum level of detection threshold.

### Outputs

- Difference of DEM raster.
- Cut/fill polygons.
- Volume table.
- Thickness/change map.
- QA report.

---

## 6.6 Tool: `CalculateStockpileVolumes`

### Inputs

- DSM/point cloud-derived surface.
- Base surface or polygon boundary.
- Stockpile polygons.
- Material density table, optional.

### Outputs

- Volume per stockpile.
- Tonnage estimate if density provided.
- Stockpile map.
- Excel report.
- CAD/GIS export.

---

## 6.7 Tool: `GenerateDroneImageryMapPackage`

### Outputs

- Orthomosaic map PDF.
- Site feature overlay map.
- Contours/hillshade map.
- Change detection map.
- QA report.
- Web map/AGOL tile layer if configured.

---

## 6.8 Tool: `PublishDroneProductsToAGOL`

### Purpose

Publish processed drone products to AGOL or an enterprise portal.

### Products

- Tile layer for orthomosaic.
- Feature layer for GCPs/checkpoints.
- Feature layer for contours.
- Feature layer for volume polygons.
- Dashboard data tables.

---

# 7. Combined Survey + Drone + Boring + Environmental Pipelines

## 7.1 Pipeline: `FieldDataToReportPackage`

### Purpose

Automate end-to-end field-to-report outputs.

```text
Survey123 / RTK / Drone / Lab Data
        ↓
QA + Normalization
        ↓
Authoritative Geodatabase
        ↓
GIS/CAD/Report Outputs
        ↓
AGOL Dashboard + Archive Package
```

### Outputs

- Boring logs.
- Monitoring well maps.
- Groundwater elevation maps.
- Analytical result maps.
- Drone imagery figures.
- DEM/volume figures.
- Survey QA report.
- Data manifest.
- Report appendix package.

---

## 7.2 Pipeline: `BoringToCivil3DGeotechModel`

### Purpose

Convert boring logs and stratigraphy into Civil 3D/Geotechnical Modeler-ready data.

### Outputs

- CSV formatted for geotechnical import.
- Boring location points.
- Stratum interval table.
- Groundwater interval table.
- Surface support points.
- QA report.

### Extra value

This creates a bridge between field boring logs and Civil 3D subsurface modeling.

---

## 7.3 Pipeline: `DroneToCivil3DSurfacePackage`

### Purpose

Convert drone DEM/DSM/point cloud products into Civil 3D-ready surface deliverables.

### Outputs

- Contour DWG/DXF.
- Point CSV.
- LandXML surface, if generated.
- Clipped DEM.
- Civil 3D layer mapping report.
- QA report.

---

## 7.4 Pipeline: `SurveyToWellElevationUpdate`

### Purpose

Combine RTK and/or level-loop data to update monitoring well elevations.

### Steps

1. Import RTK or level-loop data.
2. Validate control/closure.
3. Calculate adjusted elevations.
4. Compare against previous well elevations.
5. Flag significant changes.
6. Update elevation history table.
7. Set approved elevations after review.
8. Recalculate groundwater elevations for selected events.

---

# 8. Additional GUI Ideas

## 8.1 Boring Log Editor GUI

### Features

- Select boring from map/list.
- Edit lithology intervals in a grid.
- Validate interval gaps/overlaps live.
- Preview boring log PDF.
- Attach photos.
- Review well construction diagram.
- Mark log as reviewed.
- Export final log.

---

## 8.2 RTK Survey QA GUI

### Features

- Drag/drop point CSV.
- Preview points on map.
- Select coordinate system.
- Run control check.
- View failed points.
- Approve/reject survey import.
- Export CAD/GIS deliverables.

---

## 8.3 Drone Deliverable Manager GUI

### Features

- Register flight.
- Attach processing report.
- Import orthomosaic/DEM/DSM.
- Run checkpoint QA.
- Compare surfaces.
- Generate volume maps.
- Publish imagery to AGOL.

---

## 8.4 Level Loop Processor GUI

### Features

- Enter or import level notes.
- Calculate closure live.
- Apply adjustment method.
- Generate elevation table.
- Update well elevations after approval.
- Export survey memo.

---

# 9. Recommended Priority Order

## Immediate ROI

1. `ProcessLevelLoop`
2. `ValidateRTKSurvey`
3. `DroneGCPCheckpointQA`
4. `ImportFieldBoringLogs`
5. `GenerateBoringLogPDFs`
6. `UpdateWellElevationsFromLevelLoop`
7. `RegisterDroneFlight`
8. `Project Automation Hub` GUI skeleton

## Medium-term ROI

9. `GenerateSubsurfaceProfileFromBorings`
10. `DEMConditioningPipeline`
11. `CompareDroneSurfaces`
12. `CalculateStockpileVolumes`
13. `BuildSurvey123BoringLogForm`
14. `BoringToCivil3DGeotechModel`
15. `SurveyToWellElevationUpdate`

## Advanced/high-value

16. `DroneToCivil3DSurfacePackage`
17. `FieldDataToReportPackage`
18. `BoringLogEditorGUI`
19. `DroneDeliverableManagerGUI`
20. `PublishDroneProductsToAGOL`

---

# 10. Suggested Unified Data Architecture

## Core project database

```text
Project.gdb
  Sites
  ProjectBoundaries
  MonitoringWells
  SoilBorings
  BoringLocations
  LithologyIntervals
  Samples
  WellConstruction
  GroundwaterObservations
  SurveyPoints_Raw
  SurveyPoints_QA
  LevelLoopRuns
  LevelLoopObservations
  ElevationHistory
  DroneFlights
  DroneControlPoints
  DroneCheckpoints
  DroneProductRegistry
  DEMDifferenceResults
  StockpileVolumes
  QARecords
  RunHistory
```

---

# 11. Recommended Design Principle

All these tools should write to the same core tables:

- `RunHistory`
- `QARecords`
- `DocumentRegistry`
- `ElevationHistory`
- `ProjectConfig`
- `SourceDataManifest`

That makes the entire system auditable and reproducible.

---

# 12. Practical Next Build

The best next build is probably:

## `SurveyToWellElevationUpdate`

Why:

- It connects RTK, level loops, groundwater elevation calculations, monitoring well data, and groundwater mapping.
- It directly supports your environmental monitoring pipeline.
- It creates a foundation for defensible groundwater elevation maps and potentiometric surfaces.
- It has clear QA rules.
- It produces immediate deliverables.

Minimum viable workflow:

1. Import RTK or level-loop data.
2. Validate survey quality.
3. Update elevation history table.
4. Recalculate groundwater elevations.
5. Flag differences from prior elevations.
6. Export a QA memo.
7. Update GIS labels/maps.
