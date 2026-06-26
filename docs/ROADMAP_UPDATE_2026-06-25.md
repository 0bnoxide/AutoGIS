# Roadmap Update: 18 Fast-Track Items Integrated

**Date:** 2026-06-25  
**Source:** Candidate roadmap evaluation against hybrid harness architecture (local + CLI + AGOL/cloud + shared infrastructure)

---

## Summary

18 tools from the two candidate roadmaps have been integrated into the main `envmon-feature-roadmap.md` based on evaluation showing they fit all three execution modes and leverage shared infrastructure.

**Fast-track items added:** 18  
**Conditional items deferred:** 8 (require architecture review before integration)  
**Separate-repo candidates:** 21 (specialized, external dependencies, or Phase 2 scope)

---

## Tools Integrated by Section

### Section 2 (Data Intake and Normalization)
**2 new tools added:**
- 2.6 `ReconcileSurvey123AndLabResults` — Compares field/lab/GIS data before map production
- 2.7 `CreateSurvey123SamplingEvent` (conditional) — Pre-field event planning

### Section 7 (Field Workflow and Survey123 Tools)
**2 new tools added:**
- 7.1a `BuildSurvey123XLSFormFromConfig` — Removes manual form maintenance; form stays synced with config
- 7.1b `RouteSurvey123Submission` — Webhook: field submission → GIS database → dashboard

### Section 6 (AGOL and Dashboard Tools)
**5 new tools added:**
- 6.7 `BuildDashboardDataMart` — Flattened dashboard-specific tables (not raw analytical tables)
- 6.8 `PublishDashboardFromSpec` — Dashboard creation from YAML; no more manual AGOL clicking
- 6.9 `AuditAGOLItemDependencies` — Detect broken dependencies across AGOL items
- 6.10 `PromoteAGOLDataBetweenStages` — Release control: DEV → QA → PROD pipeline
- 6.11 `CreateHostedViewsForStakeholders` — Multi-audience views (QA, Client, Crew, Public, Regulatory)

### Section 8 (Survey, Boring, RTK, Drone, and CAD Handoff)
**Expanded with 9 new tools:**

**Boring Log Documentation (Foundation)**
- 8.0a `CreateBoringLogDatabase` — Normalized boring log schema (7 tables)
- 8.0b `ImportFieldBoringLogs` — Survey123/Excel/CSV → normalized boring database
- 8.0c `GenerateBoringLogPDFs` — Boring log appendix + photo log + QA

**Survey and Elevation (Level Loops + RTK)**
- 8.1 `ProcessLevelLoop` — Differential leveling: misclosure, adjustment, elevation history
- 8.2 `UpdateWellElevationsFromLevelLoop` — Elevation history table with approval/supersede tracking
- 8.3 `ImportRTKSurveyPoints` — CSV/shapefile → SurveyPoints_Raw/SurveyPoints_QA
- 8.4 `ValidateRTKSurvey` — RTK QA: precision, datum, control residuals, duplicates
- 8.5 `SurveyToWellElevationUpdate` (conditional) — Integrates level loop + RTK + GWE recalculation

**Drone Operations**
- 8.6 `RegisterDroneFlight` — Flight inventory: pilot, aircraft, sensor, outputs, accuracy status
- 8.7 `DroneGCPCheckpointQA` — Photogrammetry accuracy: residuals, RMSE, pass/fail QA
- 8.8 `ImportDroneProducts` — Orthomosaic/DSM/DEM/point cloud → raster catalog + GCP features

### Section 9 (Reporting and Deliverable Automation)
**2 new tools added:**
- 9.0a `ExportEventDatabaseSnapshot` — Frozen GDB snapshot for report event with audit trail
- 9.0b `EvaluateReportReadiness` — Single pass/fail gate: field complete? lab received? GIS ready? QA passing?

---

## Execution Mode Coverage

All 18 integrated tools pass the evaluation criteria:

| Mode | Count |
|---|---|
| **Local (ArcGIS Pro toolbox)** | 18/18 ✓ |
| **CLI (command-line harness)** | 18/18 ✓ |
| **AGOL/Cloud (webhooks, triggers)** | 15/18 (3 CLI-heavy) ✓ |
| **Shared infrastructure leverage** | 18/18 ✓ |

---

## New Schema Tables Required

