# Implementation Roadmap: Prioritized Sequence

**Date:** 2026-06-25  
**Foundation:** Original Phase 1-4 sequence + 18 fast-track items + Lab EDD Importer priority

---

## Already Implemented ✅

These tools are production-ready:
- `ValidateAndConvertUnits` (3.5) — unit registry, validator, CLI
- `ManageAnalyteDictionary` (3.3) — canonical analyte names, aliases, units, display order
- `ValidateEnvConfig` (10.2) — config validation framework (partial)
- Framework: `ValidateEnvironmentalDatabase` (3.1) — basic structure in place

---

## Phase 1 — Stabilize the Framework (Establish Foundation)

**Status:** Partially complete. Finish these first.

### 1.1 Complete ValidateEnvConfig (10.2)
- ✅ Parser profile validation
- ✅ Figure spec validation
- ⏳ Complete: output filename pattern validation
- ✅ Analyte/screening level reference checks
- **Owner:** Current codebase  
- **Timeline:** 1-2 weeks to complete

### 1.2 Implement WriteRunHistory (10.4 variant)
- Create run history table + mechanism to log all tool executions
- Track: tool name, inputs, outputs, start/end time, status, errors, run_id
- **Dependency:** ValidateEnvConfig complete  
- **Owner:** TBD  
- **Timeline:** 2-3 weeks

### 1.3 Complete ValidateEnvironmentalDatabase (3.1)
- Implement all QA rules (currently partial)
- Generate QA feature/table, markdown report, CSV report, JSON summary
- **Dependency:** WriteRunHistory  
- **Owner:** TBD  
- **Timeline:** 3-4 weeks

### 1.4 Implement UpgradeEnvMonitoringGDBSchema (10.3)
- Schema versioning mechanism (current version tracking, migration scripts)
- Enable schema evolution without breaking existing projects
- **Dependency:** ValidateEnvConfig  
- **Owner:** TBD  
- **Timeline:** 2-3 weeks

### 1.5 Implement RunEnvJobQueue (10.4)
- Job manifest parser (YAML/JSON)
- Execution loop: run each job, log results, track failures
- **Dependency:** WriteRunHistory  
- **Owner:** TBD  
- **Timeline:** 2-3 weeks

**Phase 1 Total:** ~12 weeks to complete foundation

---

## Phase 2 — Improve Data Reliability (Field-to-Database)

**Includes 8 of the 18 fast-track items** + original Phase 2 tools

### 2.1 Lab EDD Importer ⭐ PRIORITY
**Tool name:** `ImportLabEDD` (2.3)

Many labs provide EDD CSV/XLSX. This becomes more reliable than report parsing.

**Inputs:** EDD file, lab format config, analyte dictionary, screening-level config  
**Outputs:** Env_Samples, Env_AnalyticalResults, Env_ImportQA

**Dependency:** ValidateAndConvertUnits ✅ (already implemented)  
**Owner:** TBD  
**Timeline:** 2-3 weeks  
**Priority:** HIGH (explicitly marked earlier)

---

### 2.2 Survey123 Field-to-Lab Reconciliation ⭐ FAST-TRACK
**Tool name:** `ReconcileSurvey123AndLabResults` (2.6)

Compares field submissions (Survey123) vs. lab results vs. GIS wells. Flags mismatches early.

**Flags:** Sample ID mismatch, date mismatch, location mismatch, matrix mismatch, nondetect issues  
**Dependency:** RunEnvJobQueue, ValidateEnvironmentalDatabase  
**Owner:** TBD  
**Timeline:** 2 weeks  
**Priority:** HIGH

---

### 2.3 Survey123 Sampling Event Generator ⭐ FAST-TRACK (Conditional)
**Tool name:** `CreateSurvey123SamplingEvent` (2.7)

Pre-field: well list → expected samples → crew assignment → COC draft.

**Dependency:** ManageAnalyteDictionary ✅ (already implemented)  
**Owner:** TBD  
**Timeline:** 1-2 weeks  
**Priority:** MEDIUM (field planning helper, not blocking)

