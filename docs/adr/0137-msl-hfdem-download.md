# ADR-0137: Archive-first MSL HFDEM download with artifact provenance

**Status:** Proposed

**Date:** 2026-11-10

## Context
The owner requested a Montana State Library HFDEM workflow alongside OpenTopography and approved explicit project selection, emphasizing traceable resolution, accuracy and confidence. Live discovery found mixed project/product archives, missing ZIPs, ambiguous project folders and distributed raster metadata differing from original delivery metadata. A real ImageServer exists but its NoData coverage differed from the archive in a controlled native-grid probe.

## Decision
Use archive-first, polygon-preserving discovery and acquisition with strict size/cache/ZIP safeguards. Keep core network functions arcpy-free and use an optional rasterio backend for headless CLI plus native ArcPy in the toolbox. Require explicit selection for multiple projects. Validate actual artifact references and grids before mosaicking; preserve unknowns rather than infer Z units or accuracy. Resolution, project-level publisher accuracy claims and output coverage are distinct provenance records. Horizontal reprojection and Z scaling do not authorize vertical datum transformation. Keep OpenTopography unchanged.

## Consequences
- Reproducible source bytes, project identity and metadata links are retained in .tif.json.
- Missing/ambiguous artifacts and incompatible metadata stop instead of silently substituting or blending.
- Optional dependencies do not affect unrelated AutoGIS tools; native license constraints remain visible.
- Some projects cannot safely convert elevation units without better artifact metadata; report PDFs remain human-interpreted evidence.
- Explicit project-mosaic acquisition is available but does not silently replace quadrangle failures.
- Native ArcPy processing passed live QA; this ADR remains Proposed until final review and interactive Pro acceptance.

## Alternatives considered
Direct ImageServer export was evaluated and rejected as an equivalent fallback because masked archive cells returned elevations. Automatically selecting newest collections was rejected by the owner in favor of explicit project selection. Applying inventory NativeVerticalUnits to distributed tiles was rejected because live artifacts can have different coordinate metadata.

## Related decisions
- [ADR-0002](0002-arcpy-free-core-invariant.md)
- [ADR-0077](0077-arcpy-api-currency-policy.md)
- [ADR-0078](0078-opentopography-dem-download.md)
- [Design](../superpowers/specs/2026-11-10-msl-hfdem-design.md), [QA](../qa/msl-dem.md), [usage](../msl-dem.md)
