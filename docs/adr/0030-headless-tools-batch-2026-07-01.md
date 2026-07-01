# ADR-0030 — Headless tools batch (2026-07-01): RTK control check, portfolio
metrics, GW model cross-validation, survey CAD/GIS export, well inspection
reports

**Status:** Accepted
**Date:** 2026-07-01
**Deciders:** Greg / Claude Code
**Related:** ADR-0002 (arcpy-free core), ADR-0017 (run-history CSV log),
ADR-0026 (night-implementer batch 2026-06-27), ADR-0028 (cloud-tools batch
2026-06-28), `docs/candidates/EVALUATION_RESULTS.md`

---

## Context

Asked to pick five new features autonomously and ship them, the selection
was drawn from the project's own (already-scoped) roadmap evaluation in
`docs/candidates/EVALUATION_RESULTS.md` rather than invented from scratch —
that document had already scored ~45 candidate tools by fit and named their
blockers, so choosing from it means picking work the project itself flagged
as valuable instead of re-litigating scope.

The session runs in a web/cloud environment where **arcpy is absent** (per
ADR-0002 and the pattern established in ADR-0026/0028), so the selection was
filtered to genuinely unimplemented, headless-feasible candidates:

- Cross-referenced every "strong fit" and "conditional fit" tool name in
  `EVALUATION_RESULTS.md` against `autogis/runtime/capabilities.py`'s
  `TOOL_REGISTRY` and `autogis/adapters/cli.py`'s registered commands. Most of
  the "strong fit" list (`ProcessLevelLoop`, `ImportRTKSurveyPoints`,
  `ImportFieldBoringLogs`, `RegisterDroneFlight`, `DroneGCPCheckpointQA`,
  `ImportDroneProducts`, `BuildDashboardDataMart`, `RouteSurvey123Submission`,
  `BuildSurvey123XLSFormFromConfig`, `EvaluateReportReadiness`,
  `ExportEventDatabaseSnapshot`, `CreateSurvey123SamplingEvent` as
  `create-sampling-plan`) turned out to already be shipped.
- Excluded every AGOL-only candidate (`PublishDashboardFromSpec`,
  `AuditAGOLItemDependencies`, `PromoteAGOLDataBetweenStages`,
  `BackupAGOLProjectItems`, `CreateHostedViewsForStakeholders`) — this
  environment has no `arcgis` credentials to test against, and per ADR-0002
  they are out of scope for a headless batch.
- Excluded every raster/kriging-heavy candidate
  (`DEMConditioningPipeline`, `CompareDroneSurfaces`,
  `BuildAnalyticalConcentrationSurface`, `BuildGroundwaterSurfaceModel`) as
  arcpy/scipy-dependent.
- Of the remaining genuine gaps, picked five that are pure-stdlib
  (`csv`/`math`/`json`/`yaml`), each independently useful, each reusing an
  existing seam (`QACollector`, `RunHistory`, `evaluate_readiness`,
  `import_rtk_survey.parse_rtk_csv`) rather than inventing new schema.

---

## Decision

Ship five headless, arcpy-free tools, each registered `Runtime.CLOUD` in
`autogis/runtime/capabilities.py`, each independently committed and tested:

1. **RTKControlCheckReport** — `envmon rtk-control-check`
   → `core/envmon/rtk_control_check.py`
2. **GeneratePortfolioMetrics** — `envmon portfolio-metrics`
   → `core/envmon/portfolio_metrics.py`
3. **EvaluateGroundwaterSurfaceModels** — `envmon evaluate-gw-models`
   → `core/envmon/evaluate_gw_models.py`
4. **ExportSurveyToCADGIS** — `envmon export-survey-cad`
   → `core/envmon/export_survey_cad.py`
5. **GenerateWellInspectionReports** — `envmon well-inspection-report`
   → `core/envmon/well_inspection_report.py`

### Shared conventions

- New core modules under `autogis/core/envmon/`, pure stdlib + existing
  helpers; **no arcpy, no arcgis**; `export_survey_cad.py` uses `yaml`
  (already a core dependency) for its feature-code map, the rest are CSV/JSON.
- QA via `QACollector` (`core/common/qa.py`); CLI exit/report via the
  existing module-level `_render_qa(qa, report, fail_on)` and
  `qa_report_options` decorator in `cli.py`.
- One `tests/test_*.py` per tool, 41 new tests, plus a manual CLI smoke pass
  (`--help` and a real invocation for all five commands) to catch Click
  wiring bugs the core-level unit tests can't see.

### Functional-structure decisions (locked)

