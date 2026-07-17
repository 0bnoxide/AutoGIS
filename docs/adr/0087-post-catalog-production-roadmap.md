# ADR-0087: Post-catalog complementary capabilities production roadmap

**Status:** Accepted

**Date:** 2026-07-16

## Context

AutoGIS has completed the numbered environmental-monitoring catalog and now has
a broad set of intake, QA, analysis, cartography, reporting, field, AGOL, and
administrative tools. Additional isolated commands would deepen the catalog
without addressing the larger operational gaps: ArcGIS Pro qualification,
artifact freshness, repeatable onboarding and review, custody tracking,
regulatory exchange, and portfolio oversight.

The user approved a roadmap in which each complementary capability owns its own
production phase and explicitly removed separately in-flight work from this
roadmap. The decision needs a durable record because it establishes tool-batch
ordering and phase gates.

## Decision

Adopt [`../production-roadmap.md`](../production-roadmap.md) as the authoritative
post-catalog production roadmap, in this order:

1. ArcGIS Pro qualification runner
2. Event status and staleness checker
3. Site onboarding bootstrap
4. Monitoring-event review notebook
5. Saved workflow recipes
6. Electronic chain-of-custody lifecycle
7. Longitudinal laboratory QA
8. Outbound WQX/regulatory exchange
9. Field Maps synchronization preflight
10. Portfolio monitoring digest

Each capability is a separate production gate. The next phase starts only after
the current phase meets the shared and feature-specific exit criteria, unless
the user explicitly approves a reordering or parallel fast-track. Each phase
begins with the minimum useful slice; feature-specific specs and implementation
plans are written only when that phase opens.

Reusable logic remains in `autogis.core`. Notebooks and adapters consume that
logic rather than reimplementing it. LOCAL work remains subject to ADR-0077.
This roadmap does not reopen deferred groups.

## Consequences

### Positive consequences

- Production confidence and explainable artifact state precede higher-level
  automation.
- Site onboarding and review are proven before workflow recipes generalize them.
- Custody, laboratory QA, and regulatory exchange build on stable canonical data.
- Field and portfolio summaries consume already-established status and audit
  records.
- Each phase has a concrete stopping point and cannot quietly become a broad
  platform project.

### Negative consequences

- Valuable later capabilities wait behind earlier production gates.
- A user decision is required to reorder phases when field priorities change.
- Each opened phase may require an additional ADR or schema migration before
  implementation begins.

## Alternatives considered

**Develop several capabilities in parallel.** Rejected because multiple schema
and operational seams would move before the production-confidence foundation is
proven.

**Treat the ideas as an unordered backlog.** Rejected because it would repeat
the repo's earlier fast-tracking problem and provide no production exit gates.

**Start with a general workflow language or scheduler.** Rejected under YAGNI;
the existing linear workflow runner should gain only demonstrated capabilities.

**Put analytical logic in notebooks.** Rejected because it would create a fourth
implementation surface and weaken the shared-core invariant.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0050: unified GUI adapter direction](0050-unified-gui-adapter-direction.md)
- [ADR-0063: GUI workflow builder](0063-gui-workflow-builder.md)
- [ADR-0077: arcpy API-currency policy](0077-arcpy-api-currency-policy.md)
- [ADR-0080: WQX Step-2 import](0080-wqx-step2-import.md)
- [ADR-0083: report template system](0083-report-template-system.md)
- [Agent decision log](logs/2026-07-16-agent-decisions.md)
