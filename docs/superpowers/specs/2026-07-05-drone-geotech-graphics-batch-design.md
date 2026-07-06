# Drone / Geotech-Graphics Tool Batch — Design

**Date:** 2026-07-05
**Status:** Design approved; implementation follows
**Scope:** 3 tools rescoped out of the Phase 5 geostatistical phase gate
**Source:** Gap-analysis survey (2026-07-05) of `docs/CONDITIONAL_TOOLS_REVIEW.md`
items #7-#9, confirmed by the user as drone-raster/geotech-graphics work, not
kriging/EBK geostatistical modeling — see tracking issue for the doc's own
mis-scoping (`docs/CONDITIONAL_TOOLS_REVIEW.md` review issue).

## Phase-gate note

CLAUDE.md's "Conditional / geostatistical (Phase 5)" deferred group blocks
kriging/EBK/surface-modeling tools pending architecture review. These 3 tools
(`DEMConditioningPipeline`, `CompareDroneSurfaces`,
`GenerateSubsurfaceProfileFromBorings`) were listed in the same review
document by proximity, not by substance — none of them do geostatistical
interpolation. The user has explicitly reviewed and confirmed this rescoping
(2026-07-05); the two true geostatistical-gate tools (RunFieldToGroundwaterModelPipeline,
BuildGroundwaterSurfaceModel / EBK-kriging work) remain gated. This decision
gets its own ADR once this batch ships.

## Goal

