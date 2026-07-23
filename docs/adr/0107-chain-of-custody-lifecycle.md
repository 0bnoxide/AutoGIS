# ADR-0107: Electronic chain-of-custody lifecycle (Phase 6)

**Status:** Accepted

**Date:** 2026-07-23

## Context

The post-catalog production roadmap (`docs/production-roadmap.md`, ADR-0087)
Phase 6 calls for extending the existing chain-of-custody (COC) *draft* through
a validated lifecycle — generated, released, laboratory-received,
results-received, and reconciled/exception — capturing timestamps, responsible
parties, sample counts, temperature checks, and exception reasons, with an audit
record for every state change. The stated first-slice boundary is explicit:
**no signature platform**.

Today the COC "draft" is a single `COC_Draft` sheet written by
`core/envmon/sampling_event_writer.py` from a `SamplingEventPlan`
(`core/envmon/create_sampling_event.py`). It has no persistent state, no history,
and no way to reconcile what the field planned against what the laboratory
actually received — that reconciliation is done by hand in a spreadsheet, which
is the manual step the phase gate targets.

Constraints: the arcpy-free core invariant is binding; reusable behavior belongs
in `core`; adapters/notebooks consume it; start with the smallest useful slice.

## Decision

Add `autogis/core/envmon/custody.py` — a headless, stdlib-only COC lifecycle —
and wire it through an `envmon coc` CLI subgroup.

**State machine.** Seven states with validated forward transitions; illegal
skips raise `CustodyError`. `reconciled` and `exception` are terminal in this
slice; `exception` is reachable from every active state.

```
draft → generated → released → laboratory_received → results_received → reconciled
                                        ↘ (reconcile) ↗
      (exception reachable from any active state; both terminal)
```

**Audit trail.** Every transition appends an immutable `AuditEntry`
(ISO timestamp, from/to state, responsible-party `actor`, note, free-form
`details` dict). `actor` is required — a blank one is rejected. The `actor`
string *is* the responsible-party record for this slice; cryptographic signing
is deferred.

**Reconciliation.** `reconcile(record, received_ids)` is pure and compares a
COC's planned sample IDs against the IDs the laboratory received, returning
matched / missing / extra. `reconciled` is reachable **only** through the
`reconcile` command, so a COC cannot be marked reconciled without a recorded
comparison — enforcing the gate at the state-machine level. A clean match routes
to `reconciled`; any discrepancy routes to `exception` with the comparison stored
in the audit details.

**Bridge from the existing draft.** `records_from_plan(plan)` groups a
`SamplingEventPlan`'s expected samples by COC number into draft records, reusing
`build_sampling_event_plan` — no new workbook parsing, single source of truth.

**Persistence.** One JSON store per event, keyed by COC number, written
atomically (temp file + `os.replace`). No cross-process lock: a COC store is
single-writer in practice (one operator advances one event's COCs). This is
marked `ponytail:` in-code with the upgrade path (the `run_history` OS
byte-range lock) if concurrent multi-operator writes to one event appear.

**CLI (`envmon coc`, headless/CLOUD):** `generate` (plan → draft → generated),
`advance --to <state> [--set k=v]` (all other transitions, with details for
temperature/carrier/reason), `reconcile` (planned vs received; **exit code 2**
on discrepancy for automation, matching Phase 2's stable-exit-code convention),
and `status`. Registered in `capabilities.TOOLS` (CLOUD) and `_REGISTRY_SEED`
for `envmon list-tools` discovery.

## Consequences

### Positive consequences

- One real event reconciles from sampling plan through laboratory receipt with
  no manual comparison spreadsheet, and every state change carries an audit
  record — the Phase 6 production gate.
- Reuses the existing planner and follows the run-history precedent for
  atomic/append semantics; no new dependency, no core→adapter coupling.
- Stable exit codes make `reconcile` scriptable in automation.

### Negative consequences

- `exception` is terminal this slice: a flagged COC cannot be reopened/resolved
  without editing the store. Upgrade path noted in-code (add an
  `exception → reconciled` resolution transition when a real workflow needs it).
- No cross-process lock; concurrent writers to one event's store could clobber
  (single-writer assumption documented, upgrade path noted).
- `advance --set` records details as free-form key/values (light bool/int/float
  coercion) — no per-state field schema/validation yet.

## Alternatives considered

- **Pure event-sourcing** (store only the append-only event log, derive state on
  read): cleaner audit integrity but forces a replay on every read for no slice
  benefit. Chose current-state-doc + embedded audit list; the audit list *is*
  the append-only record.
- **Reuse `run_history.py`**: it is an append-only tool-run log with no
  per-record mutable state to advance — wrong shape for a lifecycle. Followed its
  atomic/locking precedent instead of bending it.
- **Six bespoke per-state CLI commands**: more surface for no gain. A single
  generic `advance` plus the special `reconcile` (which must compute a
  comparison) covers the lifecycle; the real business rule (legal transitions)
  lives in core.
- **Read the COC_Draft XLSX back to seed records**: couples to sheet layout.
  Rebuilding the plan from configs is deterministic and decoupled.

## Related decisions

- [ADR-0087: Post-catalog production roadmap ordering](0087-post-catalog-production-roadmap.md)
- [ADR-0093: Event status & staleness checker (Phase 2 exit-code convention)](0093-event-status-staleness-checker.md)
- `docs/production-roadmap.md` — Phase 6
- Extends `core/envmon/create_sampling_event.py` + `sampling_event_writer.py`