**RTKControlCheckReport**
- Deliberately **not** built by joining `import_rtk_survey.RTKPoint` against a
  second control-point table — it takes one flat CSV
  (`control_id, published_x/y/z, surveyed_x/y/z`), matching
  `DroneGCPCheckpointQA`'s input shape but for a different QA convention.
- **Key semantic difference from `DroneGCPCheckpointQA`:** photogrammetry
  checkpoint QA gates on an aggregate RMS threshold (a few outlier points are
  tolerable if the overall RMS is in spec). A survey control network is only
  as good as its worst point, so `overall_pass` here requires **every** point
  to individually pass its tolerance; RMSE is reported for information only,
  not as the gate. Per-point failures are `SEV_ERROR` (not `WARNING` as in
  the drone tool) because one bad control point invalidates downstream survey
  data. Tolerances default in **feet** (`0.05`/`0.10`), matching the existing
  `validate_rtk_survey.py` convention, vs. the drone tool's metres.

**GeneratePortfolioMetrics**
- No new schema: `RunRecord` already carries `site_id`, so a portfolio is
  just "every distinct `site_id` in one run-history log." Reuses
  `evaluate_readiness()` per discovered site rather than reimplementing
  readiness logic — the only new code is site discovery
  (`RunHistory.query()` with no filter, `set` of `site_id`) and re-deriving
  the per-tool missing-list via `RunHistory.latest()` for a human-readable
  CSV/console column (duplicates 2 lines of `evaluate_readiness`'s own check
  rather than parsing its QA message strings, which would be fragile).
- `--site` is repeatable to scope to an explicit site list; default is full
  discovery.

**EvaluateGroundwaterSurfaceModels**
- Consumes a **wide** CSV (`well_id, observed_ft`, then one column per model)
  rather than long/tidy — this matches how a hydrogeologist would actually
  assemble a comparison spreadsheet from multiple model runs, and needs no
  model-name enum. Any column other than `well_id`/`observed_ft` is treated
  as a model.
