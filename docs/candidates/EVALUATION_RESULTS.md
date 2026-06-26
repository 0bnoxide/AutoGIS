# Candidate Roadmap Evaluation Results

**Evaluation date:** 2026-06-25  
**Framework:** Hybrid harness architecture (local ArcGIS Pro + CLI harness + AGOL/cloud webhooks + shared infrastructure)

---

## Executive Summary

**Strong fit (9 tools):** All three modes + shared infrastructure leverage
**Conditional fit (12 tools):** Two or three modes, some schema/infrastructure extension needed
**Weaker fit (7 tools):** Specialized to one mode or requires external dependencies

**Recommendation:** Fast-track 9 strong-fit tools into main roadmap. Conditional tools require architecture review before integration.

---

# Survey123, AGOL, Dashboard, Geostatistical Roadmap Evaluation

## Strong Fit (All Three Modes + Shared Infrastructure)

### 1. ✅ `ReconcileSurvey123AndLabResults`
**Modes:** Local ✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (normalizes data, writes QA records, uses analyte dictionary)

- Compares field samples, lab results, GIS well IDs
- Runs as local QA step, CLI batch validation, or webhook trigger
- Produces QA records via shared framework
- **Integration path:** Extend existing ImportQA logic, no new schema needed
- **Priority:** High — directly supports existing envmon workflows

---

### 2. ✅ `BuildDashboardDataMart`
**Modes:** Local ✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (reads normalized tables, produces flat views)

- Flattens raw analytical tables into dashboard-ready structures
- Local: runs in ArcGIS toolbox; CLI: batch builds many sites; AGOL: scheduled refresh via webhook
- Reuses ValidateAndConvertUnits, analyte screening, QA framework
- **Integration path:** Build on top of current normalized schema (Env_Samples, Env_AnalyticalResults)
- **Priority:** High — solves dashboard performance/schema isolation problem

---

### 3. ✅ `RouteSurvey123Submission`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓✓  
**Shared infrastructure:** ✓ (webhook architecture, shared QA, GWE calculations)

- Webhook triggered on Survey123 submit → validates → updates AGOL → writes to local GDB
- Perfect fit for hybrid harness job router pattern
- Leverages shared config for well status, QA thresholds, notification rules
- **Integration path:** Implement as CLI tool that job router can call; design webhook endpoint
- **Priority:** High — core field-to-database pipeline

---

### 4. ✅ `BuildSurvey123XLSFormFromConfig`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (reads site config, well network, analyte groups)

- Generates XLSForm from project config + well network + required analytes
- Local: one-time form generation in toolbox; CLI: batch across sites
- Reuses existing config layer (sites, screening levels, analyte dictionary)
- **Integration path:** Pure config-to-form compiler, minimal new schema
- **Priority:** High — removes manual form maintenance burden

---

### 5. ✅ `ExportEventDatabaseSnapshot`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (freezes normalized schema, audit trail via run history)

- Creates reproducible GDB snapshot for report events
- Local: toolbox output; CLI: batch snapshots for archives
- Captures complete event state (samples, results, water levels, QA, figures)
- **Integration path:** Leverage existing normalized tables + RunHistory table
- **Priority:** Medium — supports reproducible reports

---

### 6. ✅ `EvaluateReportReadiness`
**Modes:** Local ✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (audits QA records, schema completeness, report status)

- Single pass/fail gate: field complete? lab received? GIS exported? QA passing?
- Local: final check before toolbox export; CLI: batch readiness for many events; AGOL: dashboard status card
- Reads from QA framework, run history, figure registry
- **Integration path:** Audit existing QA record structure + document readiness rules
- **Priority:** High — PM visibility into event status

---

### 7. ✅ `PublishDashboardFromSpec`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓✓  
**Shared infrastructure:** ✓ (config-driven dashboard creation, reproducible)

- YAML/JSON → AGOL dashboard creation (items, cards, charts, filters)
- CLI: batch dashboard updates; AGOL: refresh via scheduled job
- Reuses site config, data mart tables, screening levels
- **Integration path:** Design dashboard spec schema, integrate with AGOL API
- **Priority:** Medium-high — makes dashboards reproducible, not manual clicking

