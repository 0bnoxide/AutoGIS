# ADR-0086: Phase-5 slice 2 — EBK stage, uncertainty raster, concentration surface, nondetect policy

**Status:** Proposed

**Date:** 2026-07-16

**Addresses:** ADR-0085 slice map (slice 2), Phase-5 gate (CLAUDE.md),
`docs/superpowers/specs/2026-07-16-geostat-slice2-design.md`

## Context

ADR-0085 (Accepted 2026-07-16) unblocked the Phase-5 geostatistical group
and shipped slice 1 (PR #240): TIN/IDW pipeline, GW_ModelRun registry,
plume boundary clip. It deferred exactly three items to slice 2, each
gated on its own spec plus an ADR-0077 doc-verification pass over the
Geostatistical Analyst arcpy calls: the EBK/kriging stage, the
standard-error uncertainty raster (decision 6), the continuous
concentration surface, and its nondetect-policy prerequisite (decision 4).
This ADR records the slice-2 batch as implemented. The ADR-0077 pass was
performed in the implementing session (8 tool pages; table in the spec).

## Decision

1. **EBK stage** — `"EBK"` joins `METHODS`/`PIPELINE_METHODS`. Contours
   route EBK's prediction raster through the existing `sa.Contour` path
   (interval contract preserved; licenses: GeoStats + Spatial, degrading
   to QA-ERROR skip like every other method). Ranking uses one
   `arcpy.ga.CrossValidation` call (LOO for the fitted layer) merged into
   the shared `ObservationRow` list by headless, tested glue — all methods
   rank on identical wells via `evaluate_gw_models`. EBK is opt-in; the
   pipeline default stays `TIN,IDW`.
2. **Uncertainty presentation (closes ADR-0085 decision 6)** — EBK writes
   a `PREDICTION_STANDARD_ERROR` companion raster via
   `ga.GALayerToRasters`. DRAFT convention for rasters: `Draft_` name
   prefix + a row in the new **`Env_SurfaceRegistry`** table
   (ReviewStatus='DRAFT') + QA INFO. No uncertainty is fabricated for
   TIN/IDW.
3. **Continuous concentration surface** — new `build-conc-surface` CLI /
   `BuildAnalyticalConcentrationSurface` .pyt tool (four-surface
   registration): per-analyte IDW or EBK raster from canonical-read
   results, optional site-boundary clip with the plume tool's
   validate-before-replace contract (PR #240 review lesson), rasters +
   registry rows as in (2).
4. **Nondetect policy (closes ADR-0085 decision 4)** —
   `exclude | half_rl | use_rl | use_zero`, applied at point collection in
   headless `concentration_surface.py`; RL falls back to DetectionLimit,
   both-null rows are excluded with a warning. Scoped to the concentration
   surface only; `ExceedsScreeningLevel`/plume hull untouched.
5. **Schema 2.4 → 2.5 (additive)** — `Env_SurfaceRegistry` (41 tables);
   replace-on-write key (SiteID, EventDate, SurfaceKind, AnalyteFilter,
   Method, RasterType); no RunID column (GW_ModelRun already records
   execution; rasters replace in place).

## Consequences

### Positive

- The Phase-5 gated group (3 tools) is now fully implemented across
  slices 1+2; all six ADR-0085 blocking decisions are resolved.
- No new Python dependencies; all arcpy additions doc-verified current at
  Pro 3.x in the implementing session (ADR-0077 satisfied); arcpy-free
  core/adapters invariant preserved (headless logic unit-tested, seams
  `# pragma: no cover`).
- Uncertainty and concentration rasters are first-class, registered,
  DRAFT-labeled products rather than loose files.

### Negative

- EBK contouring requires two licenses (GeoStats + Spatial); shops without
  Spatial cannot use the EBK contour stage (see decision log for the
  GALayerToContour fallback path).
- EBK's CrossValidation is LOO for EBK's own submodel scheme, not
  literally the manual N-1 folds used for TIN/IDW — close but not
  fold-identical; acceptable for a ranking whose output is explicitly a
  suggestion (ADR-0085 decision 3).
- LOCAL ArcGIS Pro smoke testing cannot run in this environment and
  remains a user checklist item before the group is declared production.

## Alternatives considered

1. **GALayerToContour for EBK contours** — rejected: no contour-interval
   parameter, undocumented output field; would fork the contour-write
   path. (Decision log has the revisit trigger.)
2. **Per-fold EBK refits for ranking** — rejected: N× slower for the same
   statistic; CrossValidation is the purpose-built call.
3. **Separate GWE/CONC registry tables or a RunID join column** —
   rejected: duplicate schema for naming purity (ADR-0075 precedent);
   GW_ModelRun already records execution.
4. **Building the nondetect policy into apply_screening** — rejected: the
   exceedance flag's "nondetect never exceeds" rule is regulatory display
   logic; coupling interpolation substitution to it would change shipped
   behavior slice 2 has no mandate to touch.

## Related decisions

- [ADR-0085](0085-phase5-geostatistical-architecture-review.md) — the
  architecture review this slice completes; its decisions 4 and 6 are
  closed here.
- [ADR-0077](0077-arcpy-api-currency-policy.md) — doc-verification pass
  performed in the implementing session (spec has the citation table).
- [ADR-0075](0075-canonical-schema-expansion-step1.md) — additive-schema
  and no-duplicate-table precedent for Env_SurfaceRegistry.
- [ADR-0002](0002-arcpy-free-core-invariant.md) — preserved.
- `docs/superpowers/specs/2026-07-16-geostat-slice2-design.md` — spec +
  ADR-0077 citation table.
- `docs/adr/logs/2026-07-16-agent-decisions-geostat-slice2.md` — judgment
  calls.
