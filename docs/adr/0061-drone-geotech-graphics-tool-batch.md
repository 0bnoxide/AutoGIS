# ADR-0061: Drone/geotech-graphics tool batch — rescoped out of the Phase 5 geostatistical gate

**Status:** Accepted

**Date:** 2026-07-06

## Context

CLAUDE.md's "Conditional / geostatistical (Phase 5)" deferred group blocks
kriging/EBK/surface-modeling tools pending architecture review
(`docs/CONDITIONAL_TOOLS_REVIEW.md`). A 2026-07-05 gap-analysis survey found
that doc was stale in two ways (tracked as issue #167):

1. Items #3/#4/#5 (`SurveyToWellElevationUpdate`, `GenerateRegulatoryTables`,
   `EvaluateGroundwaterSurfaceModels`) had already shipped as fast-track
   tools, but the doc still listed them as unbuilt.
2. Items #7/#8/#9 (`DEMConditioningPipeline`, `CompareDroneSurfaces`,
   `GenerateSubsurfaceProfileFromBorings`) sat under the Phase 5 gate by
   proximity in the same review document, not by substance — none of them do
   kriging/EBK geostatistical interpolation. They are drone-raster and
   geotech-graphics work.

The user reviewed and confirmed the rescoping of #7/#8/#9 on 2026-07-05; a
design (`docs/superpowers/specs/2026-07-05-drone-geotech-graphics-batch-design.md`)
was approved via `superpowers:brainstorming`, and this batch implements it.

## Decision

