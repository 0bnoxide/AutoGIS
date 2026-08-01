# ADR-0001: Core-plus-adapters architecture

**Status:** Accepted

**Date:** 2026-06-18

## Context

The project needs to support multiple invocation contexts (CLI, ArcGIS Pro `.pyt` toolbox, Jupyter notebooks, future AGOL automation) while maintaining a single source of truth for business logic. Without architectural separation, code would need to be duplicated or tightly coupled to a specific invocation model.

The core problem: how do we write harvester/environmental monitoring logic once and reuse it across different runtimes (headless CLI, arcpy-dependent Pro toolbox, etc.)?

## Decision

Separate the project into two layers:

1. **Core (`autogis/core/`):** Pure Python business logic that receives external dependencies (e.g., a connected `arcgis.gis.GIS` object, a `HarvestConfig`). Never imports `arcpy` or anything invocation-specific.

2. **Adapters (`autogis/adapters/`):** Thin invocation-specific layers:
   - `cli.py` – CLI adapter (Click, argument parsing, builds GIS session)
   - `.pyt` – ArcGIS Pro toolbox adapter
   - Future: notebook/AGOL adapters

The core only depends on adapters providing a connected session and config; adapters handle environment setup, secrets, toolbox scaffolding.

## Consequences

### Positive

- Business logic is testable without arcpy, arcgis, or ArcGIS Pro installed
- Logic is reusable across multiple invocation contexts without duplication
- Easier to add new adapters (notebook, AGOL, scheduled tasks) without modifying core
- Clear separation of concerns: core handles logic, adapters handle ceremony

### Negative

- More files to maintain (separation adds structure overhead)
- Adapters must correctly construct dependencies before calling core
- Core cannot use arcpy conveniences (must work around them or implement equivalents)

## Alternatives considered

1. **Monolithic approach:** Bundle all logic with CLI/toolbox. 
   - **Rejected:** Leads to code duplication, hard to test without Pro installed.

2. **Import arcpy optionally in core:**
   - **Rejected:** Violates the arcpy-free invariant and creates implicit coupling.

3. **Service layer over arcpy:**
   - **Considered but deferred:** More overhead; core-adapters separation was sufficient for current needs.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-006: .pyt toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
