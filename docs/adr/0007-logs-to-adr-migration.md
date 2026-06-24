# ADR-007: Migrate project logs to ADR format

**Status:** Accepted

**Date:** 2026-06-23

## Context

Project decisions were historically tracked in:
- `docs/superpowers/plans/` – implementation plans and task tracking
- `docs/superpowers/specs/` – verification specs and reconnaissance reports
- `docs/superpowers/HANDOFF-*.md` – task execution summaries

This format works well for planning but becomes hard to navigate as the project grows. Key decisions are buried in long narratives and task lists.

## Decision

Migrate to Architecture Decision Records (ADR) format:

1. Extract key architectural decisions from plans/specs into numbered ADRs
2. Store ADRs in `docs/adr/` with sequential numbering and kebab-case titles
3. Keep plans/specs as project artifacts (archived, not removed)
4. Use ADRs as the single source of truth for decisions
5. Link from ADRs to related plans/specs/issues/PRs for traceability

ADRs capture the "why" and "what"; plans/specs capture the "how" and detailed verification.

## Consequences

### Positive

- Decisions are discoverable and easy to reference
- ADR format standardizes decision documentation
- Clear distinction between architecture decisions and implementation details
- Links back to plans/specs provide full traceability
- New contributors can quickly understand the project's architecture

### Negative

- Requires maintaining two parallel doc systems (ADRs + legacy plans/specs)
- Duplication of some context between ADRs and old logs
- May fragment decision history (old decisions in plans, new in ADRs)

## Mitigation

- Archive plans/specs with a clear pointer to corresponding ADRs
- Update README and ADR index as new decisions are made
- Link between ADRs and legacy artifacts for traceability

## Related decisions

- All prior ADRs (001–006) capture decisions from migration

## Timeline

- 2026-06-18 through 2026-06-20: Decisions made and executed
- 2026-06-23: ADR infrastructure created, key decisions extracted

## Next steps

1. Review and refine ADRs based on feedback
2. Archive plans/specs with references to corresponding ADRs
3. Update project README to document ADR usage
4. Create template for future ADR submissions
