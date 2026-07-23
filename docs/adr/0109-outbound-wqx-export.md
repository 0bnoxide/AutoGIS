# ADR-0109: Outbound WQX/regulatory exchange (Phase 8, slice 1)

**Status:** Accepted

**Date:** 2026-07-23

## Context

Production-roadmap Phase 8 calls for the outbound complement to the WQX reader:
map canonical records to required WQX submission fields, validate
identifiers/units/methods/qualifiers/coordinates, produce deterministic
submission files, and package rejection details plus source/configuration
provenance.

The inbound side (`wqx_reader`, `config/lab_profiles/wqx.yaml`, ADR-0080) already
reads a WQP result CSV *into* canonical fields. Its `columns` map and the
`_COL_*` constants encode the WQX column vocabulary, verified against real
exports in the 2026-07-09 paper mapping. That inbound mapping still carries a
**DRAFT** banner and `_TODO` vocabularies.

Constraints:

1. **Coordinates are not in canonical result records.** They live on the wells
   feature class (LOCAL). A headless outbound tool cannot read them from the
   GDB, so a monitoring-location metadata CSV is an explicit input contract for
   latitude/longitude/datum.
2. **The gate needs the agency validator.** "A sanitized package passes the
   target validator or a documented agency preflight review" cannot be
   self-certified; recorded below as a Proposed owner-sign-off item.

## Decision

Add `autogis/core/envmon/wqx_outbound.py` (headless, arcpy-free) and the
`envmon export-wqx` CLI.

- **Column vocabulary anchored on verified sources.** WQX target column names
  come from `wqx_reader`'s `_COL_*` constants (synthesized fields:
  CharacteristicName, ResultMeasureValue, units, media, limits, condition) and
  the `wqx.yaml` direct-field names (MonitoringLocationIdentifier,
  ActivityIdentifier, ActivityStartDate, MeasureQualifierCode, method) — never
  hand-authored from memory. Media is the inverse of the reader's `matrix_map`.
- **Input contracts:** a canonical results CSV (`WqxSourceRow`, field names ==
  `wqx.yaml` `columns` keys) and a monitoring-location metadata CSV
  (`MonitoringLocation`) for coordinates. Both via `records_csv`. `--results`
  is repeatable (one CSV per event).
- **Validation → rejections, not silent drops.** Hard-required: location and
  activity identifiers, an ISO ActivityStartDate, CharacteristicName, a method,
  a value+units for detections, and valid in-range coordinates. Failing rows go
  to `wqx_rejections.csv` with a reason. Qualifier validation is opt-in via a
  configurable `allowed_qualifiers` set (default permissive) so it never
  false-rejects a project that hasn't supplied its domain list.
- **Deterministic outputs + provenance.** `wqx_submission.csv` (sorted by
  location/activity/characteristic), `wqx_rejections.csv`, and
  `wqx_provenance.json` (source files, config, counts, timestamp, DRAFT status).

Registered `export-wqx` (CLOUD, **DRAFT** status) in `capabilities.TOOLS` +
`_REGISTRY_SEED`.

## Consequences

### Positive

- Deterministic canonical→WQX mapping with identifier/coordinate/unit/method/
  qualifier validation and explicit rejection packaging — the buildable core of
  the Phase 8 gate; "failed records cannot silently disappear" is enforced.
- Reuses `wqx_reader` constants + `wqx.yaml` names (verified) and `records_csv`;
  no new dependency, no core→adapter coupling.
- Synthetic-fixture-verified + real-console CLI run producing the three files.

### Negative / DRAFT status

- **Inherits the inbound mapping's DRAFT status.** `wqx.yaml` and `wqx_reader`
  still carry a DRAFT banner and `_TODO` vocabularies; the outbound column set
  and value transforms are therefore unverified against the agency validator.
- **Not a full WQX submission.** Slice 1 emits a flat result table; WQX Web
  submission also needs Project/MonitoringLocation/Organization headers and the
  full required-field set. Additive later slices.
- **No units/method domain validation** yet (presence-only). Cross-checking unit
  and method codes against WQX domain lists is deferred.

### Proposed gate item (owner sign-off)

Phase 8's gate — "a sanitized package passes the target validator or a documented
agency preflight review" — is **not** met by this slice and cannot be
self-certified. Proposed for owner acceptance: run `export-wqx` on a sanitized
event and submit `wqx_submission.csv` to the EPA WQX validator (or a documented
agency preflight), confirming it passes or that all failures are the intended
rejections. Until then Phase 8 is "slice 1 shipped; validator acceptance
pending", and `wqx.yaml`'s DRAFT banner stays.

## Alternatives considered

- **Hand-author WQX column names** — rejected; `wqx_reader` already has verified
  ones. Anchoring on them keeps outbound and inbound in lockstep.
- **Source coordinates from the GDB** — rejected; that is arcpy/LOCAL and breaks
  the headless invariant. Explicit metadata CSV instead.
- **Reject on any unknown qualifier by default** — rejected; would false-reject
  projects without a domain list. Made opt-in via config.
- **Drop invalid rows silently** — rejected; the gate requires failed records be
  packaged, so every reject carries a reason.

## Related decisions

- [ADR-0080: WQX inbound reader / frozen column seam](0080-wqx-step2-import.md)
- [ADR-0087: Post-catalog production roadmap ordering](0087-post-catalog-production-roadmap.md)
- [ADR-0091: Pro qualification runner — precedent for owner gate amendment](0091-arcgis-pro-qualification-runner.md)
- `wqx_reader.py` verified `_COL_*` constants; `config/lab_profiles/wqx.yaml`
