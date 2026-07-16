# Geostat slice 2 — EBK stage, uncertainty raster, continuous concentration surface, nondetect policy

**Date:** 2026-07-16
**Gate:** Phase 5, reopened 2026-07-15; ADR-0085 (Accepted) slice map, slice 2.
**Prereq satisfied:** ADR-0077 doc-verification of every new arcpy call was
performed in this session (see table below) — the ADR-0085 exit condition for
slice 2.

## Scope (exactly the ADR-0085 slice-2 list)

1. **EBK stage** for GW surfaces in `run-gw-model-pipeline` /
   `build_groundwater_contours`, plus the **standard-error uncertainty
   raster** (ADR-0085 decision 6: companion raster, not embedded in the
   vector contours).
2. **Continuous concentration surface** (IDW/EBK) for
   `BuildAnalyticalConcentrationSurface` — new CLI verb
   `build-conc-surface`, one analyte per surface (decision 5).
3. **Nondetect policy config** (decision 4): `exclude | half_rl | use_rl |
   use_zero`, consumed only by the concentration surface — built now
   because slice 2 is the deliverable that needs a numeric substitution.

Out of scope: probability/quantile EBK outputs, multi-analyte merged
surfaces, kriging variants beyond EBK, figure-spec integration.

## ADR-0077 verification (this session, 2026-07-16)

All pages fetched from the current Esri Pro tool reference
(pro.arcgis.com 301s to doc.esri.com; content identical). All current,
none deprecated at Pro 3.x:

