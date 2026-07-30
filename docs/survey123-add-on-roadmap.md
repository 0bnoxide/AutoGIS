# Survey123 optional add-on roadmap

**Status:** Accepted planning direction

**Approved:** 2026-07-25

This roadmap defines an opt-in Survey123 lifecycle for AutoGIS: validate a form,
read field submissions safely, reconcile them with planned and laboratory work,
then add controlled publishing, event processing, field-form packs, and report
automation.

It is an optional track beside the authoritative
[post-catalog production roadmap](production-roadmap.md). It does not delay,
reorder, or satisfy that roadmap's phases. The phases below are sequential
within this track; starting or fast-tracking implementation requires an explicit
user decision.

## Existing foundation

AutoGIS already provides:

- `envmon build-survey-form` for headless XLSForm generation;
- `envmon create-sampling-event` for pre-field planning;
- `envmon route-survey123` for exported submission routing into a geodatabase;
- `envmon reconcile-survey123-lab` for field-to-laboratory comparison; and
- adjacent attachment harvesting, Field Maps, AGOL, QA, run-history, and
  reporting capabilities.

This track closes the missing managed-lifecycle seam. It extends those tools
rather than replacing their schemas or creating a parallel Survey123 product.

## Installation and architecture contract

The add-on remains part of the `autogis` distribution:

```powershell
pip install autogis
# Existing headless and export-driven Survey123 tools

pip install "autogis[survey123]"
# Live Survey123 / ArcGIS Online integration
```

- The base install keeps XLSForm generation, static validation, exported-file
  normalization, and offline reconciliation.
- The `survey123` extra is introduced with the first live portal command and
  carries the ArcGIS API for Python dependency already used by the `cloud`
  extra. `autogis[cloud]` remains supported for compatibility.
- Commands remain visible without the extra. A live command invoked without it
  fails before network work with the exact install hint.
- Core contracts, normalization, reconciliation, idempotency, and report-job
  state remain arcpy-free and arcgis-free.
- Authentication and hosted-service calls use the lazy provider in
  `autogis.runtime.sessions`; neither `arcgis` nor credentials are loaded at
  module import.
- ArcPy is required only for an explicitly requested local-GDB write.
- AutoGIS processes webhook payloads but does not become an always-running
  webhook host, scheduler, notification service, or secret store.

## Shared gate for every phase

A phase is complete only when:

1. its public data contract and migration/rollback behavior are documented;
2. pure behavior has focused arcpy-free tests and import-boundary coverage;
3. retries are idempotent and cannot silently duplicate, discard, or relink
   records;
4. credentials, sharing, personally identifiable information, attachments, and
   audit implications are handled or explicitly not applicable;
5. live behavior succeeds in a non-production ArcGIS organization; and
6. runtime metadata, run history, CLI help, install guidance, and operator
   documentation are current.

## Phase 0 — Client and submission contract

Choose the supported Survey123 client baseline and pin the existing SampleID
calculation shared by event planning, XLSForm generation, normalization, and
reconciliation.

The first slice targets Survey123 Connect plus the field app. A compatibility
matrix records which generated constructs are also supported by Survey123
Studio/Mobile; AutoGIS does not assume client parity.

**Exit gate:** the SampleID contract is identical across all existing producers
and consumers, and remains `arcgis`- and `arcpy`-free.

> **Amended by ADR-0113 (2026-07-25):** the canonical submission envelope
> (survey/item/layer identity, GlobalID, edit time, operation type, repeat path,
> attachment metadata, raw-payload hash, source provenance) has moved from this
> phase to **Phase 2**, where its first consumer lives, and the envelope leg of
> this exit gate moved with it. Building it here would mean designing an
> envelope against no reader — every field shape would be a guess, and the first
> real puller would relitigate it. Phase 5's gate depends on the envelope and so
> now depends on Phase 2 rather than Phase 0; the strict phase ordering is
> unaffected, since 2 still precedes 5. The SampleID leg was delivered in
> Phase 0 slice A (ADR-0113).

## Phase 1 — Form validation and schema drift

Add headless form validation and schema comparison before any publication
feature. Validate XLSForm names, choices, calculations, repeats, required
questions, config references, SampleID behavior, and compatibility with a saved
feature-layer definition. Classify proposed changes as safe, review-required,
or destructive.

Minimum commands:

```text
autogis envmon validate-survey-form
autogis envmon diff-survey-schema
```

**Exit gate:** known-breaking question, repeat, choice, type, and feature-layer
changes are detected from saved artifacts; the commands make no portal changes
and run in the base install.

## Phase 2 — Incremental submission synchronization

Add the first live, read-only command. Pull new and changed submissions by
stable identity and edit timestamp; include geometry, repeats, attachments,
edits, and deletions. Persist a checkpoint only after a durable normalized
output is written. Support bounded replay and a dry-run summary.

Define here the one canonical submission envelope — survey/item/layer identity,
GlobalID, edit time, operation type, repeat path, attachment metadata,
raw-payload hash, and source provenance — designed against this puller, its
first real consumer (relocated from Phase 0 by ADR-0113).

The first slice writes JSON/CSV staging artifacts and feeds the existing
normalizer. Direct GDB writes remain an explicit downstream LOCAL operation.

