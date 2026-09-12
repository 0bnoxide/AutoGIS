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
