# ADR-0115: Survey123 Phase 1 — form validation and schema drift

**Status:** Accepted

**Date:** 2026-07-25

## Context

The Survey123 add-on roadmap (ADR-0112) Phase 1 requires headless,
base-install form validation and schema-drift classification before any
publication feature. Nothing in the repository read an XLSForm back in:
`build_xlsform` writes the workbook and every downstream tool consumes
submissions, so a hand-edited or regenerated form could drift from its
configs, from the ADR-0113 SampleID contract, or from the feature layer it
will eventually publish to, with no detection until field data arrived wrong.

## Decision

- **New module `autogis/core/envmon/survey_schema.py`** (openpyxl + stdlib;
  arcpy/arcgis-free): the repo's first XLSForm reader (header-driven column
  mapping), `validate_form`, `diff_forms`, and `diff_form_vs_layer`.
- **`envmon validate-survey-form FORM.xlsx [--site-config/--event-config/
  --analyte-dict] --report --fail-on`** — standard QA contract
  (`_render_qa`, exit 0/1). Checks: sheet presence, XLSForm name rules,
  duplicate names, type whitelist, choice-list resolution and hygiene,
  `${ref}` resolution (order-independent — ADR-0113 deliberately emits
  SampleID after QAFlags), group/repeat balance, required-value sanity,
  settings shape, and config cross-references (planned locations, matrices,
  crew slugs, analyte decimal coverage via the form builder's own
  `_field_name`). **SampleID contract divergence is an ERROR** (owner
  decision 2026-07-25), and every choice named by the calculate's
  `selected(...)` duplicate legs must exist in that question's choice list
  (`field_dup_a` and `field_dup_b` after issue #361).
- **`envmon diff-survey-schema FORM.xlsx [--baseline-form OLD]
  [--layer-spec SPEC] [--report]`** — classifies changes
  safe / review-required / destructive per a fixed taxonomy (removals,
  renames, type changes, repeat-shape changes, SampleID calculation changes,
  choice-code changes, and `form_id` rebinding are destructive; new-required
  questions, calculation changes, choice removals, list re-pointing, and
  group moves are review-required; additions and cosmetic edits are safe).
  Semantic exits per the `coc reconcile`/`event-status` precedent:
  0 none-or-safe, 2 review-required, 3 destructive, 1 usage/IO. Because 2 is
  load-bearing for CI gates, usage and IO errors are raised as
  `ClickException` (exit 1) and `click.Path(exists=True)` is deliberately not
  used — otherwise a mistyped path would exit 2 and read as
  "review-required". A malformed invocation caught by click's own parser
  (e.g. `--bogus`) still exits 2; that is inherent to click and writes no
  run-history record.
- **Semantic exits must also be registered for run history.** ADR-0093
  established the exit-code half of this pattern; the recorder half lives in
  `_SEMANTIC_EXIT_CODES` in `cli.py`, keyed by exact leaf command name, so a
  review-required diff logs `status=success` rather than a tool failure
  feeding `run-history-report` / `evaluate-readiness` / `portfolio-metrics`.
  A future command with a semantic nonzero exit registers there too.
- **Name rules follow xlsform.org, not intuition** (verified against the
  spec 2026-07-26). Question names start with a letter or underscore and may
  then contain letters, digits, hyphens, underscores and periods. Choice
  **values are not identifiers**: the only documented constraint is that a
  `select_multiple` choice may not contain a space (`select_one` may).
  Applying the question rule to choice values rejected Likert codes `1`/`2`
  and — because `build_xlsform` writes `location_ids` verbatim as choice
  codes — made this command reject `build-survey-form`'s own output for any
  site with a location like `101-MW`. The `allow_choice_duplicates` setting
  suppresses the duplicate-choice error, as the spec documents for cascading
  selects.
- **A workbook with no `survey` sheet is rejected by the reader**, not
  tolerated as an empty schema. Tolerating it made `diff-survey-schema`
  report every question in the other form as a safe addition, so pointing
  `--baseline-form` at the wrong workbook returned exit 0 — a clean bill of
  health from a publication gate. Sheet names match case-insensitively,
  since Excel round-trips capitalize them.
- **Feature-layer leg reuses `audit_schema`:** the saved feature-layer
  definition is the existing audit-schema local-spec YAML; form questions
  map to AGOL-REST-shaped fields (XLSForm→esriFieldType table;
  `select_one` choices become coded values, domain names normalized to the
  spec's so only coded-value drift surfaces) and `audit_schema.diff_schema`
  does the comparison. DriftItem classification: TYPE_MISMATCH destructive;
  EXTRA_FIELD/DOMAIN_DRIFT review-required; MISSING_FIELD safe.
  (NULLABLE_MISMATCH maps review-required for forward-compat but cannot
  currently fire: the form side emits no `nullable` — see the `ponytail:`
  note in `form_layer_fields`.)
- Both commands registered `Runtime.CLOUD`, `stable`, domain `field`,
  roadmap ids `S123-1.1`/`S123-1.2`. No ADR-0076 `--site`/`--event` stamps:
  neither produces event artifacts that `event-status` tracks.

## Consequences

- The Phase 1 exit gate is met from saved artifacts (.xlsx / .yaml): known-
  breaking question, repeat, choice, type, and feature-layer changes are
  detected; no portal access; base install. Phase 2 (live sync) remains
  separately user-gated.
- A builder/validator round-trip test pins `build_xlsform` output to
  zero findings against its own configs — the Phase 1 analogue of the
  ADR-0113 planner/normalizer agreement test. Its fixture deliberately
  includes a leading-digit location (`101-MW`): with only `MW-*` names the
  test passed while the validator still rejected real sites' generated forms.
- `validate-survey-form` run without config flags now emits a
  `cross_checks_skipped` INFO record. It previously returned PASS having run
  none of checks 11-13, which reads as "verified against its configs" on a
  gate that had checked nothing of the sort.
- Read-only commands over local files; no migration, credentials, or PII.
  Rollback = revert.
- Deferred: XForm expression execution (the ADR-0113 `ponytail:` ceiling),
  appearance/relevant/constraint semantics, the Phase 0 client matrix,
  rename detection beyond the same-label choice heuristic.

## Related

- Spec: `docs/superpowers/specs/2026-07-25-survey123-phase1-form-validation-design.md`
- Plan: `docs/superpowers/plans/2026-07-25-survey123-phase1-form-validation.md`
- ADR-0112 (roadmap), ADR-0113 (SampleID contract), ADR-0021 (form builder),
  ADR-0093 (semantic exit codes precedent)
