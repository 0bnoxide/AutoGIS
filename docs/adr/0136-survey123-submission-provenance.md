# ADR-0136: Survey123 submission provenance tracer

**Status:** Proposed

**Date:** 2026-09-12

## Context

Issue #414 records an incident where field submissions existed upstream of
a client's visible endpoint. Manual device database inspection was required
to establish provenance and produced-record counts. The owner explicitly
requested implementation on 2026-09-12, authorizing this optional-track tool.
The other Survey123 phase gates remain unchanged.

## Decision

Add `envmon trace-survey123` and one stdlib-only core module. Reuse Phase 2's
`LayerPull` and canonical `payload_hash`. Read closed SQLite exports through
a read-only transaction; select one exact payload root. Read complete saved
snapshots in the base install or query single layer URLs with the existing
lazy profile provider and optional `survey123` dependency. Complete pulls
compare OBJECTID inventories before and after retrieval; delta streams are
not accepted as absence evidence.

Match exact configured stable fields, normalizing UUID representation only.
Preserve duplicate and invalid-ID evidence, exclude ambiguous identities from
new-work counts, and never fabricate IDs. Parent submissions are the count
unit. Inbox copies, drafts, edits, and unknown edit modes cannot become
new-ready quantities. Keep per-leg observation counts distinct from the
device-derived new-work subsets.

Write a JSON evidence report, records CSV, and counts CSV together in a new
directory. Refuse existing outputs; do not modify inputs, portal data, or
sync state. Record source hashes, timestamps, and per-record evidence without
raw form fields or credentials. Use semantic exit 2 for report findings.

Absence means not visible in the supplied access scope and observation time.
It does not establish a QA hold or historical delivery. DRAFT status remains
until real-device and live non-production acceptance. Full operator contract:
[submission provenance](../survey123-submission-provenance.md).

## Consequences

### Positive consequences

- Offline transport reconciliation is installable without ArcGIS or ArcPy.
- Progress counts retain an inspectable identity/evidence trail and do not
  count downloaded inbox copies or repeated observations as new work.
- Explicit scope, timestamps, and unknowns prevent overclaiming delivery.

### Negative consequences

- Operators must select the correct payload root and identity fields and
  attest completeness for saved snapshots; the tool cannot infer a crosswalk.
- All records for the selected source are held in memory; streaming/external
  joins are deferred until real exports demonstrate a memory constraint.
- No historical payload-delivery proof, attachment/repeat tracing, or live
  cross-server transaction. Real device schemas may require a later reader
  revision; current format support is documented and fails closed.

## Alternatives considered

- Reuse incremental JSONL directly: rejected because a delta cannot prove
  current absence and contains multiple operations on the same identity.
- Extend five-source sampling-event reconciliation: rejected because its
  identities, sampling lifecycle, and outcome precedence serve another job.
- Guess device fields or synthesize GlobalIDs: rejected because guesses
  would destroy the evidence the tool is intended to provide.

## Related decisions

- [ADR-0112](0112-survey123-optional-add-on-roadmap.md)
- [ADR-0116](0116-survey123-phase2-submission-sync.md)
- [ADR-0123](0123-survey123-phase3-event-reconciliation.md)
- [Issue #414](https://github.com/0bnoxide/AutoGIS/issues/414)
