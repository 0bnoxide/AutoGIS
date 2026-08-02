# ADR-0123: Survey123 Phase 3 — five-source event reconciliation

**Status:** Proposed (owner sign-off pending; live non-production gate leg
owner-gated)

**Date:** 2026-08-02

## Context

The Survey123 add-on roadmap (ADR-0112) Phase 3 is the track's first gate
that proves an entire event's samples agree across every source that
touches them, not just one pairwise check. Prior phases each cover one leg
in isolation: `reconcile-survey123-lab` (field vs lab only, Tool 2.6, spun
out issue #395 for its greedy fuzzy mispairing), `sync-survey123` (Phase 2,
ADR-0116, field-only pull), and `coc` (ADR-0107, custody lifecycle). None of
them says whether a sample that exists in the plan actually got sampled,
custodied, analyzed, *and* loaded to the GDB — or flags one that shows up
in the field but never reaches the lab. The approved design
(`docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md`,
owner sign-off 2026-08-01) closes that gap with a presence-matrix engine
over all five sources: plan, field, chain-of-custody, lab, GDB.

Three real defects (#420, #421, #422) surfaced during the design's format
verification pass and were filed rather than silently worked around; the
verification also caught that no persisted plan artifact or GDB row
exporter exists today, so the command rebuilds/consumes CSVs rather than
loading pre-built files (spec §6, synced 2026-08-01, commit `832dd3a`).

## Decision

- **One module owns the engine:** `core/envmon/reconcile_event.py`
  (`SourceRow`/`GridRow`/`ReconcileEventResult`, arcpy-free, pure
  dict-in/dict-out) plus `envmon reconcile-event` (`cli.py`), registered
  CLOUD in `runtime/capabilities.py`.
- **Presence matrix over five sources** (`plan`, `field`, `coc`, `lab`,
  `gdb`), each sample keyed by the ADR-0113 lifecycle SampleID
  (`normalize_key`: trim + uppercase; structure from `sample_id.py`).
- **Six-outcome taxonomy with fixed precedence** (`OUTCOME_ORDER`,
  earlier wins the row's headline): `needs_review` > `orphan` >
  `not_collected` > `stalled` > `detail_conflict` > `reconciled`.
  `needs_review` fires on a presence gap (an absent required leg between
  two present ones), a multi-COC sample, or an unparseable sample-form ID —
  never silently resolved to a "best guess" outcome.
- **Cascading anchor, not a fixed reference leg:** the anchor is the first
  source (in `plan, field, coc, lab, gdb` order) where the sample is
  present. Plan is optional per sample (D3) — a field-added sample with no
  matching plan row anchors on `field` and is judged from there, rather
  than every un-planned sample defaulting to `orphan`.
- **QC-class expected-presence masks, plan-overridable:** `QC_MASKS` maps
  each `sample_id.qc_class()` (primary/duplicate/trip blank/field
  blank/method blank/matrix spike/matrix spike duplicate/lab duplicate) to
  a per-source `required`/`optional`/`forbidden` mask — e.g. a trip blank
  is `forbidden` in `field` (it never travels through field collection) but
  `required` in `coc`/`lab`. An unrecognized suffix falls back to
  `UNKNOWN_QC_MASK` (all-optional) so an unknown QC class can never break
  balance to a nonzero residual. `--presence-overrides` JSON
  (`{SampleID: {source: required|optional|forbidden}}`) lets an operator
  override the computed mask per sample per source; an omitted leg (not
  passed on the CLI at all) is always forced to `optional` regardless of
  mask, since an omitted input is not evidence of absence (§3 step 1 of the
  design).
- **Exact-only matching (D7):** presence is keyed by exact normalized ID.
  Fuzzy matching only ever produces non-consuming *suggestions*
  (`suggest()`): pairs a `stalled`/`not_collected` row with an
  `orphan`/`needs_review` row via `difflib.SequenceMatcher` (ratio ≥ 0.85),
  but never crosses QC classes (`qc_class` guard, the same #360 rule
  `reconcile-survey123-lab` already enforces) and never proposes a NODATE ID
  (`sample_id.py`'s uuid-disambiguated fallback for unparseable dates) as a
  candidate, since a NODATE key carries no structural signal to match on.
  Suggestions are advisory only — the engine never auto-merges two rows.
- **Observation partition by record type:** `load_survey123_csv_submissions`
  already splits raw Survey123 rows into water-level and sample streams;
  the CLI's field leg only builds `SourceRow`s from the sample stream and
  reports the water-level count under `observations` in the JSON summary —
  a water-level-only submission is never miscounted as a missing sample.
  A sample-form row with a blank SampleID is routed to `garbled` (not
  silently dropped, not silently keyed by index) and always becomes a
  `needs_review` row (`UNPARSEABLE:<raw>` key) rather than colliding with a
  real sample's key.
- **Optional dry-wells input:** `--dry-wells` JSON
  (`{LocationID: reason}`), same pattern as `identify-data-gaps`'s
  data-gaps input; a `not_collected` row at a dry/inactive location gets a
  `dry:<reason>` code so an expected non-sample doesn't read as a gap
  needing follow-up.
- **Inputs are a documented CSV contract, not persisted artifacts** (spec
  §6, verified 2026-08-01 — no plan file or GDB row exporter exists):
  - **Plan leg** (optional): `--site`/`--event`/`--analytes` config paths,
    rebuilt in-process via `build_sampling_event_plan` (the `envmon coc
    generate` pattern) — there is no persisted `SamplingEventPlan` file.
  - **Field leg**: `--submissions-csv`, the raw Survey123 export,
    normalized in-process via `load_survey123_csv_submissions` (its
    two-stream return *is* the observation partition above).
  - **COC leg**: `--custody-store` JSON via `custody.load_store`.
  - **Lab leg**: `--lab-results-csv`, canonical `AnalyticalResultRecord`
    CSV via `read_records_csv` (same contract `export-wqx` uses); QC-typed
    rows are kept because presence needs them.
  - **GDB leg**: `--gdb-samples-csv`, a CSV export of `Env_Samples` via
    `read_records_csv(path, SampleRecord)` (the same documented-CSV
    convention as `evaluate-rpd-qa --samples-csv`) — nothing exports GDB
    rows headlessly today, so the operator supplies the table export.
  - Any of the five legs may be omitted (at least one is required); an
    *omitted* leg is never judged (mask forced `optional`), while an
    *unreadable provided* leg is a hard `ClickException`/`UsageError` —
    omitted and unreadable are never conflated.
- **Semantic exit code:** `reconcile-event` exits `2` when the event does
  not reconcile cleanly (nonzero residual or any `needs_review` row) —
  distinct from exit `1` (a `--fail-on` QA-severity breach) and exit `0`
  (clean). Registered in `_SEMANTIC_EXIT_CODES` (`cli.py`) per the
  ADR-0115 defect class: a semantic non-zero exit must still log a
  successful run to run-history, not read as a tool crash.
- **Outputs written before the semantic exit:** the per-sample CSV
  (outcome/origin/five presence flags/last-stage/codes) and the JSON
  summary (per-source counts, outcome totals, observations, `excluded`,
  residual, suggestions) are both written to disk before `SystemExit(2)` is
  raised, so a caller polling exit codes never has to guess whether a
  non-clean run also lost its output.

## Deferred / limitations

- **Event-window date filtering** (design spec §7 as originally drafted)
  is *not* implemented, and that section is corrected by this ADR:
  plan/custody legs are event-scoped by construction, and the
  field/lab/GDB CSVs are event exports in practice, so a
  `--date-from`/`--date-to` filter would add real code for a filter the
  operator already applies at export time. The `excluded` counts dict is
  plumbed through `ReconcileEventResult`/`summary_dict` end-to-end (always
  `{}` today) precisely so this is additive later, not a breaking change.
- **Attachment exceptions and per-record observation tracing are out of
  scope.** No attachment hash is computed or compared anywhere in this
  engine — presence is keyed on SampleID only, via GlobalID-keyed counts
  upstream. A future submission-provenance tracer (issue #414) would trace
  which raw record produced which observation; this phase only reports
  aggregate observation counts.
- **GDB leg carries no COC linkage until issue #420 lands** —
  `route-survey123` silently drops `COCNumber`/`SampledBy`/`SampleSource`
  when writing `Env_Samples`, so a `coc_number_mismatch` code can only ever
  fire between `field` and `coc`, never against the `gdb` leg, until that
  defect is fixed.
- **Owner-gated exit-gate leg:** "a sanitized real event reconciles
  end-to-end" is recorded as a Proposed sign-off item, the same pattern
  ADR-0091 and Phases 7-9 used for legs that need a live/real dataset no
  headless test can substitute for.

## Consequences

- Every reachable outcome, the D5 mask (including plan override and
  field-origin), cascade anchoring, precedence, and balance arithmetic have
  direct unit tests (Tasks 1-4); a golden fixture event (Task 6) exercises
  every outcome at least once and pins zero residual. Real-console smoke
  (2026-08-02, PowerShell, exit 0, no `UnicodeEncodeError`) confirms the
  Phase 6 cp1252 lesson (PR #296) doesn't recur here.
- Multi-COC and unparseable-ID rows always resolve to `needs_review`
  rather than a silently-picked winner, keeping the residual honest.
- Rollback = revert the commits; no persisted state, config, or GDB schema
  changes — the command only reads CSVs/JSON and writes a CSV/JSON pair.

## Alternatives considered

- **A fixed reference leg (always anchor on `plan`)** was rejected: a
  field-added sample with no plan row would default to `orphan` even
  though nothing is actually wrong yet upstream of `field` — the cascade
  anchor (D3) judges each sample from wherever it first appears.
- **Auto-applying fuzzy suggestions** was rejected: garbled/typo'd IDs are
  exactly the case a reconciler must flag for a human, not silently repair
  — consuming a suggestion could merge two genuinely different samples.

## Related

- ADR-0112 (add-on roadmap), ADR-0113 (lifecycle SampleID contract, QC
  class detection), ADR-0107 (custody lifecycle, the COC leg's source),
  ADR-0116 (Phase 2 sync, the field leg's raw-CSV shape), ADR-0115 (the
  `_SEMANTIC_EXIT_CODES` defect class this exit-2 convention follows),
  ADR-0091 (owner-gated live-Pro sign-off precedent)
- `docs/survey123-add-on-roadmap.md` Phase 3
- `docs/superpowers/specs/2026-07-30-survey123-phase3-event-reconciliation-design.md`
  (approved design; §6/§7 amended by this ADR's date-filter correction)
- Issues #395 (Tool 2.6 fuzzy mispairing, unrelated to this phase), #414
  (submission provenance tracer, deferred), #420 (GDB leg COC-field drop,
  limitation above), #421 (planner drops `matrices[1:]`, surfaces here as
  lab-side conflicts until fixed), #422 (`CustodyRecord.sample_ids`
  duplicates, reconciler de-dupes regardless)
