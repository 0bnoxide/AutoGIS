# Agent decisions — 2026-07-24

Context: The owner asked whether Phase 9 could be headless like the other
`agol` tools, assigned it ("you're the one to tackle phase 9"), and had
already made the packaging call (CLI-first per precedent; Pro-notebook option
struck; AGOL sandbox reminder filed as #307). These are the autonomous
judgement calls made while building slice 1. Durable decision: ADR-0111.
Spec: `docs/superpowers/specs/2026-07-24-phase9-fieldmaps-preflight-design.md`.

## Started Phase 9 slice 1 while Phases 6–8 PRs await merge sign-off

**Decision:** Build slice 1 now (PRs #296/#297/#298 are open, unmerged) on a
fresh worktree branched from current `main`, not stacked on the Phase 6–8
chain.

**Reasoning:** The owner's assignment is the explicit user decision the
roadmap's strict ordering requires. The 2026-07-23 session set the precedent
of starting phase N+1 while phase N awaits sign-off. Nothing in this slice
touches envmon/custody/lab-QA/WQX files, so basing on `main` avoids joining
the #296→#297→#298 rebase chain.

**Revisit if:** the owner wants phase work strictly serialized behind merges.

## Local side of conflict/duplicate checks = CSV snapshot, arcpy leg deferred

**Decision:** Slice 1 reads the local side from `--local-csv` (e.g.
`sync-to-gdb --out-csv`) and `--manifest` (harvester manifest.csv); no arcpy
anywhere. The live-FGDB "pending local edits" leg is slice 2, using
`sync-to-gdb`'s guard-only-when-`--gdb` hybrid pattern.

**Reasoning:** Maximizes the headless-verifiable surface (the point of the
owner's question); the FGDB has no REST surface so its leg can only be
QA'd in a live Pro session anyway — bundling it would couple this slice's
verifiability to Pro time without adding gate coverage.

**Revisit if:** slice 2 lands or a headless FGDB read path is ever approved.

## Extended `edits_where_clause` instead of adding a preflight-local helper

**Decision:** Added a backward-compatible `edit_field` keyword (default
`EditDate`) to `sync_layer.edits_where_clause` and resolve the real field
from `editFieldsInfo.editDateField`.

**Reasoning:** The hardcoded `EditDate` is a shared limitation (Tool 6.2 has
it too); one keyword in the shared function is the root-cause fix, and a
second clause-builder would be the duplicate-implementation smell.

**Revisit if:** 6.2's CLI should also auto-resolve the field (needs a
service fetch before building the clause — left alone here).

## Tool number 7.5, CLOUD, `field` domain

**Decision:** Registered as `("agol fieldmaps-preflight",
"FieldMapsSyncPreflight", "7.5", "CLOUD", "stable", "field", ...)`.

**Reasoning:** 7.x is the Field Maps / field-operations family (7.1
build-fieldmaps … 7.4 inspection report; 7.5 was free). CLOUD matches every
other live-service `agol` tool (CLOUD = no arcpy, not no network). Domain
`field` matches 7.1/7.2.

## Replica details fetched per-replica; age threshold default 7 days

**Decision:** `fetch_replicas` lists via `flc.replicas.get_list()` then reads
each replica with `.get(id)`; `check_replica_age` uses `lastSyncDate` (fall
back `creationDate`, warn if neither) against `--max-replica-age-days`
(default 7, configurable).

**Reasoning:** The REST replicas listing carries only name+ID; age fields
live on the per-replica info resource (doc-verified, epoch ms). 7 days is a
sampling-cadence-shaped default, not a cited standard — it is a CLI option
precisely because it is a judgement call.

**Revisit if:** the owner wants a different default or a config-file source.

## Severity model: pending edits are INFO, structural risks are WARNING

**Decision:** Pending hosted edits count as INFO (they are what sync is
*for*); sync-config gaps, stale/unknown-age replicas, drift, duplicates,
conflicts, missing/stale attachments are WARNING. `--fail-on-findings` exits
1 on any WARNING (audit-schema's `--fail-on-drift` precedent, not the
`coc reconcile` exit-2 convention).

**Revisit if:** go/no-go automation wants pending-edit thresholds to fail.
