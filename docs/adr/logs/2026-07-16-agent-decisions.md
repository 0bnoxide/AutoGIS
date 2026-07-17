# Agent decisions — 2026-07-16

## Package the approved roadmap as a living document plus ADR

**Decision:** Add `docs/production-roadmap.md` as the living, authoritative
phase detail and ADR-0087 as the durable tool-batch ordering decision. Link both
from the existing documentation and session-guide indexes rather than editing a
dated roadmap snapshot.

**Reasoning:** The user approved the roadmap and delegated how to incorporate it.
The docs index explicitly classifies the older top-level roadmap files as
point-in-time snapshots, while the repo requires an ADR for a tool-batch or
phase-gate decision. Separating the detailed living roadmap from the concise ADR
keeps implementation gates discoverable without turning the ADR into a mutable
project plan.

**Revisit if:** AutoGIS adopts a dedicated roadmap directory or issue-tracker
milestones become the authoritative source for production sequencing.