### Boring Log Schema (Section 8)
- BoringLocations
- LithologyIntervals
- Samples (boring samples, not just analytical)
- WellConstruction
- GroundwaterObservations
- Photos
- CommentTracker (review comments + resolution)

### Survey and Elevation Schema (Section 8)
- SurveyPoints_Raw
- SurveyPoints_QA
- LevelLoopRuns
- LevelLoopObservations
- ElevationHistory (with ApprovedForUse, Superseded, SourceRunID)

### Drone Schema (Section 8)
- DroneFlights
- DroneControlPoints
- DroneCheckpoints
- DroneProductRegistry

### Dashboard Schema (Section 6)
- Dash_SiteStatus
- Dash_EventStatus
- Dash_WellStatus
- Dash_CurrentExceedances
- Dash_GWLevelSummary
- Dash_AnalyticalSummary
- Dash_FieldQA
- Dash_LabQA
- Dash_OpenIssues
- Dash_ReportReadiness

**Total new tables:** ~27 (mostly in boring + survey + drone domains)

---

## Config Extensions Needed

- Event config (analyte groups, field measurements, bottle/preservation)
- Nondetect handling rules (per analyte or matrix)
- Feature code translator (RTK codes → GIS layers)
- Dashboard specifications (YAML/JSON schema)
- Level loop closure tolerance
- RTK precision tolerance

---

## Next Steps: Conditional Tools Review

8 tools remain conditional (high value but need architecture review before integration):

1. **RunFieldToGroundwaterModelPipeline** — Stage 1 (TIN), Stage 2 (IDW), Stage 3 (kriging)
2. **BuildGroundwaterSurfaceModel** — Geostatistical modeling (TIN/IDW/EBK/kriging)
3. **GenerateRegulatoryTables** — Nondetect rules + template system design needed
4. **EvaluateGroundwaterSurfaceModels** — Model output registry + ranking logic
5. **BuildAnalyticalConcentrationSurface** — Nondetect rules + plume boundary logic
6. **DEMConditioningPipeline** — DEM void-fill/smoothing configuration
7. **CompareDroneSurfaces** — Level-of-detection threshold configuration
8. **GenerateSubsurfaceProfileFromBorings** — Profile graphics format + CAD export design

---

## Implementation Priority (Suggested Sequencing)

### Immediate (Phase 1 — Foundation)
1. Define schema additions (boring, survey, drone, elevation history, dashboard tables)
2. ProcessLevelLoop + UpdateWellElevationsFromLevelLoop (well elevation audit trail)
3. ImportRTKSurveyPoints + ValidateRTKSurvey (field survey baseline)
4. RegisterDroneFlight + ImportDroneProducts (drone inventory)

### Near-term (Phase 2 — Field Workflow)
5. BuildSurvey123XLSFormFromConfig + RouteSurvey123Submission (field-to-database pipeline)
6. ReconcileSurvey123AndLabResults (field/lab reconciliation)
7. ImportFieldBoringLogs + GenerateBoringLogPDFs (boring log deliverables)
8. DroneGCPCheckpointQA (drone accuracy validation)

### Medium-term (Phase 3 — Dashboards & Reporting)
9. BuildDashboardDataMart (dashboard data flattening)
10. PublishDashboardFromSpec (config-driven dashboards)
11. AuditAGOLItemDependencies + PromoteAGOLDataBetweenStages (AGOL release control)
12. ExportEventDatabaseSnapshot + EvaluateReportReadiness (report preparation)
13. CreateSurvey123SamplingEvent (optional, field planning helper)

### Phase 4 — Advanced (Conditional - After Core Tools Stable)
14. SurveyToWellElevationUpdate (integrates phases 1-2)
15. Conditional geostatistical tools (groundwater/concentration surface modeling)

---

## Files Updated

- `docs/envmon-feature-roadmap.md` — 18 fast-track tools integrated into sections 2, 6, 7, 8, 9
- `docs/candidates/EVALUATION_RESULTS.md` — Full evaluation rationale for each tool
- `docs/ROADMAP_UPDATE_2026-06-25.md` — This summary

---

## Next Session

**Review conditional tools** against remaining architecture questions:
- Geostatistical modeling pipeline (kriging, EBK, model ranking)
- DEM conditioning and surface comparison
- Concentration surface modeling with nondetect handling
- Subsurface profile graphics design

See `docs/candidates/EVALUATION_RESULTS.md` (section "Conditional Fit") for detailed blocker analysis.
