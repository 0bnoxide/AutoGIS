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
   "matched" with only a `sample_id_mismatch` warning. The same collision
   fires against the duplicate markers this repo's own parser profiles ship
   (`duplicate_markers: ["DUP", "-D", "FD"]`): `-DUP` scores 0.889 and `-D`
   0.941 (issue #360).
3. **A field duplicate was invisible to the QA it exists to feed.**
   `Env_Samples` has carried `IsDuplicate` / `DuplicateType` /
   `ParentSampleID` since the EDD importer, but `normalize_survey123` never
   populated them, so they inserted `NULL`. `evaluate_duplicate_rpd` pairs on
   `IsDuplicate == 0` (parent) and `IsDuplicate == 1` (duplicate), and `None`
   equals neither — a Survey123 record was therefore *neither*, and RPD QA
   was skipped in silence. Flagging only the duplicate would not fix pairing;
   the primary needs `IsDuplicate = 0` for the parent map to contain it.

None was caught by the suite: the normalizer's happy-path ID string, the
form's calculate expression, the `-fd` parser path, the emitted duplicate
metadata, and any cross-producer agreement were all unasserted.

## Decision

- **One owner module:** `autogis/core/envmon/sample_id.py` (stdlib only)
  holds `LIFECYCLE_FORMAT` (`{location}-{YYYYMMDD}-{matrix}[-{qc}]`),
  `QC_SUFFIXES`, `build_sample_id`, `parse_sample_id`, and
  `xform_sample_id_calc`. The dateless `NODATE` form is relocated unchanged.
- **Producers converge:** the planner and normalizer call `build_sample_id`;
  the form builder emits `xform_sample_id_calc()`, whose duplicate leg reads
  the `qa_flags` choices `field_dup_a` and `field_dup_b`, producing distinct
  `-FD-A` and `-FD-B` identities. No second question: an `IsFieldDup` yes/no
  was prototyped and withdrawn because two affordances for one fact let a crew
  tick the labelled one, leave the other at its default, and emit a SampleID
  identical to the primary. ADR-0021's calculate expression is amended in
  place; its question list is unchanged. The normalizer retains legacy
  `field_dup` → `-FD` compatibility for already-generated forms, rejects
  submissions selecting multiple field-duplicate codes, and reports an
  `Env_Samples` duplicate-key skip at `ERROR` rather than hiding the loss at
  `INFO`.
- **The two renderings are coupled by test, not by code.** Python and XForm
  cannot share code across the device boundary. The test evaluates the one
  expression shape `xform_sample_id_calc` emits (concat / format-date /
  if-selected) and asserts the result equals `build_sample_id`, so a change to
  either separator, field order, or suffix fails. It is deliberately not a
  general XForm evaluator (`ponytail:` ceiling noted in source).
- **Duplicate metadata is populated on both sides.** The normalizer emits
  `IsDuplicate` (1 / 0), `DuplicateType` (`FIELD_DUP` / `""`, the value
  `table_normalizer` already writes) and `ParentSampleID` (the primary
  identity, via `strip_qc`) for duplicate *and* primary alike.
- **Reconciliation guard:** a structural check runs before any similarity
  score — IDs of different QC *class* can never match, whichever side carries
  the marker. Class, not raw suffix: `-FD`, `-FD-A` and a profile-marked
  `-DUP` are all `field_duplicate` and stay mutually matchable, while `-MB`
  and `-FB` stay separate. Non-lifecycle IDs fall back to the parser
  profile's `duplicate_markers`, which is what closes #360; an ID with no QC
  signal at all classes as `None` and is never assumed primary. The 0.85
  threshold is unchanged (raising it would relocate the collision, not close
  it).
- **Non-lifecycle producers stay out:** `sampling_plan`
  (`{site}-{loc}-{event}-{group}`, per-analyte-group granularity) and
  `legacy_migrator` (`{loc}_{date}_{idx}`, only when the source has no ID)
  are documented in-source; `parse_sample_id` returns `None` for them and
  callers read that as "not a lifecycle identity."
- **Agreement tests:** planner and normalizer outputs are asserted identical
  (including `-FD-A`); the normalizer happy-path string and the `-fd` parser
  leg are now pinned.

## Consequences

- Identities ending `-FD-A` and `-FD-B` become producible from the field
  without colliding with each other. Legacy `-FD` remains parseable and
  submissions from older forms using `field_dup` still produce it. These are
  new values in the existing `TEXT(64)` column; no schema change, no
  migration; existing records are untouched. `IsDuplicate`, `DuplicateType`
  and `ParentSampleID` are existing columns that stop being written as `NULL`.
- Submissions from forms built before this change carry no ticked
  duplicate choice unless the older `field_dup` value was selected. That value
  continues to normalize as the legacy `-FD`; otherwise old submissions behave
  exactly as before, except that they now also carry `IsDuplicate = 0` instead
  of `NULL`, which is what makes them eligible as RPD parents.
- A dateless (`NODATE`) duplicate gets a well-formed `ParentSampleID` that
  cannot resolve — the uuid disambiguator differs per submission — so
  `evaluate_duplicate_rpd` raises `rpd_parent_not_found`. A visible warning is
  the intended outcome; the alternative is a silent mispair.
- Rollback = revert the commit; already-written `-FD` identities remain
  valid and parseable (`qc_sample_summary` recognized the suffix before).
- The Phase 0 exit gate's SampleID leg is met for the three lifecycle
  producers; the submission-envelope leg is deliberately not addressed and
  **moves to Phase 2**, where its first consumer lives. Designing an envelope
  with no reader would make every field shape a guess that the first real
  puller then relitigates. `docs/survey123-add-on-roadmap.md` is amended in
  place: the envelope text and its gate clause move from Phase 0 to Phase 2,
  and Phase 5 (which normalizes through the envelope) now depends on Phase 2.
  Strict phase ordering is unaffected — 2 still precedes 5. Per ADR-0112 this
  is an explicit-owner-decision surface; owner confirmed 2026-07-25.
- No new dependencies; `core/` remains arcpy-free and arcgis-free.

## Related

- Spec: `docs/superpowers/specs/2026-07-25-survey123-sample-id-contract-design.md`
- Plan: `docs/superpowers/plans/2026-07-25-survey123-sample-id-contract.md`
- ADR-0112 (Survey123 add-on roadmap), ADR-0021 (XLSForm builder — calculate
  expression amended here), `docs/survey123-add-on-roadmap.md` (envelope leg
  relocated Phase 0 → Phase 2)
- Issue #360 (lab `-DUP`/`-D` markers defeat the reconcile guard) — closed by
  the QC-class guard here