**Exit gate:** an interrupted run resumes without loss, a repeated run creates
no duplicates, edits and deletions remain visible, attachments reconcile by
stable identity, counts match a non-production hosted survey, and
representative new, edited, deleted, repeated, attachment-bearing, and replayed
submissions normalize into the envelope without importing `arcgis` or `arcpy`.

## Phase 3 — Planned, field, COC, lab, and GDB reconciliation

Extend the existing field-to-lab comparison into one event reconciliation:

```text
sampling plan -> Survey123 submission -> COC -> laboratory result -> GDB record
```

Report missing, duplicate, unexpected, mistyped, wrong-matrix, wrong-analyte,
dry/inactive-location, date, attachment, and status exceptions. Exact stable
keys decide matches; fuzzy matching may suggest a candidate but never changes
an identity automatically.

**Exit gate:** a sanitized event reconciles every planned and observed sample to
one explicit outcome, totals balance across all five sources, and no ambiguous
match is silently accepted.

## Phase 4 — Managed publishing and promotion

Publish or update generated surveys only after the read path and drift
classification are proven. Add dry-run publication plans, dependency and
sharing audits, existing-feature-service binding, and DEV -> QA -> PROD
promotion. Block destructive schema changes unless separately approved with a
documented rollback.

**Exit gate:** the same form can be promoted through a sandbox organization
without orphaning its form, feature layer, views, web maps, attachments, report
templates, or sharing; a deliberately destructive change is blocked before
mutation.

## Phase 5 — Webhook processing and replay

Add a pure payload processor plus adapter wiring for Survey123 webhook events.
Validate the source and operation, normalize through the Phase 2 envelope
(relocated from Phase 0 by ADR-0113), deduplicate by stable event identity,
record processing state, and support failure replay. External hosting and automation products own HTTP uptime,
delivery, scheduling, and human notification.

**Exit gate:** duplicate, delayed, out-of-order, edited, and deleted webhook
events converge on the same state as a full Phase 2 synchronization, with
failed payloads retained for bounded replay.

## Phase 6 — Composable field-form packs

Refactor reusable XLSForm question groups only when a second real form needs
them. Ship the sampling-v2 pack first: purge and stabilization repeats,
water-quality readings, bottle/preservative checks, QC sample workflows,
equipment/calibration details, well condition, access issues, photos,
signatures, barcode/QR capture, and offline location confirmation.

After that gate, use the same contracts for well inspection and boring/logging
packs rather than building one universal mega-form.

**Exit gate:** the sampling-v2 pack completes an offline field exercise, shared
fields retain the same names and meanings as the canonical envelope, and every
generated construct passes the Phase 0 client matrix and Phase 1 validator.

## Phase 7 — Feature reports and operational health

Manage feature-report templates, validate template syntax, estimate credits,
submit and poll jobs, download outputs, and record report provenance. Add
read-only health checks for survey dependencies, sharing, webhooks, sync
checkpoints, failed payloads, stale templates, and schema drift.

The first supported outputs are an event packet and well-inspection report.
Daily drilling reports become eligible after the boring/logging form pack
passes Phase 6.

**Exit gate:** reports regenerate deterministically from a frozen sanitized
event, every external job and credit-bearing action is visible before execution,
and operational health failures appear in run history without requiring a
separate monitoring service.

## Milestones

### Milestone A — Safe form foundation (Phases 0–1)

AutoGIS has a stable client/submission contract and can reject incompatible or
destructive form changes before portal access. This milestone remains available
in the base install.

### Milestone B — Trusted field-data intake (Phases 2–3)

The first installable live add-on release. Operators can synchronize a hosted
survey read-only and reconcile every planned, field, COC, laboratory, and GDB
record without manual export comparison.

### Milestone C — Managed Survey123 lifecycle (Phases 4–5)

Forms move through controlled environments, and webhook processing converges
with full synchronization while preserving replay, audit, and rollback paths.

### Milestone D — Field-operations expansion (Phases 6–7)

Reusable form packs and feature reports cover richer sampling and inspection
work without turning AutoGIS into a hosting, scheduling, or messaging platform.

## Explicit non-goals

- A separate `autogis-survey123` distribution or plugin framework.
- Automatic destructive feature-layer migration.
- Fuzzy or order-dependent identity changes.
- A bundled webhook server, scheduler, notification platform, or secret store.
- Replacing Survey123 Connect, ArcGIS Online administration, or professional
  field/laboratory review.
- Starting implementation merely because this planning roadmap is accepted.

## Gate-change log

Moved here from `CLAUDE.md` on 2026-07-29; record each new gate change here.

- 2026-07-26 — Phase 0 slice A (lifecycle SampleID contract) shipped via
  ADR-0113 (PR #359, owner-merged); envelope leg deliberately deferred to
  Phase 2 (first consumer). An explicit owner decision, not a default
  fast-track — the remaining Phase 0 scope and Phases 1-7 each get their own
  dated entry here as they ship.
- 2026-07-25 — Phase 2 (incremental submission sync) started by explicit user
  direction; slice 1 implemented (ADR-0116: canonical envelope +
  `envmon sync-survey123` + `survey123` extra), live non-production gate legs
  owner-gated.
- 2026-07-26 — Phase 1 (form validation and schema drift) shipped via
  ADR-0115 (PR #364): `validate-survey-form` and `diff-survey-schema`, both
  headless with no portal I/O. Started on an explicit user instruction, not by
  the roadmap's own momentum. (Phase 2 was separately user-directed and has
  its own entry above.)
