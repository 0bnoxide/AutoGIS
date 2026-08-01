# ADR-0013: Per-record JSON writer for manifest

**Status:** Accepted

**Date:** 2026-06-19

## Context

The harvester system writes a per-record JSON manifest (`manifest.json`), where each download/skip/failure emits one JSON object. This allows downstream tools to process attachments incrementally or re-sync based on a prior run.

The envmon system has only a per-summary JSON writer (`write_json_summary`), which emits aggregate counts and status, not individual records.

During the merge, the question arose: should the unified reporter preserve both types of JSON output, or consolidate to one?

## Decision

Preserve both JSON writers in the unified reporter:

1. **Per-record JSON writer** (`manifest.json`) — each result record emitted as a JSON object, one per line or array element. Enables incremental processing and re-sync workflows.
2. **Per-summary JSON writer** (`write_json_summary`) — aggregate statistics (counts, status, record_count, etc.). Enables job-level reporting and monitoring.

These are complementary, not alternatives. The per-record writer is for data consumers; the summary writer is for operational dashboards.

## Consequences

### Positive

- Backward compatible with harvester's existing per-record JSON manifest
- Supports both operational (summary) and analytical (per-record) use cases
- Enables incremental syncing and retry workflows
- Clear separation of concerns

### Negative

- Two JSON outputs; consumers must choose which to use
- Documentation must explain both formats
- Slightly larger output (both files created per run)

## Alternatives considered

1. **Keep only per-record writer:**
   - **Rejected:** Loses the aggregate reporting and monitoring that per-summary provides.

2. **Keep only per-summary writer:**
   - **Rejected:** Breaks harvester downstream tools that rely on per-record JSON; loses incremental processing capability.

3. **Create a unified JSON format:**
   - **Rejected:** Overcomplicates the schema; separate files are clearer.

## Related decisions

- [ADR-005: Thread-safe QA substrate](0005-thread-safe-qa-substrate.md) — reporter thread-safety covers both writers
- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Specification: [mergeplan-deltas.md §C7](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
- Implementation: [#1 task 2](https://github.com/0bnoxide/AutoGIS/pull/1)