---

### 8. ✅ `AuditAGOLItemDependencies`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (inventory via RunHistory, integrity checks)

- Detects broken dependencies: dashboard → deleted view, form → old layer, map → renamed item
- Local: check before export; CLI: nightly audit job; reports via email
- Uses item registry (can be extended from RunHistory/DocumentRegistry)
- **Integration path:** Query AGOL API, build inventory, flag mismatches
- **Priority:** Medium — prevents stale/broken AGOL workflows

---

### 9. ✅ `PromoteAGOLDataBetweenStages`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (release control pattern, audit trail)

- DEV → QA → PROD release pipeline for hosted layers
- CLI: promote after validation; AGOL: reviewer approval workflow
- Leverages run history, approval flags, schema validation
- **Integration path:** Extend RunHistory with promotion/approval state
- **Priority:** Medium — introduces release discipline to AGOL content

---

## Conditional Fit (Needs Architecture Review or Schema Extension)

### 10. ⚠️ `RunFieldToGroundwaterModelPipeline`
**Modes:** Local ✓ | CLI ✓✓ | AGOL ✓  
**Shared infrastructure:** ~ (needs GWE calculation standardization, model QA framework)

- End-to-end: Survey123 → GWE validation → interpolation models → contours → AGOL/PDF
- Strongest local tool (kriging, raster ops); cleanest CLI flow; webhook-friendly status updates
- **Blockers:**
  - Requires `ValidateGWModelInputs` tool (not yet in roadmap)
  - Needs standardized model QA metrics table structure
  - Kriging dependencies (scipy, arcpy spatial analyst)
- **Integration path:** Stage 1 (BuildGroundwaterElevationEvent + TIN) before full EBK; define model_qa schema
- **Priority:** High — but stage implementation; start with deterministic models (TIN/IDW) before kriging

---

### 11. ⚠️ `BuildGroundwaterSurfaceModel`
**Modes:** Local ✓✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ~ (needs elevation validation + model parameterization)

- Heavy lifting: TIN/IDW/EBK/kriging, cross-validation, uncertainty surfaces
- **Blockers:**
  - Requires working elevation data + well coordinate validation
  - Model ranking logic needs hydrogeologist input (not fully automatable)
  - Uncertainty surface output depends on model type (TIN has none, EBK has standard error)
- **Integration path:** Start with TIN (requires only points + boundary); add IDW next; defer kriging
- **Priority:** High — but as staged tool, not monolithic; document output status (draft vs. review-ready)

---

### 12. ⚠️ `GenerateRegulatoryTables`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (reuses normalized results + screening levels)

- Excel report: current event, historical by well, exceedances, nondetect formatting, RPD
- **Blockers:**
  - Nondetect handling requires user-selected rule (half-RL, use-RL, exclude) per event
  - Word/PDF output needs template system (design choice: Python library vs. Word template)
- **Integration path:** Reuse AnalyticalResults table, screening-level config, output template system
- **Priority:** Medium-high — straightforward if nondetect rules are pre-configured

---

### 13. ⚠️ `EvaluateGroundwaterSurfaceModels`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (needs model output registry schema)

- Cross-validation: RMSE, mean error, standardized residuals, percent within tolerance
- **Blockers:**
  - Needs `Model_TIN`, `Model_IDW`, `Model_EBK_*` output rasters registered
  - Ranking logic is partly subjective (hydrogeologist review flag)
  - Comparison table structure not yet designed
- **Integration path:** Define model output naming convention + comparison table schema; update after RunGroundwaterModelPipeline implemented
- **Priority:** Medium — depends on BuildGroundwaterSurfaceModel

---

### 14. ⚠️ `CreateSurvey123SamplingEvent`
**Modes:** Local ✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (reads well network, analyte groups, event config)

- Pre-field: well list → expected sample list → field crew assignment → COC draft
- **Blockers:**
  - Requires well network + event config (sites, monitoring frequency, analyte groups)
  - Output depends on access constraints, preservation rules (not yet in schema)