---

### 2.4 ReconcileSampleLocations ⭐ ORIGINAL PHASE 2 (Already Planned)
**Tool name:** `ReconcileSampleLocations` (3.2)

Compares workbook location IDs vs. GIS features. Handles aliases (MW-1 vs MW-01).

**Dependency:** ValidateEnvironmentalDatabase  
**Owner:** TBD  
**Timeline:** 2 weeks  
**Priority:** HIGH (one of three recommended immediate additions)

---

### 2.5 ManageScreeningLevels ⭐ ORIGINAL PHASE 2
**Tool name:** `ManageScreeningLevels` (3.4)

Maintains regulatory thresholds by state, program, matrix, analyte, units, effective date.

**Dependency:** UpgradeEnvMonitoringGDBSchema  
**Owner:** TBD  
**Timeline:** 1-2 weeks  
**Priority:** HIGH (all analysis tools depend on this)

---

### 2.6 EvaluateDuplicateRPD ⭐ ORIGINAL PHASE 2 + NUMPY ENHANCEMENT
**Tool name:** `EvaluateDuplicateRPD` (3.6)

Parses parent/duplicate pairs, evaluates RPD, produces QA report.

**Enhancement (NEW):** Integrate Dan Patterson `n_near()` numpy algorithm for deterministic nearest-neighbor location matching (handles MW-1 vs MW-01 style variations).

**Dependency:** ManageScreeningLevels, ValidateAndConvertUnits ✅, numpy_geom wrapper module  
**Owner:** TBD  
**Timeline:** 2-3 weeks (was 1-2, +1 week for numpy integration)  
**Priority:** MEDIUM → MEDIUM-HIGH (numpy integration improves robustness)

---

### 2.7 Survey123 Smart Form Builder ⭐ FAST-TRACK
**Tool name:** `BuildSurvey123XLSFormFromConfig` (7.1a)

Auto-generates XLSForm from site/event config. Well dropdowns, DTW fields, sample ID builder, QA warnings.

**Dependency:** ManageAnalyteDictionary ✅, site config with event metadata  
**Owner:** TBD  
**Timeline:** 2 weeks  
**Priority:** HIGH

---

### 2.8 Survey123 Webhook Event Router ⭐ FAST-TRACK
**Tool name:** `RouteSurvey123Submission` (7.1b)

Field submission → validate → calculate GWE → update dashboard → write to GDB.

**Dependency:** BuildSurvey123XLSFormFromConfig, ValidateEnvironmentalDatabase, GWE calculation logic  
**Owner:** TBD  
**Timeline:** 2-3 weeks  
**Priority:** HIGH

**Phase 2 Total:** ~20 weeks (Lab EDD Importer + Survey123 suite + reconciliation + screening levels)

---

## Phase 3 — Improve Production Output (Maps, Figures, QA)

**Includes traditional Phase 3 tools + some fast-track items**

### 3.1 OptimizeCalloutPlacement ⭐ ORIGINAL PHASE 3 (Recommended Priority) + NUMPY ENHANCEMENT
**Tool name:** `OptimizeCalloutPlacement` (5.2)

Detect overlapping callout boxes, detect leaders crossing boxes, suggest alternate quadrants, flag unresolved collisions.

**Enhancements (NEW):**
- Integrate Dan Patterson `_trans_rot_2()` numpy algorithm for fast callout coordinate rotation
- Integrate Dan Patterson `_ch_simple()` numpy algorithm for convex hull collision detection
- Pure numpy computation makes iteration 10-100x faster on large callout sets

**Dependency:** BuildAnalyticalCallouts (assumed to exist or be built), numpy_geom wrapper module  
**Owner:** TBD  
**Timeline:** 3-4 weeks (was 2-3, +1-2 weeks for numpy integration + testing)  
**Priority:** HIGH (one of three recommended immediate additions) → CRITICAL (numpy performance boost)

---

### 3.2 ManageCalloutPlacementOverrides ⭐ ORIGINAL PHASE 3
**Tool name:** `ManageCalloutPlacementOverrides` (5.3)