- Deliberately **does not interpolate** — it only cross-validates
  already-computed prediction values (RMSE, signed mean-error/bias, MAE,
  percent within tolerance), so it has no scipy/kriging/arcpy dependency,
  unlike the "conditional fit" `BuildGroundwaterSurfaceModel`/
  `EvaluateGroundwaterSurfaceModels` blockers in `EVALUATION_RESULTS.md`
  (which assumed the model outputs didn't exist yet). A missing prediction
  for one well is skipped from that model's stats only, not an error — model
  A being incomplete shouldn't block ranking model B.
- Rank 1 = lowest RMSE.

**ExportSurveyToCADGIS**
- Scoped to **CSV + optional GeoJSON only**. DWG/DXF/LandXML generation
  needs a template or external-library decision (per
  `EVALUATION_RESULTS.md`'s own blocker note) and is out of scope here —
  documented, not silently dropped.
- Reuses `import_rtk_survey.parse_rtk_csv()` directly; `RTKPoint.feature_code`
  already existed as a raw string with no consumer. The feature-code → layer
  mapping is a plain YAML dict (`{"MW": "MonitoringWells", ...}`), with an
  optional `"default"` key for the fallback bucket (`Miscellaneous` if
  unset). Points with a blank or unmapped code are routed to the fallback and
  reported via an `unmapped_feature_codes` WARNING, never silently dropped.
- CSV/GeoJSON coordinate convention: `x = Easting`, `y = Northing`,
  `z = Elevation_ft` — coordinates pass through the caller's CRS unprojected,
  matching the existing `export-geojson` tool's convention.
- **Path traversal (cold review, landed inline):** the layer-name → filename
  step originally used the YAML map's values (and, in `GenerateWellInspectionReports`
  below, the wells CSV's `WellID` values) unsanitized — a map entry of
  `{"EVIL": "../../etc/pwn"}` or a `WellID` of `../../evil` wrote outside
  `output_dir` entirely. Both tools now route the file stem through a
  `_sanitize_*` helper (`\\`/`/` → `_`, `.`/`..`/empty → a fixed fallback
  name) before constructing any path, emit a `WARNING` when sanitization
  changes the name, and — for `ExportSurveyToCADGIS` specifically — merge
  raw layer names that collide after sanitization instead of letting one
  silently overwrite the other.

**GenerateWellInspectionReports**
- Pure stdlib, **Markdown** output (same rationale as
  `GenerateMonitoringEventReport`, ADR-0028 — no PDF/Word template system
  exists yet, so PDF generation is out of scope; a Markdown report per well
  plus a site summary was chosen over blocking on a template-format decision).
  Photo-attachment workflow is likewise out of scope (undesigned, per the
  `EVALUATION_RESULTS.md` blocker).
- The `_load_csv`/`_md_table` helpers are small (~15 lines) private
  duplicates of the ones in `generate_event_report.py` rather than a shared
  module — with only two call sites, extracting a `markdown_utils` module
  would be a premature abstraction (rule of three not yet met).
- A well's "latest" inspection is the max by `InspectionDate` string
  (ISO dates sort lexically, so no date parsing needed). A well with zero
  inspection rows is flagged `wells_never_inspected` (WARNING) rather than
  silently reported as passing; a well whose latest condition isn't in
  `{GOOD, OK, PASS, SATISFACTORY}` is flagged `wells_need_attention`.
- **Duplicate `WellID` (cold review, landed inline):** two wells-CSV rows
  sharing a `WellID` originally overwrote the same `.md` file silently, with
  `build_well_inspection_reports()`'s return value still (incorrectly)
  claiming both were written. Now the second occurrence is skipped with a
  `duplicate_well_id` WARNING and the returned/counted file list matches what
  is actually on disk.

**GeneratePortfolioMetrics (cold-review addendum)**
- `missing_tools` is recomputed independently of `evaluate_readiness()`'s own
  pass/fail by design (see above), which a cold review flagged as a latent
  drift risk if `evaluate_readiness()` ever grows another failure path this
  function doesn't mirror. Added a defensive `portfolio_status_inconsistent`
  INFO record whenever `ready` and `(not missing)` disagree, so a future
  divergence is surfaced in the QA report instead of silently mis-stating a
  site's status.

---

## Consequences

### Positive

- Five more catalog tools shippable without arcpy, all reusing established
  seams (`QACollector`, `RunHistory`, `evaluate_readiness`,
  `import_rtk_survey.parse_rtk_csv`) — low architectural risk, full suite
  green (1134 passing: 41 tests from the initial batch + 11 more added after
  cold review), all five commands smoke-tested through the actual CLI (not
  just the core function) end-to-end with real fixtures.
- Cold review (envmon-spec-checker + pr-reviewer) ran on the branch:
  spec-checker PASS; pr-reviewer's first pass was REQUEST CHANGES (two path
  traversal bugs via unsanitized layer-name/WellID-to-filename construction,
  one silent-overwrite data-loss bug on duplicate `WellID`, plus two
  should-fix robustness gaps) — all landed inline with tests before opening
  the PR, per the findings recorded above.
- Closes three multi-year "conditional fit" gaps
  (`RTKControlCheckReport`/roadmap #15 boring-survey-drone list,
  `EvaluateGroundwaterSurfaceModels`/#13, `ExportSurveyToCADGIS`/#16) by
  descoping them to their headless-feasible core, rather than waiting on
  their originally-listed arcpy/CAD-library blockers.
- `GeneratePortfolioMetrics` gives PM-level visibility across sites without
  any new schema, immediately usable against every existing `run_history.csv`.

### Negative

- `ExportSurveyToCADGIS` produces no DWG/DXF/LandXML — teams needing native
  CAD import still need a manual conversion step until that follow-up ships.
- `GenerateWellInspectionReports` has no photo-attachment workflow; the
  Markdown report is text-only.
- `EvaluateGroundwaterSurfaceModels`' model ranking is unweighted RMSE only —
  it does not encode a hydrogeologist's subjective preference between models
  with similar RMSE (the same caveat `EVALUATION_RESULTS.md` flagged for the
  original candidate).
- `RTKControlCheckReport`'s all-points-must-pass gate has no size floor — a
  single noisy shot in a 50-point network fails the whole `overall_pass`
  exactly as it would in a 2-point network; `n_pass`/`n_fail` are exposed in
  the summary so a caller can apply their own percentage-based leniency if
  needed, but the tool does not do so itself.

## Alternatives considered

- **Joining `RTKControlCheckReport` against `RTKPoint`/`SurveyPoints_Raw`**
  instead of a flat CSV: rejected — it would couple a QA tool to the RTK
  import schema for no benefit, since a control check compares against
  *published* values that don't come from an RTK import at all.
- **Long/tidy format for `EvaluateGroundwaterSurfaceModels`**
  (`well_id, model_name, predicted_ft`): rejected in favor of wide format —
  matches how the data is actually assembled by hand and needs no model
  registry.
- **DWG export via an external library** for `ExportSurveyToCADGIS`: deferred;
  no library is vetted yet and CSV/GeoJSON already unblocks GIS-side
  consumption, which was the higher-value half of the original candidate.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0017: run-history CSV log](0017-run-history-csv-log.md)
- [ADR-0026: night-implementer batch 2026-06-27](0026-night-implementer-batch-2026-06-27.md)
- [ADR-0028: cloud-tools batch 2026-06-28](0028-cloud-tools-batch-2026-06-28.md)
- `docs/candidates/EVALUATION_RESULTS.md`