- **Integration path:** Extend site config with event metadata (analyte groups, field measurements); define COC template
- **Priority:** Medium — supports field workflow but not blocking

---

### 15. ⚠️ `BuildAnalyticalConcentrationSurface`
**Modes:** Local ✓✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ~ (needs nondetect rules + plume boundary logic)

- Plume mapping: concentration raster + exceedance probability + contour + uncertainty surface
- **Blockers:**
  - Nondetect handling rule (exclude, half-RL, use-RL, censored model)
  - Requires site-specific plume boundary or buffer
  - Threshold interpolation (exceed/non-exceed) less tested than continuous kriging
- **Integration path:** Reuse geostatistical framework from BuildGroundwaterSurfaceModel; define nondetect config per analyte
- **Priority:** Medium-high — powerful but needs clear nondetect & boundary rules

---

### 16. ⚠️ `CreateHostedViewsForStakeholders`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (row/field filtering, item registry)

- Five stakeholder views: QA (all fields), Client (approved), Crew (current event), Public (no analytical), Regulatory (exceedance)
- **Blockers:**
  - Requires approval workflow (which fields are "approved for client"?)
  - Sharing groups need to be defined per stakeholder
- **Integration path:** Document approval matrix + sharing group structure; implement view filtering
- **Priority:** Medium — adds governance but not blocking

---

### 17. ⚠️ `BackupAGOLProjectItems`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (run history, item registry)

- Backs up layers, views, maps, dashboards, forms, reports, JSON, thumbnails, sharing, dependencies
- **Blockers:**
  - Storage: where do backups live? (local folder, cloud storage, versioned repo?)
  - Restore logic: how to re-publish from backup? (idempotent?)
- **Integration path:** Define backup schedule + storage + restore SOP
- **Priority:** Low-medium — operational tool, not blocking feature development

---

### 18. ⚠️ `BuildClientDeliverablePackage`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (assembles figures, tables, GIS, QA, reports)

- Structured folder: Figures/, Tables/, GIS/, Dashboards/, Reports/, SourceData/, QA/, Manifest.json
- **Blockers:**
  - Requires all upstream tools working (tables, figures, GIS exports, reports)
  - Manifest structure not yet designed
- **Integration path:** Define folder structure + manifest schema; depends on ExportEventDatabaseSnapshot, GenerateRegulatoryTables, etc.
- **Priority:** Low-medium — assembly/packaging tool, useful after other tools work

---

### 19. ⚠️ `GenerateWellInspectionReports`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (needs report template system)

- PDF: one per well + site summary + photo appendix + maintenance table
- **Blockers:**
  - Report template system (Python library vs. Word merge)
  - Photo attachment workflow
- **Integration path:** Design template format, integrate photo registry
- **Priority:** Low-medium — nice-to-have for field teams

---

## Weaker Fit (Specialized to One Mode or External Dependencies)

### 20. ❌ `GenerateDailyDrillingReport`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ~ (reads Survey123 submissions)

- **Issue:** Specialized to Survey123 field workflow, limited reuse in other modes
- **Recommendation:** Keep as separate-repo candidate (field-specific operations)

---

### 21. ❌ `GeneratePortfolioMetrics`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (portfolio-level aggregation, not event-level)

- **Issue:** Aggregate multi-site metrics (active sites, events pending, lab pending, figures pending)
- **Not blocking:** Useful but can be built later once site portfolio is stable
- **Recommendation:** Defer to Phase 2

---

---

# Boring, Survey, Drone, Level Automation Roadmap Evaluation

## Strong Fit (All Three Modes + Shared Infrastructure)

### 1. ✅ `ProcessLevelLoop`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (elevation history table, QA reporting)

- Level loop closure: compute adjusted elevations, flag misclosure, produce QA memo
- Local: one-time survey; CLI: batch level runs; outputs elevation history table
- **Integration path:** Define level_loop + elevation_history tables; integrate with existing well elevation update workflow
- **Priority:** High — foundation for defensible well elevations

---

### 2. ✅ `UpdateWellElevationsFromLevelLoop`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (elevation history with approval/supersede flags)

