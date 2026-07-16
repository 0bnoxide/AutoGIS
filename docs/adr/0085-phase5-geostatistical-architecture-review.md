# ADR-0085: Phase-5 geostatistical conditional tools — architecture review

**Status:** Accepted (2026-07-16 — user merged the Proposed ADR in PR #239
without change requests and instructed "continue geostat development"; treated
as the plain-text direction sign-off required by
`docs/HANDOFF-2026-07-15-geostat.md`)

**Date:** 2026-07-15

**Addresses:** Phase 5 gate (CLAUDE.md), issue #167 (gate scope), `docs/CONDITIONAL_TOOLS_REVIEW.md`,
`docs/superpowers/specs/2026-06-28-geostatistical-conditional-tools-design.md`

**Scope:** The 3 tools still gated behind Phase 5 —
`RunFieldToGroundwaterModelPipeline`, `BuildGroundwaterSurfaceModel`,
`BuildAnalyticalConcentrationSurface`. Per the design stub's exit criteria,
this ADR is the required architecture review; **no per-tool spec or code
follows until this is Accepted.**

## Context

The user reopened the Phase-5 gate on 2026-07-15
(`docs/HANDOFF-2026-07-15-geostat.md`). Both source docs agree the group is
blocked on 6 shared decisions (execution-mode split, model QA/registry
schema, ranking/approval workflow, nondetect policy, plume boundary rules,
uncertainty presentation) and require an ADR before any per-tool spec. The
review doc and design stub are dated 2026-06-25/06-28; substantial adjacent
infrastructure has shipped since and changes the shape of what's actually
missing. This ADR runs the required reuse inventory and resolves the 6
decisions for a **slice-1** scope, deferring EBK/kriging to slice 2.

## Reuse inventory (findings)

Read: `autogis/core/envmon/{groundwater_contours,evaluate_gw_models,
draft_plume_boundary,estimate_gw_flow_direction,gdb_schema}.py`,
`autogis/core/envmon/regulatory_table_builder.py`, `autogis/core/envmon/
apply_screening.py`, `autogis/runtime/capabilities.py`, `pyproject.toml`.

- **`groundwater_contours.build_groundwater_contours`** already implements
  TIN/IDW/NaturalNeighbor interpolation, LOCAL/arcpy, with the license-degrade
  pattern (`CheckExtension("3D"|"Spatial") != "Available"` → `SEV_ERROR` +
  skip, never crash) and writes `Env_GWContours_Draft` /
  `Env_GWFlowArrow_Draft` with `ReviewStatus='DRAFT'`. This **is** most of
  both review docs' "Stage 1 (TIN) / Stage 2 (IDW)" recommended path — a
  single-method-per-call function, not yet orchestrated as a multi-model
  pipeline with ranking.
