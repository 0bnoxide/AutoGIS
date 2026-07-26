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
  decision 2026-07-25), and the choice list read by the calculate's
  `selected(...)` duplicate leg must contain the `field_dup` choice.
- **`envmon diff-survey-schema FORM.xlsx [--baseline-form OLD]
  [--layer-spec SPEC] [--report]`** — classifies changes
  safe / review-required / destructive per a fixed taxonomy (removals,
  renames, type changes, repeat-shape changes, SampleID calculation changes,
  choice-code changes, and `form_id` rebinding are destructive; new-required
  questions, calculation changes, choice removals, list re-pointing, and
  group moves are review-required; additions and cosmetic edits are safe).
  Semantic exits per the `coc reconcile`/`event-status` precedent:
  0 none-or-safe, 2 review-required, 3 destructive, 1 usage/IO.
- **Feature-layer leg reuses `audit_schema`:** the saved feature-layer
  definition is the existing audit-schema local-spec YAML; form questions
  map to AGOL-REST-shaped fields (XLSForm→esriFieldType table;
  `select_one` choices become coded values, domain names normalized to the
  spec's so only coded-value drift surfaces) and `audit_schema.diff_schema`
  does the comparison. DriftItem classification: TYPE_MISMATCH destructive;
  EXTRA_FIELD/DOMAIN_DRIFT/NULLABLE_MISMATCH review-required; MISSING_FIELD
  safe.
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
  ADR-0113 planner/normalizer agreement test.
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