- Push adjusted elevations into well database with audit trail (approval, source loop, prior value)
- **Integration path:** Extend existing well feature class + elevation history table
- **Priority:** High — critical for GWE map accuracy

---

### 3. ✅ `ValidateRTKSurvey`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (QA framework, coordinate system validation)

- RTK QA: duplicate IDs, missing elevation, precision tolerance, control residuals, datum mismatches
- Local: validate before import; CLI: batch survey QA across projects
- Reuses QA record pattern
- **Integration path:** Extend QA framework for survey points; define tolerance config
- **Priority:** High — prevents bad survey data from corrupting GWE maps

---

### 4. ✅ `ImportRTKSurveyPoints`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (normalizes CSV/shapefile into SurveyPoints_Raw)

- CSV/TXT/shapefile → SurveyPoints_Raw feature class (ID, coordinates, elevation, code, precision)
- **Integration path:** Add SurveyPoints_Raw + SurveyPoints_QA to project schema
- **Priority:** High — standard survey data import

---

### 5. ✅ `ImportFieldBoringLogs`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (normalizes Survey123/Excel/CSV into boring schema)

- Field boring forms → normalized BoringLocations + LithologyIntervals + Samples + WellConstruction tables
- QA: depth gaps, overlaps, sample depths valid, construction overlaps
- **Integration path:** Add boring schema tables (7 tables: BoringLocations, Lithology, Samples, WellConstruction, GroundwaterObservations, Photos, CommentTracker)
- **Priority:** High — enables boring-to-GWE workflows

---

### 6. ✅ `GenerateBoringLogPDFs`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (reads boring database, uses report framework)

- One PDF per boring + combined appendix + photo log + sample table + well construction diagram + QA
- Local: generate from toolbox; CLI: batch all borings for report
- **Integration path:** Choose PDF generation approach (Python library, Word template, or ArcGIS layouts); reuse boring schema
- **Priority:** High — deliverable for field work

---

### 7. ✅ `RegisterDroneFlight`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (flight inventory table, run history integration)

- Create flight record: pilot, aircraft, altitude, overlap, GCP count, processing software, outputs (orthomosaic, DSM, DEM, point cloud)
- Local: toolbox form; CLI: batch flight registry from metadata
- **Integration path:** Add DroneFlights table to project schema
- **Priority:** High — prerequisite for all drone workflows

---

### 8. ✅ `DroneGCPCheckpointQA`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (QA framework, accuracy report)

- Evaluate photogrammetry: GCP residuals, checkpoint residuals, RMSE, pass/fail by tolerance
- Local: QA before import; CLI: batch accuracy check
- **Integration path:** Define checkpoint accuracy table, integrate with QA framework
- **Priority:** High — validates drone products before use

---

### 9. ✅ `ImportDroneProducts`
**Modes:** Local ✓ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (raster registry, orthomosaic/DEM/DSM in project)

- Orthomosaic, DSM, DEM, point cloud → mosaic dataset or raster catalog + GCP/checkpoint feature class
- Local: import into GDB; CLI: batch product ingest; AGOL: publish tile layer
- **Integration path:** Add drone products to raster catalog; define registration schema
- **Priority:** High — standard drone data import

---

## Conditional Fit (Needs Architecture Review or Schema Extension)

### 10. ⚠️ `DEMConditioningPipeline`
**Modes:** Local ✓✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (raster ops, hillshade/slope/contour generation)

- Clip, reproject, fill voids, smooth, derive hillshade/slope/contours, QA rasters
- **Blockers:**
  - Void-filling and smoothing are optional (configure or skip?)
  - Output products depend on use case (hillshade for visualization, slope for stability)
- **Integration path:** Define DEM processing config (clip boundary, void-fill method, smoothing tolerance)
- **Priority:** High — needed before DEM use in analysis

---

### 11. ⚠️ `CompareDroneSurfaces`
**Modes:** Local ✓✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (raster diff, volume calculation, change output)

- Baseline DEM vs. current DEM → difference raster + cut/fill polygons + volume table + thickness map
- **Blockers:**
  - Level-of-detection threshold (minimum detectable change) must be configured
  - Coordinate system/vertical datum alignment critical