1. **Rescope #7/#8/#9 out of the Phase 5 gate and ship them.** Only the true
   kriging/EBK/surface-modeling items — `RunFieldToGroundwaterModelPipeline`,
   `BuildGroundwaterSurfaceModel`, and `BuildAnalyticalConcentrationSurface`
   (items #1, #2, #6) — remain gated. `docs/CONDITIONAL_TOOLS_REVIEW.md` and
   CLAUDE.md are updated to reflect this (closes issue #167).

2. **Two-tier architecture, reusing existing boring/drone foundations**
   (`core/common/schema/{boring,drone}.py`, `import_drone_products.py`,
   `register_drone_flight.py`, `create_boring_log_database.py`,
   `boring_log_report.py`):

   | Tool | Tier | Why |
   |---|---|---|
   | `GenerateSubsurfaceProfileFromBorings` | **Headless** | Reads the already-normalized boring SQLite DB (tool 8.0a) via `boring_log_report.read_boring_records` — pure geometry + optional matplotlib rendering, no GDB/raster access. Reclassified from the review doc's original "local ✓✓", which predated the boring-log normalization pipeline. |
   | `DEMConditioningPipeline` | **LOCAL** (arcpy) | Raster void-fill/smoothing on a DEM pulled from the drone GDB (`DroneFlight.DEMPath`). No rasterio/GDAL in this project — raster ops go through arcpy elsewhere, and this follows suit. |
   | `CompareDroneSurfaces` | **LOCAL** (arcpy) | Raster differencing between two DEM sources. Same arcpy raster-access need. |

   The two LOCAL tools are **loosely coupled, not pipelined**:
   `CompareDroneSurfaces` takes any `DroneProductRecord` (raw or conditioned)
   as either surface — no dependency on `DEMConditioningPipeline` internals.
   Conditioning-then-comparing is a recommended workflow, not an enforced one.

3. **`core/common/landxml.py`** — a new, stdlib-only (`xml.etree.ElementTree`),
   **read-only** LandXML TIN parser (`Surfaces/Surface/Definition` →
   points + triangle faces, barycentric elevation sampling). Backs
   `CompareDroneSurfaces`'s second baseline mode (a design surface, alongside
   a second drone DEM). LandXML **write**/export support is separate scope
   (issues #164/#166) — not built here.

4. **matplotlib as a new optional extras group** (`profile = ["matplotlib>=3.7"]`
   in `pyproject.toml`), following the existing `report = ["Pillow>=9.0"]`
   precedent — lazy-imported inside `subsurface_profile.render_profile`
   (mirroring `well_inspection_photo_report._prepared_image_bytes`'s
   lazy-Pillow-import-with-friendly-`ImportError`-hint pattern) so `core/`
   stays importable without matplotlib installed.

5. **CLI shape matches existing precedent, split by tier:**
   - `generate-subsurface-profile` is a full headless command (build + render
     + QA report), same shape as `gen-boring-logs`.
   - `condition-dem` and `compare-drone-surfaces` are guard-then-redirect
     commands — `_guard(name)` then a `click.ClickException` pointing at the
     `.pyt` toolbox — matching the original Tools 2-8 pattern (`import-gdb`,
     `build-event`, `gw-contours`, …), not the richer direct-call pattern used
     by `register-drone-flight`/`import-drone-products`. The actual arcpy
     raster calls (`condition_dem`, `compare_surfaces`) live in the core
     modules as `# pragma: no cover` functions, called only from new `.pyt`
     Tool classes (`ConditionDEM`, `CompareDroneSurfaces`) — mirrors the
     `load_flight_yaml`-is-not / `write_drone_flight`-is-arcpy split in
     `register_drone_flight.py`.

## Consequences

### Positive

- Closes issue #167: the review doc and CLAUDE.md's Phase 5 gate count now
  match reality (3 tools remain gated, not ~8).
- All arcpy-free logic (endpoint projection/tolerance filtering, DEM
  conditioning config/validation, LOD diff classification, LandXML parsing)
  is unit-tested in the standard arcpy-free suite; only the raster arcpy
  calls themselves are untestable without a live Pro session, and those are
  isolated to small `# pragma: no cover` functions per the project's
  established split.
- `core/`/`adapters/` stay importable with neither `arcpy` nor `matplotlib`
  installed — the arcpy-free invariant (ADR-0002) and the "zero
  PDF/graphics deps by default" precedent both hold.
- Reuses `read_boring_records` and `import_drone_products.write_product_registry`
  instead of parallel readers/writers.

### Negative / accepted trade-offs

- `GenerateSubsurfaceProfileFromBorings`'s profile line is always exactly two
  literal or boring-derived endpoints — no multi-point line-fitting. Simplest
  correct behavior matching how a profile line is drawn in practice; borings
  beyond `--projection-tolerance-ft` are excluded with a named QA warning,
  not shown with an offset annotation (considered and rejected as unrequested
  scope).
- LandXML support is read-only this batch. Write/export is tracked separately
  (issues #164/#166) and was deliberately not folded in here to keep this
  batch's scope to the 3 rescoped tools.
- `compare_surfaces` resolves both DEM inputs by `DroneProductRegistry`
  product ID (a full raster diff, cell-by-cell) rather than accepting raw
  file paths directly — consistent with `condition_dem`'s GDB-lookup pattern,
  but means both DEMs must already be registered products.
- `condition_dem`'s `--smooth` supports `median` only. A `gaussian` option
  was speculatively drafted but dropped before merge: `arcpy.sa` has no true
  Gaussian-blur statistic, and hand-rolling one via an `NbrWeight` kernel file
  would mean unverifiable arcpy syntax with zero test coverage. If a site
  needs it, the safe path is repeated `NbrCircle`+`MEAN` passes (2-3x
  converges toward Gaussian) using primitives already proven in this file.

## Alternatives considered

1. **Leave #7/#8/#9 under the Phase 5 gate indefinitely.** Rejected: they do
   not do geostatistical interpolation, so gating them on kriging/EBK
   architecture review (which they don't need) would block unrelated,
   already-designed work with no benefit.
2. **Give `CompareDroneSurfaces` a hard dependency on `DEMConditioningPipeline`'s
   output shape.** Rejected: the review doc's own design and the batch spec
   call for loose coupling — either tool should work standalone, and forcing
   a pipeline would couple two tools that don't need to know about each
   other.
3. **Build LandXML write support alongside the read side** (since the parser
   already models points/faces). Rejected as scope creep: the write side
   serves `export-survey-cad --format landxml` and `ExportContoursForCivil3D`,
   which are unrelated CLI surfaces already tracked in their own issues.

## Related decisions

- [ADR-0002](0002-arcpy-free-core-invariant.md) — the arcpy-free
  `core`/`adapters` invariant this batch preserves.
- `docs/superpowers/specs/2026-07-05-drone-geotech-graphics-batch-design.md` —
  the design this ADR records.
- `docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md` —
  origin of the "zero PDF/graphics deps in the arcpy-free layer by default"
  precedent this batch follows for matplotlib.

## Issues/PRs

- Closes issue #167 (`docs/CONDITIONAL_TOOLS_REVIEW.md` mis-scoping).
- New: `autogis/core/envmon/subsurface_profile.py`,
  `autogis/core/envmon/dem_conditioning.py`,
  `autogis/core/envmon/compare_drone_surfaces.py`,
  `autogis/core/common/landxml.py`.
- Modified: `autogis/adapters/cli.py`, `autogis/adapters/toolbox.pyt`,
  `autogis/runtime/capabilities.py`, `pyproject.toml`.
