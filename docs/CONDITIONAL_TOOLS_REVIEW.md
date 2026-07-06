# Conditional Tools Review: Architecture Decisions Needed

**Date:** 2026-06-25 (updated 2026-07-06, see issue #167)

8 high-value tools were originally reviewed here as conditional. Since then,
#3/#4/#5 shipped as fast-track tools, and #7/#8/#9 turned out — on review —
to be drone-raster/geotech-graphics work rather than kriging/EBK
geostatistical modeling; they've shipped too and their sections below are
removed (see ADR for the batch). Only **3** tools remain conditional under
the Phase 5 geostatistical gate: #1 RunFieldToGroundwaterModelPipeline, #2
BuildGroundwaterSurfaceModel, and #6 BuildAnalyticalConcentrationSurface —
the true kriging/EBK/surface-modeling items. They fit the hybrid harness
architecture but require design decisions before integration. This document
outlines blockers and integration paths for those three.

---

# 1. RunFieldToGroundwaterModelPipeline ⚠️ HIGH PRIORITY

**Evaluation:** Fits all three modes (local ✓ | CLI ✓✓ | AGOL ✓) but requires staged implementation.

## Current Blockers

### A. Upstream Tool Dependency
- Requires `ValidateGWModelInputs` tool (validation layer before interpolation)
- Requires `BuildGroundwaterElevationEvent` tool (normalizes water levels into model-ready format)
- **Both missing from roadmap** — need to add before RunFieldToGroundwaterModelPipeline

### B. Model QA Schema Not Designed
- Current roadmap lacks `GW_ModelInputPoints`, `GW_ModelExcludedPoints`, `GW_ModelQA`, `GW_ModelCrossValidation` tables
- Model ranking logic (which interpolation method won?) not yet documented
- Cross-validation metrics (RMSE, mean error, standardized residuals) need output table structure

### C. Kriging Dependencies
- Scipy, scikit-learn, or arcpy spatial analyst required (optional for IDW/TIN)
- Complex parameter tuning (semivariogram, transformation type, output types)
- Uncertainty surface generation differs by method (TIN: none, IDW: none, EBK: standard error, kriging: variance)

## Recommended Integration Path

**Stage 1 (Immediate):** TIN only
- Requires: survey points, site boundary
- No kriging/scipy dependencies
- Transparent triangulation
- Output: `GW_ModelInputPoints`, `GW_ModelContours_Draft`, `GW_ModelQA`

**Stage 2 (Near-term):** Add IDW
- Weighted inverse distance
- Adds distance decay parameter
- Same output structure as TIN

**Stage 3 (Medium-term):** Add EBK/Kriging
- Requires semivariogram, transformation, output types
- Generates `GW_ModelStandardErrorRaster` (uncertainty surface)
- More complex parameter tuning

**Stage 4 (Deferred):** Add trend surface + residuals
- Universal kriging (regional gradient + local deviations)
- Manual contour assist (hydrogeologist override)

## Architecture Decisions Needed

1. **Model output naming convention** — standardize raster names, contour feature class names
2. **Model ranking logic** — which interpolation method is "best"? (RMSE? User choice? Combination?)
3. **Hydro review workflow** — how does hydrologist approve/reject models? (table flag? manual edit?)
4. **Status marking** — all model outputs initially marked `DRAFT_REVIEW_REQUIRED`; only final approved maps leave `DRAFT` status
5. **Contour interval config** — per-site configuration (H281 uses 0.5 ft, ZT42 uses 1 ft)?

## Test Case for Design

**Site H281 (test case for GWE modeling):**
- Monitoring well network: 9 wells
- Event: 2026-Q2
- All wells measured (no DRY/NM/NS)
- Expected output:
  - TIN contours + uncertainty assessment
  - IDW contours
  - Model comparison table
  - Recommended method (per hydro judgment)
  - Draft map with all three models for review

---

# 2. BuildGroundwaterSurfaceModel ⚠️ HIGH PRIORITY

**Evaluation:** Fits all three modes (local ✓✓ | CLI ✓ | AGOL ✓) but design choices needed.

## Current Blockers

### A. Elevation Data Quality
- Requires working `ElevationHistory` table with approved elevations
- Requires well coordinate validation (ProcessLevelLoop + ValidateRTKSurvey must work first)
- Requires vertical datum alignment across all wells

### B. Model Ranking Subjectivity
- Geostatistical "best fit" is not objective (RMSE vs. uncertainty calibration vs. hydro judgment)
- Output status system needed: `Computed_GWE_Points` vs. `Draft_Interpolation` vs. `Draft_Contours` vs. `Final_Review`
- Separate outputs by review status

### C. Uncertainty Surface Output Format
- TIN: no uncertainty surface
- IDW: no uncertainty surface
- EBK/Kriging: standard error raster
- How to present uncertainty to user? (Raster + legend? Isotropic buffer?)

## Recommended Integration Path

**Start with:** TIN + IDW (deterministic, no uncertainty surface complexity)

**Then add:** EBK (empirical Bayesian kriging, automated semivariogram)

**Defer to Phase 2:** Manual contour assist, trend surface

## Architecture Decisions Needed

1. **Output status labeling** — what goes into final report? (only `APPROVED` or include `DRAFT` for context?)
2. **Uncertainty presentation** — how to show EBK standard error to stakeholder? (legend? separate raster? contours of uncertainty?)
3. **Well exclusion workflow** — user marks well "exclude from model" → regenerate → compare before/after
4. **Flow direction logic** — compute from contours? Fit plane? User-selected control wells?
5. **Boundary definition** — site boundary polygon required? Buffer around wells? User-drawn?

## Test Case for Design

**Site H281 (continuation from RunFieldToGroundwaterModelPipeline):**
- 9 wells with validated elevations
- Build TIN contours → compare against IDW
- Hydrogeologist reviews, approves one method
- Final contours marked `APPROVED` for report
- Flow direction arrow computed from approved contours

---

# 3. SurveyToWellElevationUpdate ⚠️ HIGH PRIORITY (Depends on #1 above)

✅ **SHIPPED** — `survey-to-well-elevation` (tool 8.5). Body kept for
historical design context; no longer conditional.

**Evaluation:** Fits all three modes (local ✓ | CLI ✓ | AGOL ✗) but depends on ProcessLevelLoop + ValidateRTKSurvey.

## Current Blockers

### A. Dependency Chain
- Requires `ProcessLevelLoop` ✓ (fast-track, implemented first)
- Requires `ValidateRTKSurvey` ✓ (fast-track, implemented first)
- Requires `UpdateWellElevationsFromLevelLoop` ✓ (fast-track, implemented first)
- **All prerequisites are fast-track, so this can be built immediately after Phase 1**

### B. Elevation History Management
- Must create elevation history records, not overwrite
- Must flag "approved" elevations as superseding prior values
- Must track source (ProcessLevelLoop run ID vs. RTK import)

### C. GWE Recalculation Trigger
- When well elevations change, which events should GWE be recalculated for?
- Current event only? All events at site? All events for well?
- Potential update cascade if not carefully scoped

## Recommended Integration Path

**Build after Phase 1** (ProcessLevelLoop + UpdateWellElevationsFromLevelLoop proven)

1. Import RTK or level-loop data
2. Validate survey quality (`ValidateRTKSurvey`)
3. Calculate adjusted elevations (`ProcessLevelLoop`)
4. Compare against current well elevations
5. Flag wells with changes > threshold (e.g., > 0.5 ft)
6. Create elevation history records (`UpdateWellElevationsFromLevelLoop`)
7. **Optional:** Recalculate GWE for selected event(s) if user approves

## Architecture Decisions Needed

1. **Scope of GWE recalculation** — which events? user choice? or all?
2. **Change threshold** — flag changes > 0.5 ft? configurable per site?
3. **Approval workflow** — who approves elevation supersession? (engineer, PM?)
4. **Label updates** — if GWE changes, refresh map labels? Or manual?

## Test Case for Design

**Site H281 (continuation):**
- Prior well elevations from 2023 RTK survey
- New 2026 level loop done for report
- 2 wells have elevation changes > 0.5 ft (post-construction settlement suspected)
- Elevation history created, changes flagged
- GWE recalculated for 2026-Q1 and Q2 events
- Contours regenerated, change documented in report

---

# 4. GenerateRegulatoryTables ⚠️ MEDIUM-HIGH PRIORITY

✅ **SHIPPED** — `generate-reg-tables`. Body kept for historical design
context; no longer conditional.

**Evaluation:** Fits all three modes (local ✓ | CLI ✓ | AGOL ✗) but nondetect rules + template system design needed.

## Current Blockers

### A. Nondetect Handling Rule Selection
Not a single correct answer; must be configured per analyte or matrix:
- `exclude_nondetects` — only detected values (biased high if nondetects are common)
- `use_half_rl` — use 0.5 × reporting limit
- `use_rl` — use reporting limit
- `use_zero` — use zero (generally avoid)
- `censored_model_placeholder` — future advanced method (Kaplan-Meier, etc.)

### B. Report Template System Design
Three options with tradeoffs:
1. **Python library (reportlab, pypdf2)** — reproducible, version-controlled, no Word dependency
2. **Word template + mail merge** — staff can edit templates easily, but file-dependent
3. **ArcGIS layout + export** — visual layout control, limited flexibility

### C. Output Format Choices
- Excel workbook (easy to edit, commonly used)
- Word document (for report appendix, harder to regenerate)
- PDF (static, not editable)
- All three? (requires all three generators)

## Recommended Integration Path

**Phase 1:** Excel output only
- Simplest implementation
- Reuses `Env_AnalyticalResults` table
- No template complexity

**Phase 2:** Add Word output (via template)

**Phase 3 (Optional):** Add PDF output

## Architecture Decisions Needed

1. **Nondetect rule selection** — per analyte in analyte dictionary? per event config? user prompt?
2. **Template format** — Word, Python library, or hybrid?
3. **Excel structure** — one sheet per analyte group? or all in one?
4. **Historical table generation** — include prior events? or current only?
5. **Exceedance highlighting** — red background? bold? conditional formatting?

## Recommended Config Structure

```yaml
analytical_tables:
  nondetect_rule: half_rl  # options: exclude, half_rl, use_rl, use_zero
  include_historical: true
  include_duplicates: true
  include_field_parameters: true
  output_format: xlsx  # options: xlsx, docx, pdf, all
  template_path: /path/to/templates/regulatory_table_template.docx
```

## Test Case for Design

**Site H281 (test with real data):**
- Groundwater results: 12 detected compounds, 8 nondetects (half-RL rule selected)
- Soil results: 3 metals detected, 2 below detection (exclude from table? or show as `<RL`?)
- Historical comparison: Q2 2025 vs Q2 2026
- Exceedance table: highlight 2 exceedances red
- Output: Excel workbook with 3 sheets (GW current, GW historical, Soil current)

---

# 5. EvaluateGroundwaterSurfaceModels ⚠️ MEDIUM PRIORITY

✅ **SHIPPED** — `evaluate-gw-models`. Body kept for historical design
context; no longer conditional.

**Evaluation:** Fits all three modes (local ✓ | CLI ✓ | AGOL ✗) but depends on BuildGroundwaterSurfaceModel.

## Current Blockers

### A. Model Output Registry Schema Not Designed
Needs to store and compare:
- `Model_TIN` (raster)
- `Model_IDW` (raster)
- `Model_EBK_Prediction` (raster)
- `Model_EBK_StandardError` (raster)
- `Model_TrendSurface` (raster)
- Cross-validation metrics per model

### B. Model Ranking Logic Subjective
- Mean error (RMSE): lower is better
- Mean standardized error: should be ~0 for kriging calibration
- RMS standardized error: should be ~1 for kriging calibration
- Percent within tolerance (e.g., `< 2 ft`): higher is better
- Hydrogeologist review flag: professional judgment trumps all

### C. Output Comparison Table Structure
Needs to show side-by-side comparison, but each model produces different outputs:
- All models produce prediction raster
- Only kriging produces standard error raster
- How to compare apples (TIN) to oranges (kriging)?

## Recommended Integration Path

**Build after BuildGroundwaterSurfaceModel complete**

Generate cross-validation metrics for each model, store in table:

| Model | RMSE | MeanError | MeanStdError | RMSStdError | PercentWithin | HydroReviewFlag |
|---|---|---|---|---|---|---|
| TIN | 1.2 | 0.05 | N/A | N/A | 87% | ACCEPTABLE |
| IDW | 1.1 | 0.02 | N/A | N/A | 89% | ACCEPTABLE |
| EBK | 1.0 | 0.01 | 0.1 | 0.95 | 91% | PREFERRED |

## Architecture Decisions Needed

1. **Cross-validation method** — leave-one-out? k-fold?
2. **Tolerance threshold** — what's "within tolerance"? (configurable per site?)
3. **Ranking weights** — if RMSE says IDW is best but hydro says EBK, which wins? (hydro always wins)
4. **Comparison visualization** — separate map for each model? or overlay?
5. **Storage** — store comparison table in GDB? AGOL dashboard table?

## Test Case for Design

**Site H281 (continuation):**
- TIN, IDW, EBK models generated for 2026-Q2 event
- Cross-validation: EBK RMSE = 1.0 ft (best), IDW = 1.1 ft, TIN = 1.2 ft
- Hydro review: "EBK is good, but I prefer TIN for transparency. Mark TIN as approved."
- Output: Comparison table shows EBK numerically best, but TIN marked as hydrologist-selected final

---

# 6. BuildAnalyticalConcentrationSurface ⚠️ MEDIUM-HIGH PRIORITY

**Evaluation:** Fits all three modes (local ✓✓ | CLI ✓ | AGOL ✓) but nondetect + plume boundary design needed.

## Current Blockers

### A. Nondetect Handling Rule Complexity
Same as GenerateRegulatoryTables (see #4), but for concentration mapping:
- `exclude_nondetects` — only detected values
- `use_half_rl` — use half reporting limit
- `use_rl` — use reporting limit
- Impact on plume size: use_half_rl produces smaller plume; use_rl produces larger

### B. Plume Boundary Logic
- How is plume extent defined? (e.g., concentration > screening level?)
- Does boundary respect site property line? (user-drawn polygon?)
- Does it buffer wells? (don't contour beyond `n` feet from data?)

### C. Threshold vs. Continuous Interpolation
- Geostatistical surface of concentration (continuous)
- vs. Plume boundary polygon (discrete: inside/outside threshold)
- Exceedance probability raster (probability that concentration > threshold)

### D. Analyte Selection and Detection Limits
- Only detected values used? (exclude nondetects entirely)
- Different analytes have different RLs
- How to handle mixed analytes in one plume map? (highest RL? or analyte-specific maps?)

## Recommended Integration Path

**Phase 1:** Deterministic plume
- Threshold = screening level
- Input = detected values only
- Output = plume polygon (contour polygon clipped to site boundary)

**Phase 2:** Add exceedance probability raster (requires kriging + threshold interpolation)

**Phase 3:** Add uncertainty surface (requires kriging)

## Architecture Decisions Needed

1. **Nondetect rule** — per analyte? per matrix? user choice?
2. **Plume boundary** — site property line? buffer from wells? both?
3. **Threshold definition** — screening level? site-specific cleanup level? user-entered?
4. **Output status** — all plumes start as `DRAFT_REVIEW_REQUIRED`?
5. **Multi-analyte plumes** — separate map per analyte? or combined?

## Test Case for Design

**Site ZT42 (Groundwater quality example):**
- Benzene detected in 4 wells: 50, 120, 8, 15 µg/L
- Montana RBSL for benzene = 5 µg/L
- 3 wells exceed screening level
- Nondetect rule = exclude (only use 50, 120, 8, 15)
- Plume boundary polygon generated from IDW contours
- Output: Draft plume map, approved by environmental engineer

---

# Summary Decision Matrix

| Tool | Priority | Primary Blocker | Test Case Site | Est. Design Time | Est. Build Time |
|---|---|---|---|---|---|
| RunFieldToGroundwaterModelPipeline | HIGH | Model QA schema | H281 | 2 weeks | 4-6 weeks (TIN), +4 weeks (IDW), +6 weeks (kriging) |
| BuildGroundwaterSurfaceModel | HIGH | Uncertainty output format | H281 | 2 weeks | 4 weeks (TIN/IDW), +6 weeks (kriging) |
| SurveyToWellElevationUpdate | HIGH | ✅ SHIPPED (`survey-to-well-elevation`) | H281 | — | — |
| GenerateRegulatoryTables | MED-HIGH | ✅ SHIPPED (`generate-reg-tables`) | H281, ZT42 | — | — |
| EvaluateGroundwaterSurfaceModels | MEDIUM | ✅ SHIPPED (`evaluate-gw-models`) | H281 | — | — |
| BuildAnalyticalConcentrationSurface | MED-HIGH | Nondetect + plume boundary | ZT42 | 2 weeks | 3 weeks (deterministic), +4 weeks (kriging) |
| DEMConditioningPipeline | MEDIUM | ✅ SHIPPED (`condition-dem`) | Drone project | — | — |
| CompareDroneSurfaces | MEDIUM | ✅ SHIPPED (`compare-drone-surfaces`) | Landfill project | — | — |
| GenerateSubsurfaceProfileFromBorings | MEDIUM | ✅ SHIPPED (`generate-subsurface-profile`) | H281 | — | — |

---

# Recommended Next Steps

## Immediate (Before Building Conditional Tools)

1. **Define model QA schema** — table structure for `GW_ModelInputPoints`, `GW_ModelQA`, cross-validation metrics
2. **Document model status system** — when do outputs go from `DRAFT` to `APPROVED`?
3. **Design elevation history workflow** — who approves elevation supersession? what's the audit trail?
4. **Specify nondetect rules** — per analyte config, defaults, validation

## Design Sessions (2-3 weeks)

- Geostatistical modeling (RunFieldToGroundwaterModelPipeline, BuildGroundwaterSurfaceModel)
- Nondetect handling and concentration surfaces (BuildAnalyticalConcentrationSurface) —
  GenerateRegulatoryTables shipped, so this session no longer covers it

## Implementation Sequencing

**Phase 1-2 (Concurrent with fast-track tools):**
- GWE modeling design (RunFieldToGroundwaterModelPipeline, BuildGroundwaterSurfaceModel)
- Start with TIN only (minimal dependencies)

**Phase 2-3 (After fast-track tools stable):**
- Concentration surfaces + nondetect rules

**Phase 3+ (Advanced):**
- EBK/kriging, uncertainty surfaces

---

**Next:** Choose which of the 3 remaining conditional tools to prioritize and assign design owners.
