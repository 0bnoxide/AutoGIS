# ADR-0009: Config dataclass style (field-typed vs dict-backed)

**Status:** Accepted

**Date:** 2026-06-19

## Context

The envmon config system uses two different dataclass patterns:

1. **Field-typed:** `ParserProfile`, `SheetProfile` — explicit `@dataclass` fields with types
2. **Dict-backed:** `SiteConfig`, `FigureSpec` — raw `data: dict` attribute with `__getattr__` wrapper for dynamic key access

Each has trade-offs:
- Field-typed allows static type checking and IDE support
- Dict-backed allows arbitrary key passthrough (e.g., user-defined analytes without schema changes)

The question: should the merged system mandate one style, or preserve both?

## Decision

Preserve both styles:

1. **Field-typed for config objects with stable, known schemas:** `HarvestConfig` (merged from harness), `ParserProfile`, `SheetProfile`
2. **Dict-backed for config objects that need arbitrary key passthrough:** `SiteConfig`, `FigureSpec`

Do NOT re-express dict-backed configs (like `SiteConfig`/`FigureSpec`) as explicit fields. This breaks existing callers and tests that rely on arbitrary-key passthrough.

## Consequences

### Positive

- Preserves existing envmon behavior (no test breakage)
- Allows new fields to be added to dict-backed configs without code changes
- Type safety for stable configs; flexibility for user-driven extensibility

### Negative

- Two parallel patterns increase cognitive load
- IDE autocomplete works differently for each style
- Documentation must cover both patterns

## Alternatives considered

1. **Mandate field-typed everywhere:**
   - **Rejected:** Breaks existing envmon tests and users who rely on arbitrary-key `SiteConfig` passthrough (e.g., `default_analyte_set`, `analyte_sets` keys not in schema).

2. **Mandate dict-backed everywhere:**
   - **Rejected:** Loses type safety and IDE support for stable configs like `ParserProfile`.

3. **Create a hybrid style:**
   - **Considered but deferred:** More complexity than benefit; the two-style pattern is already proven in envmon.

## Related decisions

- [ADR-003: HarvestConfig canonical location](0003-harvest-config-canonical-location.md) — `HarvestConfig` is field-typed
- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Verification: [mergeplan-deltas.md §C5](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