Build the 3 tools, each closing a gap identified in
`docs/CONDITIONAL_TOOLS_REVIEW.md` (items #7, #8, #9), reusing the existing
boring-log and drone-flight foundations already in the codebase
(`core/common/schema/{boring,drone}.py`, `import_boring_logs.py`,
`import_drone_products.py`, `register_drone_flight.py`,
`create_boring_log_database.py`, `boring_log_report.py`).

## Architecture — 2 tiers

| Tool | Tier | Why |
|---|---|---|
| GenerateSubsurfaceProfileFromBorings | **Headless** | Reads the already-normalized boring SQLite DB (Tool 8.0a); pure geometry + matplotlib rendering, no GDB/raster access needed. Reclassified from the review doc's original "local ✓✓" — that classification predates the boring-log normalization pipeline. |
| DEMConditioningPipeline | **LOCAL** (arcpy) | Raster void-fill/smoothing on a DEM pulled from the drone GDB (`DroneFlight.dem_path`). No rasterio/GDAL dependency in this project — raster ops go through arcpy elsewhere, and this follows suit. |
| CompareDroneSurfaces | **LOCAL** (arcpy) | Raster differencing between two DEM sources. Same arcpy raster-access need as above. |

Coupling between the two LOCAL tools is **loose, not pipelined**:
`CompareDroneSurfaces` takes two DEM references (`DroneProductRecord`s — raw
or conditioned) and has no dependency on `DEMConditioningPipeline` internals.
Conditioning-then-comparing is the recommended workflow, not an enforced one
— avoids coupling two tools that don't need to know about each other.

## Component 1 — GenerateSubsurfaceProfileFromBorings (headless)

- `core/envmon/subsurface_profile.py`: the profile line is always exactly
  two endpoints — either literal coordinate pairs, or the resolved
  coordinates of two named `boring_id`s used as endpoints (no multi-point
  line-fitting; unambiguous, matches how a profile line is drawn in
  practice). Given a projection tolerance (CLI flag
  `--projection-tolerance-ft`, default 50 ft — the review doc's own example
  value), the tool projects every `BoringLocation` within tolerance onto
  that line, pulls its `LithologyInterval`s, and produces a
  `ProfileBoringPlacement` (offset distance + projected station) per boring.
- Borings beyond tolerance are **excluded with a QA warning** naming them —
  not silently dropped, not shown with an offset annotation (simplest
  correct behavior; showing offset annotations was considered and rejected
  as unrequested scope).
- Rendering: matplotlib, added as a new optional extras group in
  `pyproject.toml` (`profile = ["matplotlib>=3.7"]`), following the existing
  `report = ["Pillow>=9.0"]` precedent. Import is lazy inside the render
  function so `core/` stays importable without matplotlib installed —
  consistent with `boring_log_report.py`'s documented "zero PDF/graphics
  deps in the arcpy-free layer by default" precedent
  (`docs/superpowers/specs/2026-06-28-generate-boring-log-pdfs-design.md`).
- CLI: headless command in `cli.py`, no `.pyt` entry, no arcpy guard — same
  shape as `generate-boring-log-pdfs`.

## Component 2 — DEMConditioningPipeline (LOCAL)

- Core: `core/envmon/dem_conditioning.py` — arcpy-free config/validation
  logic (which products to generate, threshold parsing), mirroring the
  `write_drone_flight`-is-arcpy / `load_flight_yaml`-is-not split already
  established in `register_drone_flight.py`.
- Void-fill and smoothing are **off by default**; CLI flags turn them on:
  - `--fill-voids [MAX_PIXELS]` — default max 9 px if the flag is bare.
  - `--smooth median|gaussian` — default `median` (preserves terrain edges
    better than Gaussian; standard geomorphology default).
- Output products: DEM + hillshade always generated. `--with-slope` /
  `--with-contours` are opt-in flags. Each output is registered as a new
  `DroneProductRecord` (`product_type` = `"conditioned_dem"`, `"hillshade"`,
  `"slope"`, or `"contours"`).
- `.pyt` entry performs the actual arcpy raster calls (`# pragma: no cover`);
  CLI guards then redirects, matching the existing Tools 2-8 pattern.

## Component 3 — CompareDroneSurfaces (LOCAL)

- Core: `core/envmon/compare_drone_surfaces.py` — LOD-threshold logic (CLI
  flag `--lod-threshold-ft`, default 0.2 ft — matches typical drone vertical
  accuracy per the review doc's own example), diff-classification
  (change/no-change per LOD), arcpy-free once given raw diff values.
- Baseline — supports **both**, per user decision:
  - A second `DroneProductRecord` (prior-flight DEM, raw or conditioned).
  - A LandXML design-surface file.
- New shared module: `core/common/landxml.py` — stdlib
  `xml.etree.ElementTree`, **read-only in this batch**. Parses a
  `<Surfaces><Surface><Definition>` TIN into points + triangle faces,
  rasterizable for diffing against the drone DEM. The write side (LandXML
  export for `export-survey-cad --format landxml` and the `ExportContoursForCivil3D`
  `--landxml` leg) is separate scope — tracked in its own issues, not built
  in this batch.

## Testing

- `GenerateSubsurfaceProfileFromBorings` gets full pytest coverage in the
  arcpy-free suite, same as the rest of `tests/`.
- `DEMConditioningPipeline` and `CompareDroneSurfaces` get arcpy-free unit
  tests on every non-arcpy function (config/validation/threshold/diff-math
  logic); the actual raster calls are `# pragma: no cover`, matching
  `register_drone_flight.py`'s established split. No live Pro session
  needed to verify the logic that can be tested.

## Build order

1. **GenerateSubsurfaceProfileFromBorings** — fully independent, headless,
   fastest to ship and verify.
2. **DEMConditioningPipeline**
3. **CompareDroneSurfaces** — benefits from Component 2 existing (to
   exercise the drone-vs-drone comparison path in review), but does not
   hard-depend on it; the design-surface (LandXML) baseline path is
   independent of Component 2 entirely.

## Explicitly out of scope for this batch

- LandXML **write**/export support (issues #164/#166) — only the read-side
  parser needed for Component 3's design-surface baseline is built here.
- PDF/Word report templating — unrelated recurring gap (issue #163),
  matplotlib here is scoped only to `GenerateSubsurfaceProfileFromBorings`'s
  own PNG/SVG profile output, not a general reporting system.
- AGOL publishing, dashboard tools — unrelated (issue #165).