- **Integration path:** Define change detection config + volume output table
- **Priority:** Medium-high — enables landfill/stockpile/erosion monitoring

---

### 12. ⚠️ `GenerateSubsurfaceProfileFromBorings`
**Modes:** Local ✓✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (reads boring lithology, water level, construction)

- Alignment-based profile: boring sticks, lithology bars, water table, screen symbols, CAD/GIS export
- **Blockers:**
  - Requires projection distance tolerance + vertical exaggeration (user choice)
  - Graphics output depends on design (matplotlib, ArcGIS layout, Civil 3D)
- **Integration path:** Design profile graphics format, integrate with boring schema + CAD export
- **Priority:** High — bridges boring logs to geotechnical/civil engineering reports

---

### 13. ⚠️ `CalculateStockpileVolumes`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (reads DEM/point cloud, stockpile polygons)

- DSM surface → volume per stockpile, tonnage estimate if density provided
- **Blockers:**
  - Base surface definition (flat plane, reference DEM, design surface)
  - Material density table (not yet in schema)
- **Integration path:** Define stockpile volume output table, material density config
- **Priority:** Medium — specialized for landfill/mining, not core environmental monitoring

---

### 14. ⚠️ `SurveyToWellElevationUpdate`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (integrates RTK + level loop + GWE recalculation)

- RTK or level loop → adjusted elevations → update elevation history → recalculate GWE → flag changes → update labels
- **Blockers:**
  - Requires both ProcessLevelLoop AND ValidateRTKSurvey working first
  - GWE recalculation triggers event-level analysis (potential update cascade)
- **Integration path:** Implement ProcessLevelLoop + ValidateRTKSurvey first; then wire integration
- **Priority:** High — but staged (depends on 2 other tools)

---

### 15. ⚠️ `RTKControlCheckReport`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (control point comparison, residual reporting)

- Compare RTK control shots to published benchmarks → residuals, RMSE, pass/fail
- **Blockers:**
  - Published control point database location/format (local file, AGOL, surveyor API?)
  - Residual tolerance configuration per control point
- **Integration path:** Define control point registry + tolerance config
- **Priority:** Medium — QA for high-accuracy surveys

---

### 16. ⚠️ `ExportSurveyToCADGIS`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (feature code translator, CAD layer mapping)

- Survey points → GIS layers + Civil 3D point CSV + DWG/DXF export
- **Blockers:**
  - Feature code → layer/symbol mapping (config-driven)
  - DWG export format (requires Civil 3D or external library)
- **Integration path:** Define feature code config (MW → MonitoringWells, GCP → DroneControlPoints, etc.)
- **Priority:** Medium — enables CAD/Civil 3D integration

---

### 17. ⚠️ `BoringToCivil3DGeotechModel`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (boring schema → geotechnical format)

- BoringLocations + LithologyIntervals + GroundwaterObservations → CSV for geotechnical software import
- **Blockers:**
  - Geotechnical software format varies (gINT, OpenGround, Civil 3D Geotech Modeler)
  - USCS code mapping to software-specific stratigraphic codes
- **Integration path:** Define export format per target software, test with real boring data
- **Priority:** Medium — specialized for civil/geotechnical teams

---

### 18. ⚠️ `DroneToCivil3DSurfacePackage`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (drone DEM/DSM → CAD surface format)

- DEM/DSM + contours + point cloud → DWG/DXF contours + point CSV + LandXML surface
- **Blockers:**
  - LandXML generation (specialized library or manual export)
  - Contour smoothing for CAD (ArcGIS contours vs. CAD-native smoothing)
- **Integration path:** Design contour/point export, test LandXML generation
- **Priority:** Medium — specialized for civil engineering deliverables

---

## Weaker Fit (Specialized to One Mode or External Dependencies)

### 19. ❌ `BuildSurvey123BoringLogForm`
**Modes:** Local ✓ | CLI ✗ | AGOL ✓  
**Shared infrastructure:** ~ (generates XLSForm from boring config)

- **Issue:** One-time form generation; limited CLI/batch value
- **Recommendation:** Keep as separate-repo candidate; can be added later if Survey123 boring integration prioritized

