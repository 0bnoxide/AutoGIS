# Phase-5 geostatistical tools — slice-1 design

**Date:** 2026-07-16
**Status:** Implemented this session
**Parents:** ADR-0085 (Accepted — architecture review, resolves the 6 shared
blockers), `docs/CONDITIONAL_TOOLS_REVIEW.md`,
`docs/superpowers/specs/2026-06-28-geostatistical-conditional-tools-design.md`,
`docs/HANDOFF-2026-07-15-geostat.md`.

## Scope

Slice 1 of the reopened Phase-5 gate: TIN/IDW only. EBK/kriging, uncertainty
surfaces, and the nondetect substitution policy are slice 2 (ADR-0085
decisions 4 and 6). Maps the 3 gated tool names to deliverables:

| Gated tool name | Slice-1 deliverable |
|---|---|
| `RunFieldToGroundwaterModelPipeline` | `run-gw-model-pipeline` (LOCAL): per-method draft contours via existing `build_groundwater_contours`, leave-one-out cross-validation feeding existing `evaluate_gw_models`, persisted `GW_ModelRun` + `GW_ModelCrossValidation` rows (ReviewStatus=DRAFT). |
| `BuildGroundwaterSurfaceModel` | The same pipeline invoked with a single method, plus the hydro-approval verb `approve-gw-model` (sets `GW_ModelRun.ApprovedModel` + `ReviewStatus=APPROVED`). No separate tool — ADR-0085 decision 1/3. |
| `BuildAnalyticalConcentrationSurface` | `draft-plume-boundary --boundary-fc`: site-boundary clipping of the existing hull polygon in the GDB write seam. Continuous surface deferred to slice 2. |

## What already exists (reuse — no new abstraction)

- `groundwater_contours.build_groundwater_contours` — TIN/IDW/NN draft
  contours, license degradation, `Env_GWContourPoints` persistence,
  DRAFT convention. Called per method by the pipeline, unchanged.
- `evaluate_gw_models.evaluate_gw_models` — headless RMSE/MAE/bias/tolerance
  ranking over `ObservationRow`s. Consumed as-is; the pipeline builds its
  observation rows in memory (no intermediate CSV required, though one can be
  written for audit).
- `gdb_schema.create_or_update_gdb_schema` / `upgrade_schema` — additive
  table creation; the two new tables ride the existing mechanism.
- `capabilities.py` guard-then-redirect LOCAL pattern; `.pyt` Tool class
  pattern (`GroundwaterContours` is the template).

## What is genuinely new

### 1. Schema (additive, `SCHEMA_VERSION` 2.3 → 2.4)

`GW_ModelRun` and `GW_ModelCrossValidation` per the ADR-0085 sketch, plus
`GW_ModelRun.ExecutedMethods` (PR #240 review amendment, recorded in the
ADR): `Methods` is what was requested, `ExecutedMethods` is what actually
produced a surface — approval validates against the latter, so a model with
no CV rows (3-point runs) stays approvable. Input/excluded points stay in
`Env_GWContourPoints` (no new point tables).

### 2. `core/envmon/gw_model_pipeline.py`

Headless (unit-tested):
- `make_run_id(site_id, event_date, now)` — deterministic run id.
- `loo_observation_rows(points, predict)` — leave-one-out glue: for each
  input point, call `predict(method, remaining_points, held_out_point)` per
  method and shape the results into `evaluate_gw_models.ObservationRow`s.
  A predictor returning `None` (e.g. held-out point outside the TIN hull of
  the remaining points) is a skipped cell, matching `evaluate_gw_models`'
  blank-cell contract.
- `build_run_records(...)` — shape `ModelStats` into `GW_ModelRun` /
  `GW_ModelCrossValidation` row dicts (ReviewStatus=DRAFT, ApprovedModel
  empty until a hydrogeologist sets it).

LOCAL seam (`# pragma: no cover`, arcpy):
- `_arcpy_loo_predictor` — TIN: `CreateTin` from the N−1 points +
  `AddSurfaceInformation` Z at the held-out point (3D Analyst); IDW:
  `arcpy.sa.Idw` raster from the N−1 points + `GetCellValue` at the held-out
  point (Spatial Analyst). Same `CheckExtension` degradation as
  `build_groundwater_contours`.
- `run_field_to_groundwater_model_pipeline(gdb, site_id, event_date, qa,
  methods, ...)` — collect points (reuses `collect_contour_points`), draft
  contours per method (reuses `build_groundwater_contours`), LOO
  cross-validate, rank, write registry rows.
- `approve_gw_model(gdb, run_id, model_name, reviewer)` — the decision-3
  approval verb; validates the run exists and the model was in the run.

Cross-validation method: leave-one-out (review doc decision list #1).
Chosen over k-fold because site well networks are small (H281 test case:
9 wells) — LOO is deterministic, parameter-free, and k-fold at n≈9 is noise.

### 3. Plume boundary clip

`write_plume_draft_to_gdb(..., boundary_fc=None)`: read the site-boundary
polygon(s) via `SearchCursor SHAPE@`, union, `Geometry.intersect(hull, 4)`
before insert. CLI `--boundary-fc` (valid only with `--gdb`). The headless
hull math is untouched.

### 4. Wiring

- CLI: `run-gw-model-pipeline` (guard + redirect to `.pyt`, like
  `gw-contours`); `approve-gw-model` (guard + direct field edit, like
  `manage-callout-overrides`).
- `capabilities.TOOLS`: both LOCAL. `TOOL_REGISTRY`: entries under the
  roadmap names above.
- `.pyt`: `RunGWModelPipeline` Tool class (multiValue method parameter —
  single method selection is the `BuildGroundwaterSurfaceModel` mode).

## arcpy calls (ADR-0077)

New calls (`AddSurfaceInformation`, `GetCellValue`, `Geometry.intersect`) and
reused ones (`CreateTin`, `Idw`) doc-verified against pro.arcgis.com in this
session; citations in the PR body. Compliance floor ArcGIS Pro 3.5.

## Out of scope (slice 2 — needs its own spec + ADR-0077 pass)

EBK/kriging (Geostatistical Analyst), standard-error uncertainty raster,
continuous concentration surface, nondetect substitution config,
flow-direction implementation consolidation (flagged in ADR-0085).
