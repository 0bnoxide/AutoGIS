# ADR-0030 — Autonomous headless tool batches (2026-06-29): PRs #81, #84, #88

**Status:** Accepted
**Date:** 2026-06-29
**Deciders:** Greg / Claude Code
**Recorded:** 2026-07-01 (retroactively — see the note under Context)
**Related:** ADR-0002 (arcpy-free core), ADR-0008 (openpyxl base dep),
ADR-0026 (night-implementer batch 2026-06-27), ADR-0028 (cloud-tools batch 2026-06-28),
ADR-0029 (thin validation adapters)

---

## Context

Continuing the night-batch cadence of ADR-0026 and ADR-0028, three autonomous
headless (arcpy-free) tool batches shipped to `main` on 2026-06-29:

| PR | Commit | Batch | Count |
|----|--------|-------|------:|
| #81 | `f6eefb4` | Headless analytical / reporting tools (exact list per the PR diff) | 10 |
| #84 | `aa58b65` | Arcade-label expressions, event change-log, lab analytical request | 3 |
| #88 | `4f92be0` | Report appendix, list-available-tools registry, analytical-exceedance event, dashboard data-mart | 4 |

These ran in web/cloud sessions where **arcpy is absent**, so every tool was
scoped headless per the ADR-0002 invariant.

**No batch ADR was recorded at the time.** This record is written retroactively
(2026-07-01) during an ADR / decision-log process audit that found the batch-ADR
practice had lapsed after ADR-0028. Per-decision judgment calls for the **#88**
batch are preserved in [`logs/2026-06-29-agent-decisions.md`](logs/2026-06-29-agent-decisions.md)
(relocated from a former `docs/decisions/` path during the same audit). **#81 and
#84 predate a per-batch log**; their decisions are reconstructable only from commit
history and the shipped modules — this ADR is their sole architectural record.

## Decision

Ship the tools above as headless, arcpy-free CLI commands, each registered in
`autogis/runtime/capabilities.py` (`TOOLS` + the new `TOOL_REGISTRY`),
independently committed and TDD-tested. Shared conventions, verifiable in the
merged code:

- **Arcpy-free CLOUD**: pure stdlib, plus openpyxl (ADR-0008) only where Excel
  output is required; CSV / JSON / Markdown otherwise. Core stays importable with
  neither `arcpy` nor `arcgis` present.
- **Dataclass-lite record I/O**: small `@dataclass` records over `csv.DictReader`
  rows (the sibling-batch convention from ADR-0028) rather than the heavier
  canonical `AnalyticalResultRecord` round-trip where GDB field fidelity is not
  needed.
- **Tool discoverability (#88)**: an additive `ToolCapability` dataclass +
  `TOOL_REGISTRY` list added *alongside* the existing `TOOLS` / `requires_arcpy`
  (zero blast radius), a `DRAFT` runtime string for pre-production stubs, and a
  one-directional drift-guard test (`test_registry_commands_exist_in_live_cli`).
- **TDD per feature**: failing tests first, one `tests/test_*.py` per tool.

Per-tool locked decisions for #88 (exceedance grouping by `(location, analyte)`;
tier boundaries; not reusing `build_current_event.select_samples`; dashboard
`Trend` emitted by `GWLevelSummary` per the schema, not `WellStatus`) are in the
2026-06-29 log — not repeated here.

## Consequences

### Positive
- ~17 more catalog + post-roadmap tools shippable without ArcGIS Pro, all reusing
  the established arcpy-free-CLOUD + `QACollector` + TDD pattern (low
  architectural risk).
- `TOOL_REGISTRY` + drift-guard makes the CLI self-describing (`list-tools`) and
  guards command-name drift.

### Negative
- The registry is hand-curated (drift risk, mitigated by the guard — a real drift
  was caught and fixed in-batch; see the log's post-review section).
- #81 and #84 shipped without a per-batch decision log; their architectural record
  is this ADR alone, reconstructed post-hoc.
- **Parallel-session collision:** #88's `export-lab-request` duplicated #84's
  already-merged tool of the same name and was dropped on rebase — a concrete
  instance of the concurrent-session hazard the coordination remediation
  (design-only, PR #99) targets.

## Alternatives considered
- One ADR per PR — rejected; per-day batch ADRs match the ADR-0026/0028 precedent
  with less ceremony, and the relocated free-will logs carry per-decision detail.
- No ADR, treating the decision logs as sufficient — rejected; the daily logs are
  an autonomous-judgment audit trail that **supplements** ADRs, it does not
  replace the architectural record.

## Related decisions
- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0026: night-implementer batch 2026-06-27](0026-night-implementer-batch-2026-06-27.md)
- [ADR-0028: cloud-tools batch 2026-06-28](0028-cloud-tools-batch-2026-06-28.md)
- [Agent-decision log 2026-06-29](logs/2026-06-29-agent-decisions.md)