GUI for maintaining override points. Prevents automatic regeneration from erasing manual cartography.

**Dependency:** OptimizeCalloutPlacement  
**Owner:** TBD  
**Timeline:** 1-2 weeks  
**Priority:** HIGH

---

### 3.3 BuildAnalyticalKey ⭐ ORIGINAL PHASE 3
**Tool name:** `BuildAnalyticalKey` (5.5)

Create or update analytical key/table for map layouts. Generates layout text, table graphics, optional GDB table.

**Dependency:** ManageAnalyteDictionary ✅, ManageScreeningLevels  
**Owner:** TBD  
**Timeline:** 1 week  
**Priority:** MEDIUM

---

### 3.4 GenerateSiteMapSeries ⭐ ORIGINAL PHASE 3
**Tool name:** `GenerateSiteMapSeries` (5.6)

Builds figure packets across many sites/events. One PDF per site, combined appendix, historical series.

**Dependency:** OptimizeCalloutPlacement, BuildAnalyticalKey  
**Owner:** TBD  
**Timeline:** 1-2 weeks  
**Priority:** MEDIUM

---

### 3.5 BuildReportFigurePackage ⭐ ORIGINAL PHASE 3
**Tool name:** `BuildReportFigurePackage` (5.7)

Creates structured deliverable folder with PDFs, PNGs, QA, tables, source data manifest.

**Dependency:** GenerateSiteMapSeries, ExportEventDatabaseSnapshot  
**Owner:** TBD  
**Timeline:** 1 week  
**Priority:** MEDIUM

---

### 3.6 ExportEventDatabaseSnapshot ⭐ FAST-TRACK
**Tool name:** `ExportEventDatabaseSnapshot` (9.0a)

Frozen GDB snapshot for report event. Captures wells, samples, results, water levels, callouts, contours, QA, figures.

**Dependency:** ValidateEnvironmentalDatabase, RunEnvJobQueue  
**Owner:** TBD  
**Timeline:** 1-2 weeks  
**Priority:** HIGH

---

### 3.7 EvaluateReportReadiness ⭐ FAST-TRACK
**Tool name:** `EvaluateReportReadiness` (9.0b)

Single pass/fail gate: field complete? lab received? GIS ready? QA passing?

**Dependency:** ValidateEnvironmentalDatabase, ExportEventDatabaseSnapshot  
**Owner:** TBD  
**Timeline:** 1 week  
**Priority:** HIGH

**Phase 3 Total:** ~14 weeks

---

## Phase 4 — Expand Deliverables (Field Survey + AGOL + Reporting)

**Includes 9 fast-track items from survey/boring/drone domains + AGOL tools**

### 4.1 Field Survey Foundation (Survey, RTK, Level Loop, Boring Logs)

**4.1a ProcessLevelLoop ⭐ FAST-TRACK**
- **Tool name:** `ProcessLevelLoop` (8.1)
- Differential level: misclosure, adjustment, elevation history
- **Dependency:** UpgradeEnvMonitoringGDBSchema (add ElevationHistory table)
- **Owner:** TBD
- **Timeline:** 2 weeks
- **Priority:** HIGH

**4.1b UpdateWellElevationsFromLevelLoop ⭐ FAST-TRACK**
- **Tool name:** `UpdateWellElevationsFromLevelLoop` (8.2)
- Push adjusted elevations into well database with audit trail
- **Dependency:** ProcessLevelLoop
- **Owner:** TBD
- **Timeline:** 1 week
- **Priority:** HIGH

**4.1c ImportRTKSurveyPoints ⭐ FAST-TRACK**
- **Tool name:** `ImportRTKSurveyPoints` (8.3)
- CSV/TXT/shapefile → SurveyPoints_Raw/SurveyPoints_QA
- **Dependency:** UpgradeEnvMonitoringGDBSchema (add SurveyPoints tables)
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** HIGH

