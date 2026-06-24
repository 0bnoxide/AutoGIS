# ADR-012: Reserved provenance columns for future use

**Status:** Accepted

**Date:** 2026-06-19

## Context

As the AutoGIS suite grows, richer provenance tracking is needed for debugging, auditing, and reproducibility. The harvester and envmon tools may eventually need to record:

- **Checksum + algorithm** — file integrity verification (SHA256, MD5, etc.)
- **Geometry** — WKT or GeoJSON representation of the feature/attachment location
- **Source table** — which database/layer the attachment came from
- **Relationship ID** — tracking parent-child relationships in geodatabases

Currently, these fields are not used. The question: should we define them now and reserve the column names?

## Decision

Define and reserve the following provenance column names in the unified result record, even though they are not yet populated:

1. `checksum` + `algorithm` — file integrity hash
2. `geometry` — WKT/GeoJSON of source feature location
3. `source_table` — origin table/layer name
4. `relationship_id` — parent-child relationship tracker in GDB

Leave these fields **empty/null** in current output. This reserves the schema for future tools without breaking existing consumers.

## Consequences

### Positive

- Future tools can populate these fields without schema migration
- Consumers can start writing code to handle these columns (even if null)
- Clear path for adding features like attachment deduplication (via checksum) or spatial analysis (via geometry)

### Negative

- Output includes empty columns; may confuse users who see them
- Slight overhead in CSV/JSON exports (extra keys/columns)
- Commits to maintaining these field names permanently

## Mitigation

- Documentation clearly states that these columns are reserved and currently empty
- Schema version marker can flag when these fields are first populated
- CSV headers and JSON schema documents make reserved fields discoverable

## Alternatives considered

1. **Add fields dynamically when needed:**
   - **Rejected:** Creates schema migrations and breaks downstream consumers unexpectedly.

2. **Use optional/extensible schema:**
   - **Rejected:** Harder for users to plan integrations if schema is unstable.

3. **Add fields one-at-a-time as features arrive:**
   - **Considered but deferred:** Reservation avoids surprise schema changes.

## Related decisions

- [ADR-010: Explicit disposition field](0010-explicit-disposition-field.md) — disposition is the primary outcome field
- [ADR-005: Thread-safe QA substrate](0005-thread-safe-qa-substrate.md) — provenance vs. QA record distinction

## Issues/PRs

- Specification: [mergeplan-deltas.md §Global Constraints](../superpowers/specs/2026-06-19-mergeplan-deltas.md)
- Future enhancements: [docs/HARVESTER_ENHANCEMENTS.md](../HARVESTER_ENHANCEMENTS.md)
