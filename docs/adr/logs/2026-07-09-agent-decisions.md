# Agent decisions — 2026-07-09

## Normalize CLI run-history identity at the recording seam

**Decision:** Record the capability-registry command name for nested Click
leaves and resolve site identity from `site_id`, `site`, or `site_config` in
the shared recorder. Leave multi-site manifest runs blank rather than encode
several sites into the scalar `RunRecord.site_id` field.

**Reasoning:** Readiness performs exact tool/site lookup. Per-command fixes
would repeat policy, while inventing a multi-site encoding would change the
run-history schema beyond the two requested bugs.

**Revisit if:** `RunRecord` gains explicit support for multiple site IDs or a
second nested command group needs a different canonical identity.

## Treat ADR-0070 override commands as GUI-reachable

**Decision:** Remove the four executable `manage-callout-overrides` leaves
from GUI `UNREACHABLE`, while retaining the redirect-only
`optimize-callouts` compatibility alias.

**Reasoning:** ADR-0070 and the CLI implementations supersede ADR-0039's dead
end classification. The alias still cannot execute independently.

**Revisit if:** reachability becomes derived from consolidated capability
metadata instead of the hand-maintained map proposed for consolidation by
ADR-0069.
