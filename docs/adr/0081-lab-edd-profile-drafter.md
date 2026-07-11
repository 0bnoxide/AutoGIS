# ADR-0081: LabEDD profile drafter — close the two-profile-system disconnect

**Status:** Accepted

**Date:** 2026-07-10

**Parents:** [ADR-0016](0016-lab-edd-importer-design.md) (LabEDDProfile / EDD importer),
[ADR-0075](0075-canonical-schema-expansion-step1.md) (frozen seam the drafted
profiles feed)

## Context

The intake-seamlessness review (2026-07-10, PR #225 notes) ranked the untracked
two-profile-system disconnect as the top remaining gap: `draft-parser-profile`
(Tool 2.1) heuristically drafts a `ParserProfile` for formatted monitoring
workbooks, but the flat-lab-EDD path's `LabEDDProfile` had **no drafter and no
exposed validator** — every new lab meant hand-authoring the column-mapping YAML
from scratch by reading `edd_profile.py`. A Slice-1 design spec existed
(`docs/superpowers/specs/2026-07-08-lab-profile-drafting-tooling-design.md`) but
was held pending a broader-scope reconciliation; that broader scope has since
landed as the ADR-0075 Step-1/2/3 program (Steps 1–2 shipped in PRs #212/#226),
which kept the `LabEDDProfile.columns` seam the drafter targets unchanged.

The headless-normalization half of the reviewed gap turned out to already exist:
`batch-import-workbooks` (Tool 2.2) runs `normalize_edd_rows` headlessly and
emits normalized sample/result CSVs. The drafter is the missing piece.

## Decision

1. **`autogis/core/envmon/edd_profile_draft.py`** (arcpy-free): synonym-list
   header matching per the spec — coarse two-tier confidence (CONFIRMED = exactly
   one distinct header matched; NEEDS_REVIEW = zero or ambiguous, candidates
   recorded). Field set updated from the spec's 13 to the full post-ADR-0075
   resolver set (9 required + 15 optional). Format detection: `.csv` → flat_csv
   (BOM-sniffed encoding); `.xlsx/.xlsm` → two_tab_xlsx with default
   Samples/Results sheet names, order-based fallback flagged for review, and
   single-sheet workbooks mapped as an identity merge (sample_sheet ==
   result_sheet).
2. **NEEDS_REVIEW fields are omitted from `columns`** (not written as empty
   strings) so `validate_edd_profile()` flags missing required mappings loudly;
   they surface as `_TODO` entries listing candidates, same convention as
   `propose_parser_profile`.
3. **CLI:** `envmon draft-edd-profile` (Tool 2.3a) mirrors
   `draft-parser-profile`; `envmon validate-lab-profile` (Tool 2.3b) is a thin
   exposure of the pre-existing `validate_edd_profile()` via the shared
   `_render_qa` / `--report` / `--fail-on` contract. Both CLOUD, both in
   `_REGISTRY_SEED`.

## Consequences

- New-lab onboarding becomes: `draft-edd-profile` → edit `_TODO` mappings →
  `validate-lab-profile` → dry-run via `batch-import-workbooks` (headless CSVs)
  → `import-edd` into the GDB on the Pro machine.
- Synonym lists are the load-bearing content and are thin (one verified real
  format: TestAmerica). They grow organically as new labs' exports are drafted;
  a fully-CONFIRMED draft is still a DRAFT a human must review.
- Deliberately not shipped from the spec (YAGNI until asked): the
  `list-lab-profiles` command and the `lab_profiles/<lab>/profile.yaml`
  directory restructure with per-lab sample fixtures; GUI drafting dialog
  remains Slice 2; AI-assisted drafting remains §11 phase-gated.
