# ADR-002: Arcpy-free core invariant

**Status:** Accepted

**Date:** 2026-06-18

## Context

The project must be testable in CI/CD environments where ArcGIS Pro is not installed. Arcpy requires Pro and cannot be mocked easily due to its tight integration with the OS and ArcGIS installation. Including arcpy in core code blocks testing and makes local development harder.

Constraint: Tools 2–8 (LOCAL tools) require arcpy for geodatabase/shapefile manipulation, but tools 1, 9, 10 are headless (openpyxl only).

## Decision

The core library (`autogis/core/**`) MUST NOT import `arcpy` or anything that depends on arcpy at the module level. This applies to:

- Direct imports of `arcpy`
- Any transitive import that requires `arcpy`

Lazy imports or runtime checks for arcpy in adapters are acceptable; core must never require it.

## Consequences

### Positive

- The entire test suite runs in CI without Pro installation
- Easier local development on non-Windows machines or without Pro
- Clear boundary: what's testable offline vs. what requires a Pro session

### Negative

- Core code cannot use arcpy utilities (must implement equivalents or use alternatives)
- Some utility functions (geometry, spatial joins) must be implemented or wrapped by adapters
- More defensive coding in core (no assumptions about arcpy availability)

## Alternatives considered

1. **Install Pro in CI:**
   - **Rejected:** Expensive, slow, license management complexity.

2. **Mock arcpy in tests:**
   - **Rejected:** Arcpy has deep OS/GIS integration; mocks become fragile and misleading.

3. **Lazy-import arcpy in core:**
   - **Rejected:** Still violates the invariant; hidden coupling that breaks assumptions.

## Related decisions

- [ADR-001: Core-adapters separation](0001-core-adapters-separation.md)
- [ADR-006: .pyt toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
