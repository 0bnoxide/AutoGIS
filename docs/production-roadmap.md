# Post-catalog production roadmap

**Status:** Accepted

**Approved:** 2026-07-16

This is the authoritative production sequence for complementary AutoGIS
capabilities after completion of the numbered environmental-monitoring catalog.
It is intentionally a sequence of production gates, not a promise to build every
idea concurrently.

## Governance

- Each capability owns one phase and must reach its production gate before the
  next phase starts. Reordering or parallel fast-tracking requires an explicit
  user decision recorded in the session guide and an ADR when architectural,
  structural, invariant, or tool-batch scope changes.
- Start each phase with the smallest useful slice. Do not pre-build branching
  workflow languages, schedulers, notification services, or other speculative
  infrastructure.
- Reusable behavior belongs in `autogis.core`; adapters and notebooks consume
  it. Notebooks are review and exploration surfaces, not a fourth implementation.
- The arcpy-free import invariant remains binding. Any LOCAL work follows
  ADR-0077 documentation verification and a real ArcGIS Pro acceptance run.
- Deferred groups remain deferred. This roadmap does not reopen the AI-assisted
  tools or any other blocked group.

## Production gate shared by every phase

A phase is production-ready only when its applicable items are complete:

1. An approved design/ADR exists when the phase changes schemas, architecture,
   invariants, or tool-batch scope.
2. Core behavior and CLI wiring have focused tests and the full headless suite
   is green.
3. Runtime metadata, run-history identity, help text, and user documentation are
   updated.
4. The feature succeeds end-to-end against the sanitized reference event.
5. LOCAL paths are doc-verified against current Esri documentation and pass a
   manual ArcGIS Pro acceptance run.
6. Migration, rollback, data-loss, security, and audit implications are either
   handled or explicitly documented as not applicable.

## Phase 1 — ArcGIS Pro qualification runner

Build a repeatable local qualification command that instantiates every `.pyt`
tool, validates parameter construction, exercises representative arcpy seams
against a scratch geodatabase, and reports the Pro version, extensions, passes,
failures, and skips in JSON plus a human-readable report.

**Production gate:** the runner completes on the currently installed Pro
release, and detects a deliberately broken parameter definition and a
deliberately failing scratch-GDB operation. *(Amended from "Pro 3.5 and the
current preferred release" by owner decision 2026-07-19, recorded in ADR-0091:
no Pro 3.5 install exists; the 3.5 compliance floor remains an authoring-time
doc-verification duty per ADR-0077 that a runtime pass cannot prove. The
runner stays version-agnostic so a 3.5 leg can be added later.)*

## Phase 2 — Event status and staleness checker

Add `envmon event-status` to compare source hashes, configuration, run history,
snapshots, approvals, and package manifests. Report each expected artifact as
current, stale, missing, failed, or awaiting review, including the upstream
change that caused the state. Provide stable exit codes for automation.

**Production gate:** changes to an input workbook, site configuration, screening
levels, figure specification, and approved model each invalidate only the
correct downstream artifacts without modifying production data.

## Phase 3 — Site onboarding bootstrap

Add `envmon init-site` to copy versioned templates, create the site/schedule/
parser/figure-spec skeleton, identify unverified anchors and missing regulatory
content, and run existing validators. The first slice is a CLI with `--dry-run`,
not a new wizard framework.

**Production gate:** a sanitized site can be initialized, validated, and handed
to an operator without manually assembling its directory structure.

## Phase 4 — Monitoring-event review notebook

Ship one supported notebook that imports existing core behavior and presents an
event's import summary, QA findings, completeness, screening, comparisons,
trends, map-ready data, readiness state, and reviewer decision. Record the
AutoGIS version and input hashes. Keep business rules out of notebook cells.

**Production gate:** restart-and-run-all succeeds against the sanitized reference
event with no hidden state, local credentials, client data, or duplicated domain
logic.

## Phase 5 — Saved workflow recipes

Extend the existing GUI workflow builder with save/load for linear YAML recipes,
shared site/event/GDB/output parameters, and the existing halt, warning-pause,
checkpoint, and cancellation behavior. Validate CLOUD/HYBRID/LOCAL ordering.
Defer branching, expression languages, internal scheduling, and a general
output-binding DSL until a demonstrated workflow needs them.

**Production gate:** monitoring-event processing and RTK-to-CAD recipes can be
saved, reopened, validated, and repeated deterministically.

## Phase 6 — Electronic chain-of-custody lifecycle

Extend the existing COC draft through generated, released, laboratory-received,
results-received, and reconciled/exception states. Capture timestamps,
responsible parties, sample counts, temperature checks, and exception reasons.
Do not add a signature platform in the first slice.

**Production gate:** one real event reconciles from sampling plan through
laboratory receipt without a separate manual comparison spreadsheet, and every
state change has an audit record.

## Phase 7 — Longitudinal laboratory QA

Trend blank detections, surrogate and spike recovery, duplicate RPD, reporting-
limit changes, and qualifier frequency by laboratory, method, matrix, and
analyte. Begin with deterministic rules and CSV/XLSX outputs; do not automate
professional conclusions.

**Production gate:** results reproduce a manually reviewed set of historical
events and every threshold is configurable, cited, and represented in QA output.

## Phase 8 — Outbound WQX/regulatory exchange

Add the outbound complement to the WQX reader: map canonical records to required
submission fields, validate identifiers/units/methods/qualifiers/coordinates,
produce deterministic submission files, and package rejection details plus
source/configuration provenance.

**Production gate:** a sanitized package passes the target validator or a
documented agency preflight review, and failed records cannot silently disappear.

## Phase 9 — Field Maps synchronization preflight

Add a read-only report covering pending local and hosted edits, replica or
offline-area age, schema drift, missing/stale attachments, duplicate identities,
and potential conflicts before synchronization. Keep conflict resolution under
human control in the first release.

**Production gate:** a non-production hosted service with intentionally created
conflicts produces a complete preflight report without changing either side.

## Phase 10 — Portfolio monitoring digest

Aggregate new exceedances, missing scheduled work, stale artifacts, failed
readiness gates, COC exceptions, laboratory-QA changes, open reviewer comments,
and field-sync warnings into JSON and self-contained HTML. External schedulers
and messaging systems handle delivery.

**Production gate:** every digest total reconciles to its source event-status,
QA, COC, reviewer, and portfolio records, and the same inputs produce the same
digest.

## Milestones

- **Production confidence:** Phases 1–2
- **Usability and repeatability:** Phases 3–5
- **Environmental operations:** Phases 6–8
- **Field and portfolio operations:** Phases 9–10

The first user-facing milestone is the completion of Phase 4: a qualified Pro
installation, explainable event status, repeatable site onboarding, and an
interactive monitoring-event review surface.

## Optional add-on track

The accepted [Survey123 optional add-on roadmap](survey123-add-on-roadmap.md)
defines its own sequential phases and milestones for opt-in live Survey123
integration (ADR-0112). It does not delay, reorder, or satisfy Phases 1–10
above, and accepting its planning direction does not start implementation.
