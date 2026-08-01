# ADR-0006: .pyt toolbox as primary UI for LOCAL tools

**Status:** Accepted

**Date:** 2026-06-20

## Context

Tools 2–8 (LOCAL tools) require arcpy and an active ArcGIS Pro session. The question: should CLI provide full-featured support for these tools, or should the .pyt toolbox be the primary UI?

Invocation contexts:
- **Headless tools (1, 9, 10):** openpyxl only, can run in CLI or toolbox
- **LOCAL tools (2–8):** require arcpy + Pro session, ideally invoked from Pro

Trade-off: Rich CLI UX vs. single source of truth (Pro toolbox).

## Decision

The `.pyt` toolbox is the primary UI for LOCAL tools (2–8). CLI commands for these tools:

1. Detect if running headless (no active Pro session)
2. Raise a clear `ClickException`: "Use the Pro toolbox instead"
3. Do not provide an alternative headless execution path

This follows the constraint: ".pyt is their primary UI; no rich CLI ergonomics for 2–8".

Rationale:
- Pro toolbox provides parameter validation, geometry visualization, and session management that CLI cannot replicate
- Attempting dual paths (CLI + toolbox) leads to code divergence and bugs
- Single path (toolbox) is clearer and more maintainable

## Consequences

### Positive

- Clear guidance: users know to use toolbox for LOCAL tools
- Single code path (no branching logic)
- Easier to maintain; reduces testing surface
- Emphasizes Pro toolbox as the "official" UI

### Negative

- Users cannot invoke LOCAL tools from CLI (even for automation)
- Headless workflows cannot use LOCAL tools (expected and documented)
- Requires documentation to set expectations

## Alternatives considered

1. **Dual execution (CLI + toolbox):**
   - **Rejected:** Code divergence, testing complexity, maintenance burden.

2. **Emulate Pro in CLI:**
   - **Rejected:** Not possible without arcpy and Pro session.

3. **Defer to future adapters (notebook, AGOL):**
   - **Rejected:** Doesn't solve the problem; still need guidance on invocation.

## Related decisions

- [ADR-001: Core-adapters separation](0001-core-adapters-separation.md)
- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md)

## Issues/PRs

- Implementation: [#1 task 5](https://github.com/0bnoxide/AutoGIS/pull/1)
- Commit: `1f600f8` (envmon CLI + .pyt wiring + guards)
