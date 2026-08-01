# ADR-0005: Thread-safe QA and reporting substrate

**Status:** Accepted

**Date:** 2026-06-19

## Context

The QA system needed to support:

1. Both harvest and envmon modules recording results
2. Thread-safe concurrent processing (parallel harvests, parallel analysis)
3. Rich disposition tracking (outcome, issue severity, provenance)

The original QACollector had no thread safety guarantees. Writing records and iterating them simultaneously caused data corruption in concurrent scenarios.

## Decision

Implement a unified, thread-safe `QACollector` substrate with:

1. **Thread-safe record writing** (`QACollector.add_record()` with locks)
2. **Unified disposition vocabulary:**
   - `outcome`: disposition of the record (success, warning, error, skipped, failed)
   - `provenance`: reserved tracking info (checksum, geometry, source_table, relationship_id, etc.)
3. **Reporter interface** for standardized output formatting (JSON summary, CSV export)
4. **RunSummary** as a small summary view over QA records (counts by outcome/issue)

## Consequences

### Positive

- Concurrent harvest/analysis safe from data corruption
- Unified QA system across harvest and envmon
- Rich provenance tracking for debugging and audits
- Clear outcome/issue vocabulary

### Negative

- Locks add overhead (mitigated for non-concurrent workflows)
- Provenance fields in QARecord ≠ harvester provenance (confusing naming; needs clarification)
- Outcome-axis vs. issue-axis mismatch in RunSummary (deferred clarification)

## Known gaps (follow-up ADRs)

1. Provenance field definition unclear (harvester provenance vs. QA record provenance)
2. RunSummary disposition logic needs refinement (outcome-axis vs. issue-axis)
3. Thread-safe surface extends beyond QACollector (needs audit of all concurrent call sites)

## Related decisions

- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Implementation: [#1 task 2](https://github.com/0bnoxide/AutoGIS/pull/1)
- Commit: `d0efcec` (QA/Reporter substrate)