**4.1d ValidateRTKSurvey ⭐ FAST-TRACK**
- **Tool name:** `ValidateRTKSurvey` (8.4)
- RTK QA: precision, datum, control residuals, duplicates
- **Dependency:** ImportRTKSurveyPoints, ValidateEnvironmentalDatabase
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** HIGH

### 4.2 Boring Log Foundation

**4.2a CreateBoringLogDatabase ⭐ FAST-TRACK**
- **Tool name:** `CreateBoringLogDatabase` (8.0a)
- Normalized boring schema: 7 tables (BoringLocations, LithologyIntervals, Samples, WellConstruction, GroundwaterObservations, Photos, CommentTracker)
- **Dependency:** UpgradeEnvMonitoringGDBSchema
- **Owner:** TBD
- **Timeline:** 2 weeks (schema design + implementation)
- **Priority:** HIGH

**4.2b ImportFieldBoringLogs ⭐ FAST-TRACK**
- **Tool name:** `ImportFieldBoringLogs` (8.0b)
- Survey123/Excel/CSV → normalized boring database
- **Dependency:** CreateBoringLogDatabase, ValidateEnvironmentalDatabase
- **Owner:** TBD
- **Timeline:** 2 weeks
- **Priority:** HIGH

**4.2c GenerateBoringLogPDFs ⭐ FAST-TRACK**
- **Tool name:** `GenerateBoringLogPDFs` (8.0c)
- Standardized boring log PDFs from normalized database
- **Dependency:** ImportFieldBoringLogs
- **Owner:** TBD
- **Timeline:** 2-3 weeks (PDF generation + template)
- **Priority:** HIGH

### 4.3 Drone Operations

**4.3a RegisterDroneFlight ⭐ FAST-TRACK**
- **Tool name:** `RegisterDroneFlight` (8.6)
- Flight inventory: pilot, aircraft, sensor, outputs, accuracy status
- **Dependency:** UpgradeEnvMonitoringGDBSchema (add DroneFlights table)
- **Owner:** TBD
- **Timeline:** 1 week
- **Priority:** HIGH

**4.3b ImportDroneProducts ⭐ FAST-TRACK**
- **Tool name:** `ImportDroneProducts` (8.8)
- Orthomosaic/DSM/DEM/point cloud → raster catalog + GCP features
- **Dependency:** RegisterDroneFlight, UpgradeEnvMonitoringGDBSchema
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** HIGH

**4.3c DroneGCPCheckpointQA ⭐ FAST-TRACK**
- **Tool name:** `DroneGCPCheckpointQA` (8.7)
- Photogrammetry accuracy: residuals, RMSE, pass/fail QA
- **Dependency:** ImportDroneProducts, ValidateEnvironmentalDatabase
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** HIGH

### 4.4 AGOL & Dashboard Tools

**4.4a BuildDashboardDataMart ⭐ FAST-TRACK**
- **Tool name:** `BuildDashboardDataMart` (6.7)
- Flattened dashboard-specific tables (not raw analytical tables)
- **Dependency:** UpgradeEnvMonitoringGDBSchema (add Dash_* tables), ValidateEnvironmentalDatabase
- **Owner:** TBD
- **Timeline:** 2 weeks
- **Priority:** HIGH

**4.4b PublishDashboardFromSpec ⭐ FAST-TRACK**
- **Tool name:** `PublishDashboardFromSpec` (6.8)
- Dashboard creation from YAML config
- **Dependency:** BuildDashboardDataMart, AGOL API integration
- **Owner:** TBD
- **Timeline:** 2-3 weeks
- **Priority:** HIGH

**4.4c AuditAGOLItemDependencies ⭐ FAST-TRACK**
- **Tool name:** `AuditAGOLItemDependencies` (6.9)
- Detect broken dependencies across AGOL items
- **Dependency:** AGOL API integration, item inventory table
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** MEDIUM

**4.4d PromoteAGOLDataBetweenStages ⭐ FAST-TRACK**
- **Tool name:** `PromoteAGOLDataBetweenStages` (6.10)
- Release control: DEV → QA → PROD pipeline
- **Dependency:** RunEnvJobQueue, UpgradeEnvMonitoringGDBSchema (add promotion state to RunHistory)
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** MEDIUM