| Call | Page | Notes used |
|---|---|---|
| `arcpy.ga.EmpiricalBayesianKriging(in_features, z_field, {out_ga_layer}, {out_raster}, {cell_size}, ..., output_type)` | geostatistical-analyst/empirical-bayesian-kriging | `output_type` enum incl. `PREDICTION` (default), `PREDICTION_STANDARD_ERROR`; requires Geostatistical Analyst |
| `arcpy.ga.CrossValidation(in_geostat_layer, {out_point_feature_class})` | geostatistical-analyst/cross-validation | LOO semantics; `CrossValidationResult` (count, mean_error, root_mean_square, …); out points carry GA-Layer-To-Points fields |
| GA Layer To Points output fields | geostatistical-analyst/ga-layer-to-points | `Source_ID`, `Included`, `Predicted`, `Error`, `StdError`, … (`Source_ID` = OID of source feature) |
| `arcpy.ga.GALayerToRasters(in_geostat_layer, out_raster, {output_type}, …, {cell_size}, …)` | geostatistical-analyst/ga-layer-to-rasters | `output_type` incl. `PREDICTION_STANDARD_ERROR` |
| `arcpy.management.Clip(in_raster, rectangle, out_raster, {in_template_dataset}, {nodata_value}, {clipping_geometry}, {maintain_clipping_extent})` | data-management/clip | raster clip; `"ClippingGeometry"`; no extension required |
| `arcpy.sa.Idw(in_point_features, z_field, {cell_size}, …)` | spatial-analyst/idw | re-verified this session (concentration IDW reuses it) |
| `arcpy.sa.Contour(in_raster, out_polyline_features, contour_interval, …)` | spatial-analyst/contour | re-verified; EBK contour path routes through it (see below) |
| `arcpy.CheckExtension("GeoStats")` | arcpy/functions/checkextension | `GeoStats` is the Geostatistical Analyst product code |
| `Raster.save(name)` / `Raster.maximum` | arcpy/classes/raster-object | persists a temporary raster; `maximum` read-only property (all-NoData value undocumented — code treats None and a raise identically) |
| `arcpy.management.CopyRaster(in_raster, out_rasterdataset, …)` | data-management/copy-raster | scratch → GDB publish; no extension required |
| `arcpy.management.GetRasterProperties(in_raster, "ALLNODATA")` | data-management/get-raster-properties | direct all-NoData test for the clipped prediction (#241 review); `getOutput(0)` == "1" → confirmed empty |

## Design decisions

### D1. EBK contours route through the prediction raster + `sa.Contour`

`GALayerToContour` exists but classifies by breaks/class-count — it has no
fixed contour-interval parameter, so it cannot honor the pipeline's
`contour_interval` contract, and its output value field is undocumented.
Instead: `EmpiricalBayesianKriging(pt_fc, "GWE", out_ga_layer=lyr,
out_raster=pred)` then the **existing, shipped** `sa.Contour` →
`Env_GWContours_Draft` write path, unchanged. Consequence: the EBK stage
requires **GeoStats + Spatial** (IDW already requires Spatial, so this adds
no new license class to a shop running the pipeline). License-degrade stays
the shipped pattern: missing license → `SEV_ERROR` + skip.

### D2. EBK ranking uses `ga.CrossValidation`, merged into the shared rows

Manual per-fold refits (the TIN/IDW predictor) would mean N full EBK runs;
`ga.CrossValidation` IS leave-one-out for the fitted layer, in one call.
Per-well predictions are read from its `out_point_feature_class`
(`Source_ID` → LocationID via the scratch FC's captured OIDs; rows with
`Included <> 'Yes'` or null `Predicted` are treated as skipped cells) and
merged into the same `ObservationRow` list the manual LOO produces, so
`evaluate_gw_models` ranks all methods on identical wells with one code
path. Headless merge glue (`merge_method_predictions`) is unit-tested; the
CV read is an arcpy seam. LOO minimum (≥ 4 points) applies to EBK exactly
as to TIN/IDW.

### D3. Uncertainty raster: `Draft_`-prefixed GDB raster + registry row

Rasters cannot carry a `ReviewStatus` field, so the DRAFT convention maps
to: name prefix `Draft_`, a registry row with `ReviewStatus='DRAFT'`, and
a QA INFO. New additive table **`Env_SurfaceRegistry`** (schema 2.4 → 2.5)
serves both slice-2 tools:

```
Env_SurfaceRegistry (new, additive):
  SiteID (TEXT 32)         EventDate (DATE)
  SurfaceKind (TEXT 16)    -- 'GWE' | 'CONC'
  AnalyteFilter (TEXT 128) -- '' for GWE surfaces
  Method (TEXT 32)         -- 'IDW' | 'EBK'
  RasterType (TEXT 32)     -- 'PREDICTION' | 'STD_ERROR'
  NondetectRule (TEXT 16)  -- '' for GWE surfaces
  Units (TEXT 16)          -- declared surface unit ('ug/L' CONC, 'ft' GWE)
  RasterPath (TEXT 256)    ReviewStatus (TEXT 16)
  CreatedAt (DATE)         Notes (TEXT 256)
```

Replace-on-write key: (SiteID, EventDate, SurfaceKind, AnalyteFilter,
Method, RasterType) — mirrors the contour-row replace semantics. No RunID
column: rasters are replaced in place per key, and the run registry already
records which methods a run executed (YAGNI on a join table).

Raster naming (#241 review — `slug()` alone is lossy, so distinct
identities could collide onto one dataset): a bounded readable prefix plus
a stable sha1-8 of the ORIGINAL site/analyte identity (`surface_tag`),
e.g. `Draft_GWE_<tag>_<yyyymmdd>_EBK_SE` /
`Draft_Conc_<tag>_<yyyymmdd>_<method>[_SE]`. Scratch names carry the same
tag.

### D4. Nondetect policy (`exclude | half_rl | use_rl | use_zero`)

Applied at point-collection time in the new headless
`concentration_surface.py`:

- detected result → `ResultNumeric`;
- nondetect + `exclude` → dropped;
- nondetect + `half_rl` / `use_rl` → `ReportingLimit` (× 0.5 for
  `half_rl`), falling back to `DetectionLimit` when RL is null; if both
  are null the row is excluded with a `SEV_WARNING`;
- nondetect + `use_zero` → 0.0.

Input path mirrors `draft-plume-boundary` (results CSV + coords CSV,
canonical-read first per ADR-0075 so fraction pairs/QC rows never seed a
surface). Rows are scoped to the requested SiteID + SampleDate(==event) +
optional Matrix before aggregation — a multi-site/multi-event export must
never leak a foreign value into the surface (#241 review). Every value
(and the RL/DL a rule substitutes) is normalized into a **declared surface
unit** (default `ug/L`, `--unit` to override) via the ADR-0022 registry
(`core/common/units.py`); unknown or cross-dimension units warn and drop
(#241 review — mixed mg/L / ug/L data is routine). Per-well aggregation:
**max** normalized value (conservative for plume mapping); wells lacking
coordinates warn and drop, matching the plume tool. The rule and the unit
are recorded on the registry row and in the QA log.
`ExceedsScreeningLevel` / the plume hull are untouched — decision 4 scoped
the policy to the continuous surface only.

### D5. Concentration surface tool shape

`build-conc-surface` (CLI, `Runtime.LOCAL`, the draft-plume-boundary
hybrid: headless point collection + `--dry-run` always work, the GDB
stage is `_guard`ed) + `BuildAnalyticalConcentrationSurface` .pyt Tool +
capabilities + `_REGISTRY_SEED`, the standard four surfaces. Headless
compute (points + policy) is unit-tested; the interpolate/clip/write seam
is `# pragma: no cover`. Boundary clip contract copies the plume tool:
a requested `--boundary-fc` that is missing, has no usable geometry, or
clips to nothing (`GetRasterProperties(ALLNODATA) == '1'` on the clipped
prediction — a direct test, with an inspection failure reported as its
own QA category, #241 review) skips with a QA ERROR **before** replacing
any existing raster/registry row.
Minimum points: 4 (same QA-error-and-skip degrade as contours). IDW needs
Spatial; EBK needs GeoStats (management.Clip needs no extension). EBK
also writes the `_SE` standard-error companion raster (D3); IDW has no
error surface — none is fabricated.

### D6. Pipeline surface: EBK is opt-in, not default

`PIPELINE_METHODS` gains `"EBK"` as the validation universe, and a
separate `DEFAULT_PIPELINE_METHODS = ("TIN", "IDW")` is the function
default (#241 review) — so programmatic callers with no methods argument
never silently consume a GeoStats license. Opt-in is via the .pyt
multivalue methods filter (the CLI pipeline verb stays guard→redirect
with no methods flag, unchanged from slice 1). EBK's CV points are
accepted only when `Included` normalizes to exactly `yes` — Esri
documents the field's other values as diagnostic strings, not `No`
(#241 review).

## Deliverables checklist

- [ ] `groundwater_contours.py`: EBK branch (D1), `Draft_` SE raster +
      registry write (D3), `"EBK"` in `METHODS`, license map entry.
- [ ] `gw_model_pipeline.py`: `"EBK"` in `PIPELINE_METHODS`, CV-merge glue
      (D2, headless) + `ebk_loo_predictions` seam, license checkout map.
- [ ] `concentration_surface.py` (new): nondetect policy + point collection
      (headless, tested) + interpolate/clip/write seam (D4, D5).
- [ ] `gdb_schema.py` / `upgrade_schema.py`: `Env_SurfaceRegistry`,
      `SCHEMA_VERSION = "2.5"`; drift-guard tests updated (41 tables).
- [ ] Four-surface registration for `build-conc-surface`; `--methods`
      accepts EBK on the pipeline verb.
- [ ] Headless tests: policy rules (all 4 + fallbacks), point collection,
      CV-merge, registry-row shaping, CLI smoke (help + guard).
- [ ] Decision log + batch ADR; suite green; envmon-spec-checker +
      pr-reviewer pass.
- [ ] LOCAL smoke in ArcGIS Pro (user's machine) — checklist item for the
      PR, not automatable here.
