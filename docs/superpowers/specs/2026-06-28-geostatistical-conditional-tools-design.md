# Geostatistical / Conditional Tools — Design Stub

**Date:** 2026-06-28
**Status:** DEFERRED — blocked on architecture review (per `ROADMAP_UPDATE_2026-06-25.md`)
**Tools:** RunFieldToGroundwaterModelPipeline, BuildGroundwaterSurfaceModel,
EvaluateGroundwaterSurfaceModels, BuildAnalyticalConcentrationSurface,
DEMConditioningPipeline, CompareDroneSurfaces, GenerateSubsurfaceProfileFromBorings
(plus GenerateRegulatoryTables — already has a plan, listed for completeness)
**Priority:** LOW — Phase 4 / "Conditional," gated behind core-tool stability

---

## Why one stub

`ROADMAP_UPDATE_2026-06-25.md` lists 8 conditional tools that are "high value but
need architecture review before integration." They are deferred for shared, unresolved
design reasons — not yet ready for individual implementation specs. This stub records
them as **planned-but-deferred** (so coverage is honest) and names the blockers each
must clear before it earns a full design spec. One of the eight,
`GenerateRegulatoryTables`, is *not* blocked and already has a plan
(`2026-06-27` / `2026-06-28-generate-regulatory-tables.md`); it is listed here only so
the conditional set is complete in one place.

This is the geostatistical/surface-modeling analog of the AI-tools deferral
(`2026-06-28-ai-assisted-tools-llm-seam-design.md`): capture intent + the blocking
dependency now, write the real spec when the dependency is resolved.

---

## Shared blockers (the architecture review)

1. **Surface-modeling dependency + execution mode.** TIN/IDW/EBK/kriging need either
   the numpy/geostatistics stack (heavy new deps) or arcpy's Geostatistical Analyst
   (a LOCAL, licensed extension). The arcpy-free core invariant (ADR-0002) forces a
   decision: which stages, if any, can run headless, and which route through the
   `.pyt` seam (ADR-0006). Until decided, no module boundary can be drawn.
2. **Nondetect handling rules.** Concentration surfaces and regulatory tables both
   need a configured nondetect policy (substitute ½ DL, Kaplan-Meier, exclude). This
   is a config-schema design task that several tools share.
3. **Model output registry + ranking.** `EvaluateGroundwaterSurfaceModels` needs a
   persisted registry of model runs and a ranking metric (cross-validation RMSE, etc.)
   — a schema addition not yet designed.
4. **Graphics/CAD format.** `GenerateSubsurfaceProfileFromBorings` and
   `CompareDroneSurfaces` need a profile-graphics and surface-diff output format,
   which ties into the CAD export decisions (`BuildCADExportPackage`,
   `ExportContoursForCivil3D`).

---

## Tool intents (one line each)

- **RunFieldToGroundwaterModelPipeline** — staged GW surface pipeline: TIN → IDW → kriging.
- **BuildGroundwaterSurfaceModel** — single geostatistical GW surface (TIN/IDW/EBK/kriging).
- **EvaluateGroundwaterSurfaceModels** — rank candidate surface models by cross-validation.
- **BuildAnalyticalConcentrationSurface** — concentration/plume surface with nondetect rules.
- **DEMConditioningPipeline** — DEM void-fill / smoothing before surface use.
- **CompareDroneSurfaces** — surface-to-surface diff (volume/change) above a detection threshold.
- **GenerateSubsurfaceProfileFromBorings** — cross-section profile graphics from boring logs.
- **GenerateRegulatoryTables** — (not blocked; plan exists) regulatory exceedance tables.

---

## Exit criteria

Each tool graduates to its own `*-design.md` once blockers 1–4 above are resolved for
it. Resolution belongs in an ADR (surface-modeling dependency + execution-mode decision
is ADR-worthy), then per-tool specs follow the established headless / `.pyt`-seam
patterns. Do not implement against this stub.