**4.4e CreateHostedViewsForStakeholders ⭐ FAST-TRACK (Conditional)**
- **Tool name:** `CreateHostedViewsForStakeholders` (6.11)
- Multi-audience views (QA, Client, Crew, Public, Regulatory)
- **Dependency:** AGOL API, approval matrix definition
- **Owner:** TBD
- **Timeline:** 1-2 weeks
- **Priority:** MEDIUM

**Phase 4 Total:** ~24 weeks (survey + boring + drone + AGOL/dashboard suite)

---

## Phase 5 — Advanced Analytics & Conditional Tools (Future)

Deferred pending architecture decisions:
- RunFieldToGroundwaterModelPipeline (geostatistical modeling)
- BuildGroundwaterSurfaceModel
- GenerateRegulatoryTables
- BuildAnalyticalConcentrationSurface
- Other conditional tools (see CONDITIONAL_TOOLS_REVIEW.md)

---

## Implementation Timeline Summary

| Phase | Focus | Duration | Cumulative |
|---|---|---|---|
| **Phase 1** | Framework foundation | ~12 weeks | 12 weeks |
| **Phase 2** | Data intake + field reconciliation + Survey123 | ~20 weeks | 32 weeks |
| **Phase 3** | Maps, figures, callout optimization, reporting | ~14 weeks | 46 weeks |
| **Phase 4** | Field survey, boring logs, drone, AGOL/dashboards | ~24 weeks | 70 weeks |
| **Phase 5** | Geostatistical modeling, advanced analytics | TBD | TBD+ |

**Total for Phases 1-4:** ~70 weeks (~16 months, assuming 1 full-time developer + part-time review)

---

## Critical Path Dependencies

```
Phase 1 (12 weeks)
    ↓
ValidateEnvConfig → WriteRunHistory → ValidateEnvironmentalDatabase
    ↓
Phase 2 (20 weeks)
    ├─ Lab EDD Importer (priority)
    ├─ Survey123 form builder → Webhook router
    ├─ ReconcileSampleLocations, ManageScreeningLevels
    └─ ReconcileSurvey123AndLabResults
    ↓
Phase 3 (14 weeks)
    ├─ OptimizeCalloutPlacement → ManageCalloutPlacement Overrides
    ├─ BuildAnalyticalKey, GenerateSiteMapSeries
    └─ ExportEventDatabaseSnapshot → EvaluateReportReadiness
    ↓
Phase 4 (24 weeks) [PARALLEL TRACKS]
    ├─ Survey Foundation (Level Loop → RTK Import/Validate)
    ├─ Boring Logs (Database → Import → PDFs)
    ├─ Drone (Register → Import → QA)
    └─ AGOL/Dashboards (DataMart → PublishFromSpec → Audit/Promote)
```

---

## "Build Next" Recommendation (Aligned with Priorities)

**Immediate focus (next 2-3 months):**

1. **Complete Phase 1 foundation** — finish ValidateEnvConfig, implement WriteRunHistory, ValidateEnvironmentalDatabase (if not fully implemented)

2. **Implement Lab EDD Importer** (Tool 2.3) — explicitly marked as priority; foundation for lab data intake

3. **Begin Phase 2 in parallel:**
   - ReconcileSampleLocations (already planned, high ROI)
   - ManageScreeningLevels (all analysis tools depend on this)
   - BuildSurvey123XLSFormFromConfig + RouteSurvey123Submission (field-to-database core)

4. **Start Phase 3 planning:**
   - OptimizeCalloutPlacement (one of three recommended priority builds)
   - ExportEventDatabaseSnapshot (report reproducibility)

This keeps the roadmap grounded in the original Phase 1-4 sequence while integrating the 18 fast-track items and Lab EDD Importer priority.

---

**For detailed blocker analysis of conditional tools, see:** `CONDITIONAL_TOOLS_REVIEW.md`
