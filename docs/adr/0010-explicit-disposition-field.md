# ADR-0010: Explicit disposition field for result records

**Status:** Accepted

**Date:** 2026-06-19

## Context

The harvester and envmon systems use different result-tracking models:

1. **Harvester:** outcome counters (`downloaded`, `skipped`, `failed`) — an **outcome axis**
2. **Envmon:** QA records with severity + category — an **issue axis**

A successful download emits a manifest row but no QA record. This creates confusion: how should unified reporting count outcomes?

Options:
- (a) Unified result record carries an explicit **disposition/outcome field** (success, skipped, failed, warning)
- (b) Successes/skips emit INFO-severity QA records under a reserved category

## Decision

The unified result record carries an explicit **disposition** field (outcome axis: `downloaded`, `skipped`, `failed`). QA records remain issue-only (severity + category); successes do NOT emit QA records.

Summary counts group by the disposition field, not by QA severity/category.

## Consequences

### Positive

- Clear separation: disposition (outcome) vs. issues (problems)
- Matches user intuition ("how many downloads succeeded?")
- Preserves existing harness counter vocabulary
- Simpler reporting: disposition is always present; QA records are optional

### Negative

- Unified record has two metadata axes (disposition + QA records)
- Documentation must explain the distinction
- Summary view needs to handle both axes correctly

## Alternatives considered

1. **Emit info-level QA records for successes:**
   - **Rejected:** QA system becomes bloated; success is not an issue, and treating it as one confuses the model.

2. **Replace disposition with QA-only model:**
   - **Rejected:** Loses the outcome vocabulary users already understand.

3. **Keep both systems separate:**
   - **Rejected:** Defers a decision that must be made before the merge.

## Related decisions

- [ADR-005: Thread-safe QA substrate](0005-thread-safe-qa-substrate.md) — QA records remain issue-only
- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Decision: [mergeplan-deltas.md §H2](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
- Implementation: [#1 task 2](https://github.com/0bnoxide/AutoGIS/pull/1)