- **`evaluate_gw_models.evaluate_gw_models`** is headless (pure `csv`+`math`),
  computes RMSE/mean-error/MAE/pct-within-tolerance and ranks models 1..N by
  RMSE. It consumes a wide CSV of externally-supplied predictions — it does
  not interpolate itself. Blocker 3 ("model output registry + ranking … not
  designed") is **partially resolved**: the ranking metric exists; missing
  are (a) glue from contour output to the CSV it expects, (b) a persisted
  registry table, (c) a hydro-override/approval field.
- **`draft_plume_boundary.py`** (shipped as CLI `draft-plume-boundary`, tool
  4.5, `Runtime.LOCAL`, status `stable`) already builds a convex/concave hull
  polygon from `ExceedsScreeningLevel==1` wells and writes
  `Env_PlumeBoundary_Draft` with `ReviewStatus='DRAFT'`. This **is**
  `CONDITIONAL_TOOLS_REVIEW.md`'s "Phase 1: Deterministic plume" for
  `BuildAnalyticalConcentrationSurface` — already shipped, just under a
  different tool name, and the module's own docstring explicitly disclaims
  being "a geostatistical surface model." It does not yet clip to a site
  boundary polygon.
- **`estimate_gw_flow_direction.py`** (headless, CSV-driven plane fit) and
  `groundwater_contours.fit_plane_gradient` (arcpy-embedded, same math,
  GDB-driven) are **two separate implementations of the same plane-fit flow
  direction**. Not a blocking decision for this ADR, but flagged as a
  consolidation candidate for whichever per-tool spec touches flow direction
  next.
- **`gdb_schema.py`** (`SCHEMA_VERSION = "2.3"`, `upgrade_schema.py`) has
  `Env_GWContourPoints`, `Env_GWContours_Draft`, `Env_GWFlowArrow_Draft`,
  `Env_PlumeBoundary_Draft`, `ElevationHistory`. **No `GW_Model*` registry
  tables exist** — that schema is genuinely undesigned, confirming the
  handoff doc.
- **Nondetect policy — correction to the handoff doc.** The handoff doc
  suggested checking `generate-reg-tables`'s config for a reusable nondetect
  rule. It doesn't have one: `regulatory_table_builder.ND_QUALIFIERS =
  frozenset({"ND","U","BDL"})` is a **display-only** label set, not a
  numeric substitution policy. Separately, `apply_screening.py` hardcodes
  "a non-detect never exceeds screening level" for `ExceedsScreeningLevel`
  (effectively an always-on "exclude" rule for the exceedance flag, which
  `draft_plume_boundary.py` inherits). **A configurable nondetect policy
  (half-RL / RL / zero / exclude) does not exist anywhere in this codebase
  yet.** This matters for scoping decision 4 below.
- **`capabilities.py`** confirms the established guard-then-redirect LOCAL
  pattern (`Runtime.LOCAL` + `.pyt` Tool class calling a `# pragma: no
  cover` core function) used by `gw-contours`, `draft-plume-boundary`,
  `condition-dem`, `compare-drone-surfaces` — the pattern this ADR's slice-1
  tools should follow, not a new one.
- **`pyproject.toml`**: `numpy>=1.24` is already a hard dependency (not a new
  concern). `scipy`/`scikit-learn` are still not deps. EBK/kriging require
  arcpy's Geostatistical Analyst extension (LOCAL, licensed, same
  `CheckExtension` pattern as 3D/Spatial Analyst) — no new Python dependency
  question, only an arcpy-signature-verification one (ADR-0077).

## Decision

### 1. Execution-mode split per stage

**Recommendation:** Extend the already-shipped, license-gated
`build_groundwater_contours` (LOCAL/arcpy) for TIN/IDW rather than write a
parallel implementation. Add a thin headless orchestration layer
(`run_field_to_groundwater_model_pipeline`) that calls it once per method,
collects results into the CSV shape `evaluate_gw_models` already expects, and
persists a run record. EBK/kriging is a **separate, deferred stage** — its
own `.pyt` Tool class, gated the same way TIN/IDW are gated on `3D`/`Spatial`
licenses, but gated additionally on `Geostatistical Analyst` and on an
ADR-0077 doc-verification pass over the actual arcpy calls (`EmpiricalBayesianKriging`,
`GACrossValidation`, etc.) — not performed in this ADR, so EBK/kriging is
**not in slice-1 scope**.

### 2. Model QA / registry schema

**Recommendation:** Reuse `Env_GWContourPoints` for input/excluded points —
it already carries `SiteID, EventDate, LocationID,
GroundwaterElevation_ft, UseForContour, ExclusionReason`, which is the same
shape the review doc's `GW_ModelInputPoints`/`GW_ModelExcludedPoints` were
asking for. Add only what's genuinely missing:

- `GW_ModelRun` — one row per pipeline invocation (`RunID` PK, `SiteID`,
  `EventDate`, `Methods` requested, `RunTimestamp`, `ApprovedModel`,
  `ReviewStatus`, `Notes`).
- `GW_ModelCrossValidation` — persists `evaluate_gw_models.ModelStats` 1:1
  (`RunID` FK, `ModelName`, `NPoints`, `RMSE`, `MeanError`, `MAE`,
  `PctWithinTolerance`, `Rank`).

`SCHEMA_VERSION` bumps `2.3` → `2.4`, additive only, per the
`upgrade_schema.py` convention.

### 3. Ranking + approval workflow

**Recommendation:** Reuse the existing `ReviewStatus` DRAFT→APPROVED
convention (already used by `Env_GWContours_Draft`,
`Env_PlumeBoundary_Draft`) rather than invent a new status system.
`evaluate_gw_models`'s rank-1 model is a **default suggestion only**;
`GW_ModelRun.ApprovedModel` is set by the hydrogeologist and can diverge from
rank 1 — both docs are explicit that hydro judgment trumps the metric.
Approval is a GDB field edit or a small CLI verb, not a new workflow engine.

### 4. Nondetect policy config

**Recommendation: out of slice-1 scope.** Per the reuse-inventory
correction above, no reusable nondetect substitution config exists, and
none of the slice-1 deliverables need one — `draft-plume-boundary` already
works off the boolean `ExceedsScreeningLevel` flag, which is unaffected by
this decision. Design a shared `nondetect_rule: exclude|half_rl|use_rl|
use_zero` config only when slice 2's continuous concentration surface
(interpolating actual values, not just an exceed/no-exceed flag) requires
one. Building it now would be speculative.

### 5. Plume boundary rules

**Recommendation:** `BuildAnalyticalConcentrationSurface`'s slice-1
deliverable is a **small extension of `draft-plume-boundary`**, not a new
tool duplicating hull logic:

- Threshold source is already flexible in principle — `apply_screening.py`
  takes an arbitrary `screening_levels` dict, so "screening level vs.
  site-specific cleanup level" is a config-selection question (which YAML is
  passed upstream), not a code gap.
- Site-boundary clipping does not exist yet — add it, reusing
  `groundwater_contours.py`'s `boundary_fc` clip pattern (`arcpy.analysis.Clip`)
  rather than inventing a new clip path.
- Multi-analyte handling stays one map per analyte (matches the existing
  per-group-sheet pattern in `regulatory_table_builder.py`) — no combined
  multi-analyte merge in slice 1.

Continuous concentration surface / kriging-based plume mapping is deferred to
slice 2 alongside nondetect policy (decision 4).

### 6. Uncertainty presentation

**No decision needed for slice 1** — TIN/IDW produce no uncertainty surface.
Deferred to slice 2 with EBK/kriging, per both source docs' staged path.
When slice 2 is spec'd, the standard-error raster is presented as a
companion raster layer (not embedded in the vector contour output),
following the existing DRAFT convention; the arcpy Geostatistical Analyst
call signatures are doc-verified against pro.arcgis.com in that spec's
session per ADR-0077 — not assumed here.

## Slice map

**Slice 1 (unblocked by this ADR):**
- `RunFieldToGroundwaterModelPipeline` — orchestrates existing
  `build_groundwater_contours` (TIN, then IDW) + `evaluate_gw_models`; writes
  `GW_ModelRun`/`GW_ModelCrossValidation`. No kriging/EBK.
- `BuildGroundwaterSurfaceModel` — single-method entry over the same
  orchestration, adds the hydro-approval flag (decision 3).
- `BuildAnalyticalConcentrationSurface` — extends `draft-plume-boundary`
  with site-boundary clipping; threshold source stays config-driven.
  Continuous surface deferred.

**Slice 2 (deferred, own spec + ADR-0077 arcpy verification pass):**
- EBK/kriging stage for GW surfaces; standard-error uncertainty raster.
- Continuous concentration surface (IDW/EBK) for
  `BuildAnalyticalConcentrationSurface`.
- Nondetect policy config (decision 4) — only needed here.

## Schema sketch

```
GW_ModelRun (new, additive):
  RunID (TEXT 64, PK)      SiteID (TEXT 32)
  EventDate (DATE)         Methods (TEXT 64, e.g. "TIN,IDW")
  RunTimestamp (DATE)      ApprovedModel (TEXT 32, null until hydro sets it)
  ReviewStatus (TEXT 16)   Notes (TEXT 256)

GW_ModelCrossValidation (new, additive):
  RunID (TEXT 64, FK -> GW_ModelRun)   ModelName (TEXT 32)
  NPoints (LONG)            RMSE (DOUBLE)        MeanError (DOUBLE)
  MAE (DOUBLE)              PctWithinTolerance (DOUBLE)   Rank (LONG)

Env_GWContourPoints (existing, reused as-is — no change):
  SiteID, EventDate, LocationID, GroundwaterElevation_ft,
  UseForContour, ExclusionReason
```

`SCHEMA_VERSION` `"2.3"` → `"2.4"` in `upgrade_schema.py`, additive tables
only.

## Consequences

### Positive

- Slice 1 mostly wires up already-shipped, already-tested pieces
  (`groundwater_contours`, `evaluate_gw_models`, `draft_plume_boundary`) —
  small net-new surface area, no new dependencies, no new arcpy call
  patterns to verify (TIN/IDW/hull/clip are all precedented in this
  codebase already).
- Corrects the handoff doc's nondetect-reuse assumption before it costs a
  wasted design cycle — decision 4 is explicitly scoped out rather than
  half-built against a nonexistent precedent.
- 2 of the 3 tools' stated "primary blocker" (model QA schema, uncertainty
  output format) are resolved for the TIN/IDW case without touching kriging.

### Negative

- `BuildAnalyticalConcentrationSurface`'s "surface" in its name oversells
  slice 1: it ships a boundary-clipping extension, not a continuous
  concentration raster. That gap (and its nondetect-policy prerequisite) is
  explicitly deferred, not silently dropped — flagged here for stakeholder
  expectation-setting before slice-1 work starts.
- EBK/kriging and its uncertainty output remain fully unspecified pending an
  ADR-0077 arcpy doc-verification pass — a real second design/verification
  cycle stands between slice 1 landing and slice 2 starting.
- Two parallel flow-direction implementations (`estimate_gw_flow_direction.py`
  vs. `groundwater_contours.fit_plane_gradient`) are left unconsolidated;
  noted for whichever slice-1 spec touches flow direction, not resolved here.

## Alternatives considered

1. **Design new `GW_ModelInputPoints`/`GW_ModelExcludedPoints` tables**
   matching the review doc's literal naming. Rejected: `Env_GWContourPoints`
   already carries the same columns; a second table would duplicate data for
   a naming-purity gain only, which the project doesn't otherwise chase (see
   ADR-0075's "never widen/duplicate registered schema for cosmetic
   reasons").
2. **Put EBK/kriging in slice 1**, matching the review doc's literal 3-tool
   ask more closely. Rejected: both source docs recommend staging kriging
   last, and ADR-0077 requires doc-verifying unfamiliar Geostatistical
   Analyst arcpy signatures before shipping — no such verification has been
   done in this session, so shipping unverified kriging calls would violate
   ADR-0077 directly.
3. **Build the nondetect policy config now**, since two of the three tools'
   review sections mention it. Rejected as premature: no slice-1 deliverable
   consumes it (`draft-plume-boundary` already works off the boolean
   exceedance flag). YAGNI — design it when slice 2's continuous surface
   actually needs a numeric substitution value.
4. **Build `BuildAnalyticalConcentrationSurface` as a new standalone tool**
   independent of `draft-plume-boundary`. Rejected: it would duplicate hull
   logic that already ships, tested, under a different CLI name — extending
   the existing tool is the smaller, correct diff.

## Related decisions

- [ADR-0002](0002-arcpy-free-core-invariant.md) — arcpy-free `core`/`adapters`
  invariant this ADR's slice-1 plan preserves (orchestration headless, arcpy
  calls stay `# pragma: no cover` behind the `.pyt` seam).
- [ADR-0006](0006-pyt-toolbox-as-primary-ui.md) — `.pyt` seam pattern
  slice-1 tools follow.
- [ADR-0061](0061-drone-geotech-graphics-tool-batch.md) — prior rescope of
  this same gate; precedent for narrowing scope against shipped
  infrastructure.
- [ADR-0075](0075-canonical-schema-expansion-step1.md) — additive-schema /
  no-duplicate-table precedent this ADR's schema sketch follows.
- [ADR-0077](0077-arcpy-api-currency-policy.md) — gates slice 2's EBK/kriging
  arcpy calls; not satisfied by this ADR.
- `docs/CONDITIONAL_TOOLS_REVIEW.md`, `docs/superpowers/specs/
  2026-06-28-geostatistical-conditional-tools-design.md`,
  `docs/HANDOFF-2026-07-15-geostat.md` — source docs for this review.
- Issue #167 — prior gate-scope correction.
