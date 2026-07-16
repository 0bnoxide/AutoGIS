# Agent decisions — geostat slice 2 (2026-07-16)

Judgment calls made autonomously while implementing
`docs/superpowers/specs/2026-07-16-geostat-slice2-design.md` (ADR-0085
slice 2). Supplement to ADR-0086, not a substitute.

## EBK contours via prediction raster + sa.Contour, not GALayerToContour
**Decision:** The EBK stage feeds its prediction raster through the same
`arcpy.sa.Contour` path IDW already uses, instead of
`arcpy.ga.GALayerToContour`.
**Reasoning:** GALayerToContour classifies by class count/breaks — it has
no contour-interval parameter, so it cannot honor the pipeline's
`contour_interval` contract, and its output value field is undocumented.
Routing through sa.Contour keeps the downstream contour-write path
byte-identical for all methods. Cost: EBK needs Spatial Analyst in
addition to Geostatistical Analyst — no new license class for a shop
already running the IDW stage.
**Revisit if:** a site needs EBK contours without any Spatial Analyst
seat — then GALayerToContour with MANUAL breaks derived from the interval.

## EBK ranks via ga.CrossValidation, not N per-fold refits
**Decision:** EBK's leave-one-out predictions come from one
`arcpy.ga.CrossValidation` call (which IS LOO for the fitted layer),
joined back to wells via a LocID field on the scratch FC; TIN/IDW keep
the manual per-fold predictor.
**Reasoning:** N full EBK refits per ranking would be the slowest possible
implementation of the same statistic. The merge happens in headless,
unit-tested glue (`merge_method_predictions`) so every method still ranks
on identical wells through `evaluate_gw_models`. Wells CrossValidation
excludes are skipped cells — the same contract as a None from the manual
predictor.
**Revisit if:** fold-exact parity with the manual predictor ever matters
more than runtime (CrossValidation refits submodels per EBK's own scheme,
not literally our N-1 folds).

## One registry table (Env_SurfaceRegistry) for GWE and CONC rasters
**Decision:** A single additive table registers both the EBK standard-error
raster and the concentration surfaces, keyed by (SiteID, EventDate,
SurfaceKind, AnalyteFilter, Method, RasterType); no RunID column.
**Reasoning:** Rasters are replaced in place per key (same semantics as the
draft contour rows), and GW_ModelRun already records what a run executed —
a RunID join column would duplicate that for no consumer. Two parallel
kind-specific tables would be the naming-purity trap ADR-0075 warns about.
**Revisit if:** slice-3 needs per-run raster lineage — add RunID additively
then.

## Nondetect limit fallback: ReportingLimit, then DetectionLimit
**Decision:** `half_rl`/`use_rl` substitute from ReportingLimit and fall
back to DetectionLimit when RL is null; both null → row excluded with a
SEV_WARNING (never a fabricated value).
**Reasoning:** The rule names say RL, but real EDDs frequently carry only a
DL on nondetect rows; excluding those wells silently would bias the surface
low exactly where data is sparse. Excluding when both limits are missing is
the only honest option.
**Revisit if:** a regulator requires strict-RL-only substitution — make the
fallback a flag.

## Per-well aggregation: max concentration
**Decision:** One point per well per analyte, using the MAX value across
the well's canonical rows.
**Reasoning:** Conservative (never understates the plume), deterministic,
and matches how exceedance mapping treats a well ("any exceedance
qualifies"). Mean/latest would need tie-break policy for depth intervals
and duplicate samples that slice 2 has no requirement for.
**Revisit if:** depth-discrete surfaces are requested (then aggregation
becomes per-interval, not per-well).
