# Roadmap Status Review — 2026-06-27

**Reviewer:** Claude Code (night-implementer planning session)
**Sources reconciled:** `docs/envmon-feature-roadmap.md` (79 named tools, sections 2–11),
`docs/IMPLEMENTATION_ROADMAP_PRIORITIZED.md`, `docs/ROADMAP_UPDATE_2026-06-25.md`
**Method:** Cross-referenced every named tool against registered CLI commands
(`autogis/adapters/cli.py`), core modules (`autogis/core/envmon/`,
`autogis/core/common/`), and schema dataclasses (`autogis/core/common/schema/`).

---

## Headline numbers

| Bucket | Count | Approx. % of catalog |
|---|---:|---:|
| **Fully implemented** (CLI command + core module + tests) | 17 | ~22% |
| **Foundation laid / partial** (schema or related module exists, tool not wired) | 8 | ~10% |
| **Not started** | ~54 | ~68% |
| **Catalog total** (distinct named tools, §2–11) | ~79 | — |

> The attachment harvester (`autogis/core/harvest/`) is a separate, fully-shipped
> domain not counted in the 79 envmon tools. Figure-pipeline support modules
> (`build_current_event`, `export_figures`, `import_to_gdb`, `layout_manager`,
> `table_normalizer`, `build_figure_dataset`) are infrastructure, also not counted
> as standalone catalog tools.

Test baseline at review time: **329 passing** (`python -m pytest -q`).

---

## Fully implemented (17)

| Tool | Roadmap # | Surface |
|---|---|---|
| ImportLabEDD | 2.3 | `envmon import-edd` |
| ValidateEnvironmentalDatabase | 3.1 | `envmon validate-db` |
| ReconcileSampleLocations | 3.2 | `envmon reconcile-locations` |
| ManageAnalyteDictionary | 3.3 | `envmon manage-analyte-dict` |
| ValidateAndConvertUnits | 3.5 | `envmon validate-units` |
| EvaluateDuplicateRPD | 3.6 | `envmon evaluate-rpd-qa` |
| GenerateDraftGWContours | 4.2 | `envmon gw-contours` |
| BuildAnalyticalCallouts | 5.1 | `envmon build-callouts` |
| OptimizeCalloutPlacement | 5.2 | `envmon optimize-callouts` |
| ManageCalloutPlacementOverrides | 5.3 | `envmon manage-callout-overrides` |
| PublishEnvironmentalLayersToAGOL | 6.1 | `envmon publish-layer` |
| BuildSurvey123XLSFormFromConfig | 7.1a | `envmon build-survey-form` |
| EvaluateReportReadiness | 9.0b | `envmon evaluate-readiness` |
| ExportAnalyticalSummaryTables | 9.1 | `envmon export-report-format-summary-tables` |
| ValidateEnvConfig | 10.2 | `envmon validate-config` |
| UpgradeEnvMonitoringGDBSchema | 10.3 | `envmon upgrade-schema` |
| WriteRunHistory | 10.5 | `core/common/run_history.py` (used by readiness gate) |

## Foundation laid / partial (8)

| Tool | Roadmap # | What exists | What's missing |
|---|---|---|---|
| BuildGroundwaterElevationEvent | 4.1 | `normalize_groundwater.py`, `build_current_event.py` | dedicated event-builder + flags (`Dry`/`NM`/`NS`/anomalous) |
| BuildAnalyticalExceedanceEvent | 4.4 | `build_current_event.py` emits `Env_CurrentEventWide` w/ HasDetection/HasExceedance | event-mode selectors (latest/range/max), style fields |
| CreateWorkbookParserProfile | 2.1 | `excel_workbook_inspector.py`, `excel_profile_reader.py` | profile *drafting* output |
| CreateBoringLogDatabase | 8.0a | `schema/boring.py` (7 dataclasses) + upgrade-schema tables | standalone create/validate tool |
| SyncFieldAttachments | 6.5 | attachment harvester (separate domain) | envmon-side attachment index table wiring |
| (RTK schema) ImportRTKSurveyPoints / ValidateRTKSurvey | 8.3 / 8.4 | `schema/survey.py` (`SurveyPointRaw`/`SurveyPointQA`) | import + QA logic |
| (Level-loop schema) ProcessLevelLoop / Update… | 8.1 / 8.2 | `schema/survey.py` (`LevelLoopRun`/`Observation`/`ElevationHistory`) | computation + history-write logic |
| (Drone/Dashboard schema) 8.6–8.8 / 6.7–6.11 | — | `schema/drone.py`, `schema/dashboard.py` | every consuming tool |

