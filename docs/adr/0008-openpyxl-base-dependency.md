# ADR-0008: Openpyxl as base dependency

**Status:** Accepted

**Date:** 2026-06-19

## Context

The envmon modules `envmon_config`, `excel_profile_reader`, and others import `openpyxl` at the module level to read Excel workbooks. This is foundational functionality for configuration parsing and data inspection. The question: should `openpyxl` be optional or required?

Previously, `openpyxl` was treated as a conditional extra, but during the envmon merge verification, it became clear that core modules fail to import without it.

## Decision

`openpyxl` is a **base** dependency of the AutoGIS package (not an optional extra). It must be listed in `pyproject.toml` under `dependencies`, not `extras`.

This is distinct from `arcpy` and `arcgis`, which are conditionally lazy-loaded or optional (`arcgis` is the `cloud` extra, `arcpy` is runtime-detected).

## Consequences

### Positive

- Clear distinction: `openpyxl` is always present; `arcpy/arcgis` are conditional
- Simpler packaging; no feature matrix confusion
- All Excel-based tools (workbook inspection, parser profiles) work without special installation
- Consistent with envmon's existing usage

### Negative

- Every installation carries `openpyxl` even if the user never inspects workbooks
- Adds a dependency that some users may not need (mitigated: small library, widely-used)

## Alternatives considered

1. **Keep openpyxl as an extra:**
   - **Rejected:** Core modules import it unconditionally; making it an extra breaks import of those modules.

2. **Lazy-import openpyxl in modules:**
   - **Rejected:** High-level modules like `envmon_config` use it pervasively; lazy import provides no real benefit.

3. **Replace openpyxl with an alternative:**
   - **Rejected:** openpyxl is well-supported and already used by envmon.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — `openpyxl` is NOT subject to this invariant; only `arcpy/arcgis` are lazy.
- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Verification: [mergeplan-deltas.md §C2](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
