# ADR-0031 — Autonomous headless tool batches (2026-06-30): PRs #92, #93, #95, #96

**Status:** Accepted
**Date:** 2026-06-30
**Deciders:** Greg / Claude Code
**Recorded:** 2026-07-01 (retroactively — see the note under Context)
**Related:** ADR-0002 (arcpy-free core), ADR-0008 (openpyxl base dep),
ADR-0028 (cloud-tools batch 2026-06-28), ADR-0030 (autonomous batches 2026-06-29)

---

## Context

Four more autonomous headless batches shipped to `main` on 2026-06-30, extending
the ADR-0030 cadence:

| PR | Commit | Batch |
|----|--------|-------|
| #92 | `4074bae` | gw-level-summary, build-gwe-event, select-soil-intervals, gen-synthetic-workbook, build-analytical-key |
| #93 | `0ed989f` | source-doc registry, drone flight, drone products, boring logs, RTK→well-elevation |
| #95 | `5d1d1ea` | trend charts, reviewer comments, soil intervals, comparison-excel, job queue |
| #96 | `c364a9a` | batch-import, migrate-legacy, draft-profile, sampling-plan, reconcile-field-lab |
| #97 | `82e5942` | **revert** — drops #92's `select-soil-intervals` (tool 4.8) in favour of #95's design |

As with ADR-0030, **no batch ADR was recorded at the time**; this is written
retroactively (2026-07-01) during the ADR-process audit. Per-decision judgment
calls for the **#95** batch are in
[`logs/2026-06-30-agent-decisions.md`](logs/2026-06-30-agent-decisions.md)
(relocated from `docs/decisions/` during the audit; it documents the #95 batch
specifically). #92, #93, and #96 predate a per-batch log; their decisions are
reconstructable from commit history and the shipped modules.

The #93 batch introduces the first **HYBRID** field/intake tools: a headless
validation/QA half (`validate-drone-products`, `validate-boring-logs`) plus a
LOCAL geodatabase-writing half (`import-drone-products`, `import-boring-logs`),
and `survey-to-well-elevation` / `register-drone-flight` that run headless for a
dry-run/CSV path and guard on `arcpy` for the `--gdb` write path.

## Decision

Ship the tools above under the same conventions as ADR-0030 (arcpy-free CLOUD
core, dataclass-lite CSV/JSON/openpyxl I/O, `TOOLS` + `TOOL_REGISTRY`
registration, TDD per feature, registry drift-guard). Additional decisions
specific to this day:

- **HYBRID split (#93)**: tools that ultimately write a geodatabase keep all
  transformation/validation logic in an arcpy-free, unit-tested core half and
  isolate the arcpy `InsertCursor`/write half behind the `_guard()` redirect
  (matching the LOCAL-tool pattern). The headless half is exposed as its own
  `validate-*` command so the QA is runnable in CI.
- **`#97` revert (supersession)**: `select-soil-intervals` was implemented twice
  in parallel (#92 tool 4.8 and #95); #92's version was reverted in favour of
  #95's design rather than merging both. Recorded here as a supersession so it is
  not re-litigated; rationale is in the #97 commit body and the 2026-06-30 log.
- **Fresh-pull discipline (#95)**: the #95 session synced `main`, verified no open
  PRs, and confirmed each target module was absent before branching — a direct
  response to ADR-0030's `export-lab-request` collision.

Per-tool locked decisions and three plan-bug fixes (trend-charts empty-input
crash; soil-interval ND/NO_DATA split; comparison-excel `freeze_panes`
blank-row off-by-one) plus the pre-PR adversarial-review findings are in the
2026-06-30 log — not repeated here.

## Consequences

### Positive
- ~20 more catalog + intake tools, opening the field/intake (§2/§8) and
  cartography-intake tracks; the HYBRID split keeps GDB-writing tools testable
  headless while honouring ADR-0002.
- The #95 batch ran a two-agent adversarial review (envmon-spec-checker +
  pr-reviewer) before the PR, catching a producer/consumer contract mismatch and
  a ≥20-point chart-corruption bug — a repeatable pre-PR gate.

### Negative
- #92, #93, #96 shipped without a per-batch decision log; this ADR is their sole
  architectural record.
- The parallel `select-soil-intervals` implementation (#92 vs #95) wasted work and
  required a revert (#97) — again the concurrent-session hazard; the coordination
  remediation (design-only, PR #99) targets it.

## Alternatives considered
- One ADR per PR — rejected for the same reason as ADR-0030 (per-day batching +
  free-will logs).
- Keeping both `select-soil-intervals` implementations — rejected via #97;
  duplicate tools for one roadmap slot are supersession, not co-existence.

## Related decisions
- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0030: autonomous headless batches 2026-06-29](0030-autonomous-headless-batches-2026-06-29.md)
- [Agent-decision log 2026-06-30](logs/2026-06-30-agent-decisions.md)
