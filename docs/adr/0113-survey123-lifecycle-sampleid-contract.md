# ADR-0113: Survey123 lifecycle SampleID contract (Phase 0 slice A)

**Status:** Accepted

**Date:** 2026-07-25

## Context

The Survey123 add-on roadmap (ADR-0112) Phase 0 says to pin "the existing
SampleID calculation shared by event planning, XLSForm generation,
normalization, and reconciliation." A codebase survey
(`docs/superpowers/specs/2026-07-25-survey123-sample-id-contract-design.md`,
approved 2026-07-25) found that premise inaccurate: **five** sites each
constructed a SampleID with its own literal — `create_sampling_event`,
`survey123_form_builder` (XForm concat), `normalize_survey123`,
`sampling_plan`, and `legacy_migrator` — and nothing pinned any two of them
together. The drift had already produced two live defects:

1. **A planned field duplicate could never be produced.** The planner emits
   `MW-1-20260715-GW-FD` rows and `qc_sample_summary` can read a `-fd`
   suffix, but the generated XLSForm had no duplicate input and the
   normalizer could not emit the suffix — the planner-to-parser contract was
   unreachable from the field.
2. **A duplicate silently consumed its own primary's laboratory record.**
   `reconcile_field_lab` falls back to `difflib` at threshold 0.85;
   `MW-1-20260715-GW` vs `MW-1-20260715-GW-FD` scores ≈0.914, so the pair
   "matched" with only a `sample_id_mismatch` warning.

Neither was caught by the suite: the normalizer's happy-path ID string, the
form's calculate expression, the `-fd` parser path, and any cross-producer
agreement were all unasserted.

## Decision

- **One owner module:** `autogis/core/envmon/sample_id.py` (stdlib only)
  holds `LIFECYCLE_FORMAT` (`{location}-{YYYYMMDD}-{matrix}[-{qc}]`),
  `QC_SUFFIXES`, `build_sample_id`, `parse_sample_id`, and
  `xform_sample_id_calc`. The dateless `NODATE` form is relocated unchanged.
- **Producers converge:** the planner and normalizer call `build_sample_id`;
  the form builder emits `xform_sample_id_calc()` plus a
  `select_one yes_no` question `IsFieldDup` (default no) so the field can
  produce `-FD` — this amends the ADR-0021 question list. The two renderings
  (Python / XForm) cannot share code across the device boundary; a structure
  test pins them in lockstep (`ponytail:` ceiling noted in source).
- **Reconciliation guard:** a structural check runs before any similarity
  score — two parseable lifecycle IDs with different QC components can never
  match. The 0.85 threshold is unchanged (raising it would relocate the
  collision, not close it).
- **Non-lifecycle producers stay out:** `sampling_plan`
  (`{site}-{loc}-{event}-{group}`, per-analyte-group granularity) and
  `legacy_migrator` (`{loc}_{date}_{idx}`, only when the source has no ID)
  are documented in-source; `parse_sample_id` returns `None` for them and
  callers read that as "not a lifecycle identity."
- **Agreement tests:** planner and normalizer outputs are asserted identical
  (including `-FD`); the normalizer happy-path string and the `-fd` parser
  leg are now pinned.

## Consequences

- Identities ending `-FD` become producible from the field for the first
  time — new values in the existing `TEXT(64)` column; no schema change, no
  migration; existing records untouched.
- Forms generated before this change have no `IsFieldDup` question; a
  missing field normalizes as "not a duplicate," so old submissions behave
  exactly as before.
- Rollback = revert the commit; already-written `-FD` identities remain
  valid and parseable (`qc_sample_summary` recognized the suffix before).
- The Phase 0 exit gate's SampleID leg is met for the three lifecycle
  producers; the submission-envelope leg is deliberately not addressed and
  waits for Phase 2 (its first consumer).
- No new dependencies; `core/` remains arcpy-free and arcgis-free.

## Related

- Spec: `docs/superpowers/specs/2026-07-25-survey123-sample-id-contract-design.md`
- Plan: `docs/superpowers/plans/2026-07-25-survey123-sample-id-contract.md`
- ADR-0112 (Survey123 add-on roadmap), ADR-0021 (XLSForm builder — question
  list amended here)
