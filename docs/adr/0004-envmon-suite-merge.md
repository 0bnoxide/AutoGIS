# ADR-004: Merge envmon suite into AutoGIS

**Status:** Accepted

**Date:** 2026-06-19

## Context

The environmental monitoring suite lived in a separate `staging/envmon-incoming/` directory (23 modules, 56 tests). This created:

1. Unclear project boundaries (is envmon part of AutoGIS or separate?)
2. Duplicated infrastructure (separate config system, logging, QA)
3. Unclear code ownership and test ownership

The question: should envmon be repackaged as a submodule of AutoGIS or kept separate?

## Decision

Merge the 23 envmon modules into `autogis/core/envmon/` with:

1. Unified config system (dataclass-based, under `autogis/core/common/config.py`)
2. Shared logging and QA infrastructure
3. All 56 tests ported and passing in unified test suite
4. envmon CLI subcommands under `autogis/adapters/cli.py`
5. 10 envmon tools wired into the `.pyt` toolbox

This establishes envmon as a first-class AutoGIS subsystem, not a separate tool collection.

## Consequences

### Positive

- Unified codebase with clear ownership
- Shared infrastructure (config, logging, QA, testing)
- All 56 envmon tests pass in CI; discovered 53 harvest + 56 envmon + 4 new guard/CLI/capabilities = 113 total
- Arcpy-free invariant holds across all modules
- Single entry point for both harvest and envmon capabilities

### Negative

- Larger core package surface
- 23 more modules to maintain and test
- envmon config schema now coupled with harvest config schema (mitigated by separate dataclass sections)

## Status corrections

Original plan claimed "165 tests target" but was double-counting:
- Baseline already collected 56 envmon tests via sys.path hack
- Real total: 113 (not 165)

## Related decisions

- [ADR-001: Core-adapters separation](0001-core-adapters-separation.md)
- [ADR-003: HarvestConfig canonical location](0003-harvest-config-canonical-location.md)
- [ADR-005: Thread-safe QA substrate](0005-thread-safe-qa-substrate.md)

## Issues/PRs

- Merge: [#1 envmon-suite-merge](https://github.com/0bnoxide/AutoGIS/pull/1)
- Commit: `cc6ba1e` (repackage envmon, ported tests)