---

### 20. ❌ `SyncSurvey123BoringLogs`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ✓ (normalizes Survey123 into boring schema)

- **Issue:** Specialized to Survey123 integration; depends on BuildSurvey123BoringLogForm
- **Recommendation:** Defer until Survey123 boring workflow is priority

---

### 21. ❌ `GenerateDailyDrillingReport`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ~ (reads Survey123 submissions)

- **Issue:** Specialized to field crew operations, limited reuse
- **Recommendation:** Keep as separate-repo candidate

---

### 22. ❌ `BoringLogReviewDashboard`
**Modes:** Local ✗ | CLI ✗ | AGOL ✓  
**Shared infrastructure:** ~ (AGOL dashboard only)

- **Issue:** AGOL-only tool; better as part of PublishDashboardFromSpec pattern
- **Recommendation:** Integrate boring dashboard into general dashboard config approach

---

### 23. ❌ `BoringLogCommentResolutionTracker`
**Modes:** Local ✗ | CLI ✗ | AGOL ✓  
**Shared infrastructure:** ~ (AGOL table only)

- **Issue:** Specialized workflow, not core to environmental monitoring
- **Recommendation:** Keep as separate-repo candidate

---

### 24. ❌ `Project Automation Hub` (GUI)
**Modes:** Local ✓ | CLI ✗ | AGOL ✗  
**Shared infrastructure:** ✓ (wraps all tools)

- **Issue:** Desktop GUI application; requires PySide6/PyQt investment; not production-critical
- **Recommendation:** Defer to Phase 2 after core tools are stable; then build GUI wrapper

---

### 25. ❌ `GenerateDroneImageryMapPackage`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ~ (map figure generation)

- **Issue:** Figure/report output; can be built as ExportEventDatabaseSnapshot enhancement
- **Recommendation:** Defer; build as map export feature, not standalone tool

---

### 26. ❌ `PublishDroneProductsToAGOL`
**Modes:** Local ✗ | CLI ✓ | AGOL ✓  
**Shared infrastructure:** ~ (AGOL publishing)

- **Issue:** Specialized to drone products; can be handled as raster publishing pattern
- **Recommendation:** Implement as part of general PromoteAGOLDataBetweenStages pattern

---

### 27. ❌ `FieldDataToReportPackage`
**Modes:** Local ✓ | CLI ✓ | AGOL ✗  
**Shared infrastructure:** ✓ (end-to-end pipeline)

- **Issue:** Meta-pipeline that orchestrates many tools; should be built AFTER individual tools work
- **Recommendation:** Defer until Phase 2 when core tools are integrated

---

---

# Summary Table

