# ADR-003: HarvestConfig canonical location

**Status:** Accepted

**Date:** 2026-06-20

## Context

Multiple config loading paths existed in the codebase:
- Legacy `adapters/config_loader.py` – tuple-returning loader
- New envmon-style config system – dataclass-based, nested-flattened
- Uncertainty about where the single source of truth should live

This created confusion about which loader to use and where to document config schema. Config is core business logic (not invocation-specific), so it should live in `core/`.

## Decision

`HarvestConfig` is canonical in `autogis/core/common/config.py` with a `.load(path)` classmethod. This location:

1. Makes it clear that config is core business logic
2. Centralizes config schema and validation
3. Supports nested-flattening and URL/item_id XOR validation

The dataclass is also re-exported from `autogis/core/harvest/models.py` for backward compatibility with adapters that import it from harvest.

The legacy `adapters/config_loader.load_config()` remains untouched (its CLI profile/override rewiring is deferred).

## Consequences

### Positive

- Single canonical location for config definition and loading
- Config schema is documented and validated in one place
- Nested YAML naturally maps to nested dataclasses
- `.load()` classmethod allows validation at parse time

### Negative

- Legacy loader still exists in parallel (technical debt)
- Re-exports create potential for confusion about canonical location
- Profile/override rewiring still pending (deferred work)

## Alternatives considered

1. **Keep config in adapters:**
   - **Rejected:** Config is business logic, not invocation-specific.

2. **Create a separate `autogis/config/` package:**
   - **Rejected:** Core business logic should live in `core/`.

3. **Keep both locations (current state):**
   - **Rejected:** Creates duplication and confusion.

## Related decisions

- [ADR-001: Core-adapters separation](0001-core-adapters-separation.md)
- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Initial impl: [#1 task 2](https://github.com/0bnoxide/AutoGIS/pull/1)