**Key insight:** the ADR-0014 schema-dataclass package + ADR-0018 upgrade-schema
work already shipped the *tables* for the survey, boring, drone, and dashboard
domains. The dataclasses exist and import arcpy-free. What remains in those
domains is purely the **headless processing/import logic** that fills them — which
is exactly the kind of bounded, testable work the night implementer is best at.

---

## Not started — grouped by domain (~54)

- **Data intake (§2):** BatchImportEnvironmentalWorkbooks (2.2),
  MigrateLegacyMonitoringData (2.4), RegisterSourceDocuments (2.5),
  ReconcileSurvey123AndLabResults (2.6), CreateSurvey123SamplingEvent (2.7)
- **Analysis (§4):** EstimateGWFlowDirection (4.3), GenerateDraftPlumeBoundary (4.5),
  GenerateWellTrendCharts (4.6), **CompareMonitoringEvents (4.7)**,
  SelectSoilIntervalsForMapping (4.8), BuildMaxResultMapDataset (4.9),
  **IdentifyMonitoringDataGaps (4.10)**
- **Cartography (§5):** GenerateArcadeLabelExpressions (5.4), BuildAnalyticalKey (5.5),
  GenerateSiteMapSeries (5.6, arcpy), BuildReportFigurePackage (5.7),
  UpdateLayoutDynamicText (5.8, arcpy)
- **AGOL/cloud (§6):** SyncAGOLFeatureLayerToGDB (6.2), UpdateAGOLWebMapFromFigureSpec (6.3),
  RefreshMonitoringDashboardData (6.4), AuditAGOLSchemaAgainstLocalConfig (6.6),
  BuildDashboardDataMart (6.7), PublishDashboardFromSpec (6.8),
  AuditAGOLItemDependencies (6.9), PromoteAGOLDataBetweenStages (6.10),
  CreateHostedViewsForStakeholders (6.11)
- **Field/Survey123 (§7):** BuildFieldMapsMonitoringProject (7.1),
  RouteSurvey123Submission (7.1b), CreateSamplingEventPlan (7.2),
  ReconcileFieldAndLabData (7.3), GenerateWellInspectionPhotoReport (7.4)
- **Survey/boring/RTK/drone/CAD (§8):** ImportFieldBoringLogs (8.0b),
  GenerateBoringLogPDFs (8.0c), **ProcessLevelLoop (8.1)**,
  UpdateWellElevationsFromLevelLoop (8.2), ImportRTKSurveyPoints (8.3),
  ValidateRTKSurvey (8.4), SurveyToWellElevationUpdate (8.5),
  RegisterDroneFlight (8.6), DroneGCPCheckpointQA (8.7), ImportDroneProducts (8.8),
  BuildCADExportPackage (8.9), ExportContoursForCivil3D, ValidateSurveyDeliverable
- **Reporting (§9):** ExportEventDatabaseSnapshot (9.0a),
  BuildMonitoringReportAppendix (9.2), GenerateEventChangeLog (9.3),
  IngestReviewerMapComments (9.4)
- **Admin (§10):** ListAvailableEnvTools (10.1), RunEnvJobQueue (10.4),
  GenerateSyntheticEnvWorkbook (10.6)
- **AI-assisted (§11):** AIDraftParserProfile, AIExplainQAReport, AIDraftFigureSpec,
  AIMapReviewChecklist (all deferred — need LLM seam design)
- **Conditional/geostatistical (Phase 5):** 8 deferred tools per
  `ROADMAP_UPDATE_2026-06-25.md` (kriging/EBK/surface modeling) — blocked on
  architecture review.
- **Both groups above are a separate future development phase, not a backlog to pick
  from** — see `CLAUDE.md` for the standing phase-gate policy.

---

## Night-implementer batch selected this session

Three **headless, arcpy-free, schema-backed** tools across three domains, each
independently shippable and TDD-friendly. See ADR-0026 and the plans in
`docs/superpowers/plans/2026-06-27-*.md`:

1. **CompareMonitoringEvents (4.7)** — analysis; current-vs-prior delta/trend table.
2. **ProcessLevelLoop (8.1)** — field survey; differential-leveling math + QA,
   fills the existing `LevelLoopRun`/`LevelLoopObservation`/`ElevationHistory` schema.
3. **IdentifyMonitoringDataGaps (4.10)** — QA; missing wells/analytes vs an
   expected sampling schedule.

These were chosen over the higher-headline AGOL/dashboard tools (6.7–6.11) and
arcpy-bound cartography tools (5.6, 5.8) precisely because the night implementer
runs in web/cloud sessions where arcpy is absent and the arcpy-free core
invariant (ADR-0002) must hold.
