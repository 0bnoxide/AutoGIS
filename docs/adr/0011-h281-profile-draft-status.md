# ADR-011: H281 profile draft status and pre-production gate

**Status:** Accepted

**Date:** 2026-06-19

## Context

The H281 (Glasgow) environmental monitoring parser profile is delivered as part of the envmon suite. However, it has never been verified against real H281 workbook data from the actual field campaign.

The profile includes:
- DRAFT banner and TODO markers in the code
- Documented assumptions and unverified rules
- A gate in Tool 1 (Inspect Workbook) that requires human review before importing H281 data for the first time

The question: should the H281 profile be included in the merged codebase? If so, what guards must be maintained?

## Decision

Include the H281 profile in the merged codebase. Preserve and maintain (do not regress) all existing guards:

1. **DRAFT banner** — clearly mark the profile as unverified
2. **`_TODO` markers** — highlight unverified rules and assumptions
3. **Human-review gate in Tool 1** — require manual review before first H281 import
4. **README documentation** — document that real-workbook verification is a manual pre-production task

These guards remain owned by the project team; the merge does not attempt to verify them.

## Consequences

### Positive

- H281 profile is available for testing and development
- Guards prevent accidental misuse on production data
- Clear documentation sets expectations for pre-production verification
- Team retains flexibility to refine the profile as real data becomes available

### Negative

- H281 tools cannot be promoted to production until verification is complete
- Users may be confused by the DRAFT status and gates
- Maintenance burden to keep the profile up-to-date as tools evolve

## Mitigation

- Documentation and comments make the draft status obvious
- Tool 1 gate with clear error message prevents accidental production use
- README flag for the team: real-workbook verification remains a manual, pre-production task

## Alternatives considered

1. **Exclude H281 profile from the merge:**
   - **Rejected:** Profile is complete enough for development and testing; guards are already in place.

2. **Remove all guards and promote to production:**
   - **Rejected:** Violates the team's pre-production verification requirement; too risky.

3. **Re-verify H281 as part of this merge:**
   - **Deferred:** Out of scope for the envmon merge; remains a team responsibility.

## Related decisions

- [ADR-004: Envmon suite merge](0004-envmon-suite-merge.md)

## Issues/PRs

- Verification: [mergeplan-deltas.md §H3](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
- Carried forward from: H281_Glasgow.yaml, config/parser_profiles/