| Tool | Fit | Blocker | Priority | Integration Path |
|---|---|---|---|---|
| **ReconcileSurvey123AndLabResults** | ✅ Strong | None | High | Extend ImportQA logic |
| **BuildDashboardDataMart** | ✅ Strong | None | High | Build on normalized schema |
| **RouteSurvey123Submission** | ✅ Strong | None | High | Implement as CLI tool + webhook |
| **BuildSurvey123XLSFormFromConfig** | ✅ Strong | None | High | Config-to-form compiler |
| **ExportEventDatabaseSnapshot** | ✅ Strong | None | Medium | Leverage normalized tables |
| **EvaluateReportReadiness** | ✅ Strong | None | High | Audit QA + schema completeness |
| **PublishDashboardFromSpec** | ✅ Strong | None | Med-High | Design dashboard spec schema |
| **AuditAGOLItemDependencies** | ✅ Strong | None | Medium | Query AGOL API + inventory |
| **PromoteAGOLDataBetweenStages** | ✅ Strong | None | Medium | Extend RunHistory for promotion |
| **ProcessLevelLoop** | ✅ Strong | None | High | Define elevation history schema |
| **UpdateWellElevationsFromLevelLoop** | ✅ Strong | None | High | Extend well feature class |
| **ValidateRTKSurvey** | ✅ Strong | None | High | Extend QA framework |
| **ImportRTKSurveyPoints** | ✅ Strong | None | High | Add SurveyPoints schema |
| **ImportFieldBoringLogs** | ✅ Strong | None | High | Add boring schema (7 tables) |
| **GenerateBoringLogPDFs** | ✅ Strong | None | High | Choose PDF approach + template |
| **RegisterDroneFlight** | ✅ Strong | None | High | Add DroneFlights table |
| **DroneGCPCheckpointQA** | ✅ Strong | None | High | Define checkpoint QA table |
| **ImportDroneProducts** | ✅ Strong | None | High | Add raster registry |
| **RunFieldToGroundwaterModelPipeline** | ⚠️ Conditional | GWE validation, model QA schema | High | Stage: TIN first, then IDW, defer kriging |
| **BuildGroundwaterSurfaceModel** | ⚠️ Conditional | Elevation validation, model ranking subjectivity | High | Stage: TIN first |
| **GenerateRegulatoryTables** | ⚠️ Conditional | Nondetect rule selection, template system | Med-High | Reuse normalized results + templates |
| **EvaluateGroundwaterSurfaceModels** | ⚠️ Conditional | Model output registry schema | Medium | Depends on BuildGroundwaterSurfaceModel |
| **CreateSurvey123SamplingEvent** | ⚠️ Conditional | Event config schema extension | Medium | Extend site config |
| **BuildAnalyticalConcentrationSurface** | ⚠️ Conditional | Nondetect rules, plume boundary | Med-High | Reuse geostat framework |
| **CreateHostedViewsForStakeholders** | ⚠️ Conditional | Approval workflow, sharing groups | Medium | Document approval matrix |
| **BackupAGOLProjectItems** | ⚠️ Conditional | Storage location, restore SOP | Low-Medium | Define backup schedule + restore |
| **BuildClientDeliverablePackage** | ⚠️ Conditional | Manifest schema, upstream tools | Low-Medium | Depends on ExportEventDatabaseSnapshot + tables |
| **GenerateWellInspectionReports** | ⚠️ Conditional | Report template system, photos | Low-Medium | Design template format |
| **DEMConditioningPipeline** | ⚠️ Conditional | Config choices (fill/smooth/etc) | High | Define DEM processing config |
| **CompareDroneSurfaces** | ⚠️ Conditional | Level-of-detection threshold | Med-High | Define change detection config |
| **GenerateSubsurfaceProfileFromBorings** | ⚠️ Conditional | Graphics format, CAD export | High | Design profile format |
| **CalculateStockpileVolumes** | ⚠️ Conditional | Base surface definition | Medium | Define stockpile volume table |
| **SurveyToWellElevationUpdate** | ⚠️ Conditional | Depends on ProcessLevelLoop + ValidateRTKSurvey | High | Wire after dependencies work |
| **RTKControlCheckReport** | ⚠️ Conditional | Control point registry | Medium | Define control point config |
| **ExportSurveyToCADGIS** | ⚠️ Conditional | Feature code mapping | Medium | Define feature code config |
| **BoringToCivil3DGeotechModel** | ⚠️ Conditional | Geotechnical format varies | Medium | Test with target software |
| **DroneToCivil3DSurfacePackage** | ⚠️ Conditional | LandXML generation | Medium | Design surface export format |
| **GenerateDailyDrillingReport** | ❌ Weaker | Survey123-specific | Low | Keep as separate-repo candidate |
| **GeneratePortfolioMetrics** | ❌ Weaker | Portfolio-level (not core) | Low | Defer to Phase 2 |
| **BuildSurvey123BoringLogForm** | ❌ Weaker | One-time form generation | Low | Keep as separate-repo candidate |
| **SyncSurvey123BoringLogs** | ❌ Weaker | Depends on BuildSurvey123BoringLogForm | Low | Defer until Survey123 boring prioritized |
| **BoringLogReviewDashboard** | ❌ Weaker | AGOL-only | Low | Integrate into PublishDashboardFromSpec |
| **BoringLogCommentResolutionTracker** | ❌ Weaker | AGOL-only, specialized workflow | Low | Keep as separate-repo candidate |
| **Project Automation Hub (GUI)** | ❌ Weaker | Desktop GUI not core | Low | Defer to Phase 2 |
| **GenerateDroneImageryMapPackage** | ❌ Weaker | Figure output (not core) | Low | Build as ExportEventDatabaseSnapshot enhancement |
| **PublishDroneProductsToAGOL** | ❌ Weaker | AGOL publishing (general pattern) | Low | Use PromoteAGOLDataBetweenStages |
| **FieldDataToReportPackage** | ❌ Weaker | Meta-pipeline (build after tools work) | Low | Defer to Phase 2 |

