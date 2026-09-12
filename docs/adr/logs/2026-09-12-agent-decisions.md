# Agent decisions — 2026-09-12

## Issue #414: observed presence and conservative progress counts

**Decision:** Implement the owner-authorized tracer with a documented device
format and complete endpoint snapshots. Preserve DRAFT and live-acceptance
limits. Count new-ready parent identities separately from all observed IDs;
exclude inbox, draft, edits, unknown edit modes, and ambiguities.

**Reasoning:** Esri documents the table/box states and links a root-keyed JSON
reader. This is sufficient for testable tooling, but not proof of a real
device's schema. Endpoint absence cannot prove a QA hold. Reusing sync's
incremental outputs would falsely interpret unobserved records as absent.

**Revisit if:** A sanitized export demonstrates another schema or the owner
requires a different, explicitly validated production/billing contract.

Architectural record: [ADR-0136](../0136-survey123-submission-provenance.md).

## PR #537: preserve closed WAL-mode evidence directories

**Decision:** Add SQLite `immutable=1` to the read-only device URI while
retaining nonempty WAL/journal rejection and before/after main-file hashes.

**Reasoning:** Cold review and a real CLI regression reproduced that `mode=ro`
creates `-wal`/`-shm` beside a checkpointed WAL-mode export. SQLite's documented
immutable mode prevents those writes for the already-required closed,
consolidated export. The regression compares the entire source directory
before and after tracing, including file bytes.

**Revisit if:** Reading live field-app databases becomes an explicit requirement;
that needs a consistent export/backup acquisition step instead of immutable I/O.

## PR #537: recheck sidecars after device verification

**Decision:** Reuse the active-WAL/journal guard after the read and final
main-file hash check, before accepting device observations.

**Reasoning:** Automated review found that concurrent commits can live only
in a new WAL, leaving the main-file hash unchanged. A regression with a real
SQLite writer reproduced a successful incomplete report and now fails closed.

**Revisit if:** Live acquisition is authorized; pre/post checks do not replace
the required closed-export contract or establish a continuous source lock.