---

# Recommendations

## Fast-Track to Main Roadmap (Next 18 months)
**Strong fit + high priority. Start immediately:**
1. ProcessLevelLoop
2. UpdateWellElevationsFromLevelLoop
3. ValidateRTKSurvey
4. ImportRTKSurveyPoints
5. ImportFieldBoringLogs
6. GenerateBoringLogPDFs
7. RegisterDroneFlight
8. DroneGCPCheckpointQA
9. ImportDroneProducts
10. ReconcileSurvey123AndLabResults
11. BuildDashboardDataMart
12. RouteSurvey123Submission
13. BuildSurvey123XLSFormFromConfig
14. ExportEventDatabaseSnapshot
15. EvaluateReportReadiness
16. PublishDashboardFromSpec
17. AuditAGOLItemDependencies
18. PromoteAGOLDataBetweenStages

## Conditional (Architecture Review Required Before Integration)
**High value but needs design work. Stage implementation:**
1. RunFieldToGroundwaterModelPipeline (stage 1: TIN, stage 2: IDW, stage 3: kriging)
2. BuildGroundwaterSurfaceModel (stage 1: TIN)
3. SurveyToWellElevationUpdate (depends on ProcessLevelLoop + ValidateRTKSurvey)
4. DEMConditioningPipeline
5. CompareDroneSurfaces
6. GenerateSubsurfaceProfileFromBorings
7. GenerateRegulatoryTables
8. BuildAnalyticalConcentrationSurface

## Keep as Separate-Repo Candidates
**Lower priority or specialized. Revisit in Phase 2:**
- Survey123-specific tools (BuildSurvey123BoringLogForm, SyncSurvey123BoringLogs, GenerateDailyDrillingReport)
- AGOL-only review tools (BoringLogReviewDashboard, BoringLogCommentResolutionTracker)
- Civil/CAD integration (BoringToCivil3DGeotechModel, DroneToCivil3DSurfacePackage)
- Portfolio/reporting (GeneratePortfolioMetrics, GenerateDroneImageryMapPackage, FieldDataToReportPackage)
- GUI application (Project Automation Hub)

---

# Architecture Notes

### Schema Additions Required

**Survey123/AGOL/Dashboard roadmap:**
- Dashboard data mart tables (Dash_SiteStatus, Dash_EventStatus, Dash_WellStatus, Dash_CurrentExceedances, Dash_GWLevelSummary, Dash_AnalyticalSummary, Dash_FieldQA, Dash_LabQA, Dash_OpenIssues, Dash_ReportReadiness)
- AGOL item registry (dashboard specs, layer versions, sharing groups)
- Model output rasters + comparison table for geostatistical models

**Boring/Survey/Drone/Level roadmap:**
- BoringLocations, LithologyIntervals, Samples, WellConstruction, GroundwaterObservations, Photos, CommentTracker (7 tables)
- SurveyPoints_Raw, SurveyPoints_QA
- DroneFlights, DroneControlPoints, DroneCheckpoints, DroneProductRegistry
- LevelLoopRuns, LevelLoopObservations
- ElevationHistory (with approval/supersede tracking)
- Stock-pile volumes, DEM difference results (for drone analysis tools)

### Config Extensions Needed

- Event config (analyte groups, field measurements, bottle/preservation types)
- Nondetect handling rules (per analyte or per matrix)
- Feature code translator (RTK codes → GIS layers)
- Dashboard specifications (YAML/JSON schema)
- Model parameterization (TIN/IDW/kriging config, tolerance rules, model ranking weights)

---

**Evaluation completed:** 2026-06-25
