# Survey123 add-on Phase 3 — planned/field/COC/lab/GDB event reconciliation

**Status:** DESIGN CHECKPOINT — brainstorming incomplete, not yet approved, no
implementation started.
**Date:** 2026-07-30
**Track:** Survey123 optional add-on roadmap (ADR-0112), Phase 3.
**Phase start:** explicit owner decision 2026-07-30 (not roadmap momentum).

> **Why this file exists.** A Claude service outage interrupted the
> brainstorming session. This records the decisions already made and the
> code-survey findings behind them so the next session resumes without
> re-deriving anything. It is **not** an approved design and must not be
> implemented from as-is — the open questions in §5 come first.

## 1. Scope (from the roadmap)

Extend the existing field-to-lab comparison into one event reconciliation
across five sources:

```text
sampling plan -> Survey123 submission -> COC -> laboratory result -> GDB record
```

Report missing, duplicate, unexpected, mistyped, wrong-matrix, wrong-analyte,
dry/inactive-location, date, attachment, and status exceptions. Exact stable
keys decide matches; fuzzy matching may suggest a candidate but never changes
an identity automatically.

**Exit gate:** a sanitized event reconciles every planned and observed sample
to one explicit outcome, totals balance across all five sources, and no
ambiguous match is silently accepted.

## 2. Decisions locked in this session

### D1 — All five sources in one slice (owner, 2026-07-30)

Not sliced into a 3-source spine first. Rationale: the new value in Phase 3 is
entirely the **five-way join on one stable key**. A plan→S123→lab subset is
close to what `field_lab_reconciler` and `reconcile_survey123_lab` already do,
so a partial slice would land a third overlapping reconciler that meets no
gate. Only the full join can satisfy "totals balance across all five sources."

Rejected alternative: a source-agnostic "join engine" with sources wired in
incrementally — risks a speculative abstraction if the five sources each need
per-source logic anyway (they likely do: COC and GDB legs differ in kind from
the other three).

### D2 — Sample grain, analytes as an attribute (owner, 2026-07-30)

The reconciliation table is **one row per SampleID**. Four of the five sources
are per-sample; only lab results are per-sample-per-analyte. Analyte coverage
is compared as an *attribute* of the lab leg (expected vs received analyte
sets), which still reports wrong-analyte and missing-analyte exceptions.

Rationale: keeps "every planned and observed sample to one explicit outcome"
literally true — one row, one outcome — and keeps the five-source balance
claim countable. Full sample×analyte grain would multiply rows by analyte
count and repeat the four per-sample sources on every row, making the balance
statement hard to state or verify, for one extra exception type.

Rejected alternative: two tables (sample-grain outcome + analyte detail) —
cleanest reporting but two outputs to keep mutually consistent.

## 3. Code-survey findings (do not re-derive)

### The stable-key spine already exists

`autogis/core/envmon/sample_id.py` is the single owner per **ADR-0113**:
`LIFECYCLE_FORMAT` = `{location}-{YYYYMMDD}-{matrix}[-{qc}]`, plus
`build_sample_id`, `parse_sample_id`, `strip_qc`, `qc_class`, `QC_SUFFIXES`,
and `xform_sample_id_calc`. ADR-0113 converged five previously-drifting
producers onto it. Phase 3 must not introduce a second key notion.

**CORRECTION (2026-07-30, Fable review — verified against source).** The key
is *not* already uniform across the five sources, and an earlier draft of this
file wrongly implied it was:

- `sampling_plan.py:139-142` builds `f"{site_id}-{loc}-{event_str}-{group_name}"`
  and carries an explicit comment: *"Non-lifecycle identity: per-analyte-group
  granularity, deliberately NOT the lifecycle SampleID format —
  sample_id.parse_sample_id returns None for it."* So `sampling_plan` is the
  **wrong plan leg** for this join.
- The lifecycle-key plan producer is `create_sampling_event.py`:
  `ExpectedSampleRow.sample_id` is built via `build_sample_id`
  (`create_sampling_event.py:195`, `:214`), and `SamplingEventPlan` exposes
  `expected_samples` (`:62`).
- That is also exactly what the COC bridge already consumes:
  `custody.records_from_plan` reads `plan.expected_samples` and groups by
  `row.coc_number` (`custody.py:204-206`).

**Consequence:** the plan leg is `SamplingEventPlan.expected_samples`, not
`sampling_plan.PlannedSample`. Note the roadmap's phrase "sampling plan"
ambiguously names the non-lifecycle module — see Q9.

Key normalization across the five sources — not the join itself — is where
"totals balance" lives or dies: lab feeds ship `-DUP`/`-D` spellings, and
`NODATE` IDs never resolve to a primary (`sample_id.py:121-126`).

### The arcpy-free constraint is already solved by an established seam pattern

The add-on must run in a base install, but the GDB leg appears to need arcpy.
The repo already resolves this shape:

- `canonical_read.py` — *"arcpy-free: operates on plain row dicts"*
  (`canonical_result_rows`, `canonical_records`).
- `export_snapshot.py` — pure-Python layer (`SnapshotManifest`,
  `format_manifest`, `build_where`) with `export_event_snapshot()` isolated
  behind `# pragma: no cover` because it imports arcpy.
- Phase 2 followed the same split: `plan_layer_envelopes` pure,
  `fetch_item_pulls` the live `# pragma: no cover` seam.

**Consequence:** the Phase 3 reconciler consumes **row dicts**; any arcpy
extraction stays a thin separate seam. No new policy needed.

### Two field↔lab reconcilers exist, and the overlap is deliberate

- `field_lab_reconciler.py` (251 lines, Tool 7.3) — generic CSV path.
  `FieldSampleRecord`/`LabResultRecord`/`ReconciliationFlag`,
  `_FLAG_SEVERITY` map, exact-key matching only, no fuzzy. Its docstring
  states it is *"Distinct from reconcile-survey123-lab (Tool 2.6), which is
  Survey123-specific."* — **do not "converge" these as cleanup.**
- `reconcile_survey123_lab.py` (166 lines, Tool 2.6) — Survey123-specific.
  `Survey123Sample`/`LabSample`/`ReconcileS123LabResult`, `load_survey123_csv`
  with `DEFAULT_HEADER_MAP`, `reconcile_field_lab`, `_check_pair`,
  `reconcile_to_qa`.

Being on the Survey123 track, Phase 3's natural base is **Tool 2.6**.

### LANDMINE — Tool 2.6's fuzzy match violates the Phase 3 rule

`reconcile_field_lab` (`reconcile_survey123_lab.py:71-122`) falls back to
`difflib` at `threshold=0.85` and, on a hit, **auto-consumes the candidate**:
it removes `best` from `unmatched_lab`, pairs it via `_check_pair`, and only
emits a `sample_id_mismatch` warning. That *is* an automatic identity change,
which Phase 3 forbids outright ("fuzzy matching may suggest a candidate but
never changes an identity automatically").

ADR-0113 / issue #360 already fixed the *QC-class* case of this: `qc_class()`
now structurally bars cross-class matches, so a `-FD`/`-DUP`/`-D` duplicate
can no longer consume its own primary (which scored 0.914 / 0.889 / 0.941 —
all above threshold). But the **general** case survives: two plain IDs
differing by a typo still auto-match and silently rewrite identity.

Phase 3 must therefore either (a) not reuse that fallback, or (b) fix it at
the root so fuzzy results become *suggestions* on the outcome record. Option
(b) touches existing Tool 2.6 callers — see open question Q3.

### Per-source readers available

| Source | Module | Key types |
|---|---|---|
| Plan | `create_sampling_event.py` — **not** `sampling_plan.py`, see correction above | `SamplingEventPlan.expected_samples`, `ExpectedSampleRow` (`.sample_id` via `build_sample_id`, `.coc_number`) |
| Survey123 | `survey_sync.py` (398 ln, Phase 2) | `SubmissionEnvelope`, `LayerPull`, `plan_layer_envelopes`, `write_envelopes_jsonl`, `write_submissions_csv` |
| COC | `custody.py` (331 ln, Phase 6) | `CustodyRecord`, `AuditEntry`, `Reconciliation`, `reconcile(record, received_ids)`, `records_from_plan`, `load_store`/`save_store` |
| Lab | `reconcile_survey123_lab.LabSample`, EDD canonical via `canonical_read.py` | row dicts |
| GDB | `canonical_read.py` row dicts (arcpy extraction = separate seam) | row dicts |

`custody.reconcile()` already does a COC↔received-IDs comparison — the COC leg
should reuse it rather than re-implement.

Other context: `normalize_survey123.py` (146 ln) produces submissions;
`survey_schema.py` (625 ln) owns form validation/drift (Phase 1, ADR-0115).

## 4. Constraints carried in

- Headless, arcpy-free, no `arcgis` import in `core/` (CI is the only verifier
  of the arcgis-free invariant — local env has `arcgis` installed).
- Survey123 code paths live behind the opt-in `survey123` extra (ADR-0112).
- Ponytail: reuse before writing. Three of five legs have existing readers and
  the COC leg has an existing comparison function.
- Any new arcpy call would need ADR-0077 doc-verification — the seam pattern
  above means slice 1 likely adds **none**.

## 5. Open questions — resume here

1. **Q1 — Outcome taxonomy.** The gate demands "one explicit outcome" per
   sample. What is the closed set of outcomes, and how do the roadmap's ten
   exception types map onto it? (Domain judgment; owner input wanted. Likely
   shape: one `outcome` enum per row + a list of exception codes.)
2. **Q2 — Balance statement.** What exactly does "totals balance across all
   five sources" assert, and where is it emitted — a reconciliation summary
   block with per-source counts plus a residual that must be zero?
3. **Q3 — Fuzzy fix scope. RESOLVED in direction (Fable review), confirm on
   resume.** Phase 3 uses **exact-only** matching; fuzzy becomes a suggestion
   list computed *after* the set-differences and consuming nothing. That
   satisfies the roadmap rule without touching Tool 2.6 at all, so Phase 3
   carries no behavior change to shipped code. Tool 2.6's own auto-consume
   defect is separated out as its own issue (see §5.1) rather than smuggled
   into this phase.
4. **Q4 — Module boundary.** New `reconcile_event.py`, or extend Tool 2.6
   in place? Tool 2.6 is 166 lines; a five-source join plus outcome
   assignment will not fit comfortably without the file doing too much.
5. **Q5 — Command surface.** Command name and output formats
   (`envmon reconcile-event`? JSON + CSV? QA report via `_render_qa`?).
6. **Q6 — Dry/inactive locations and attachments.** Which source is
   authoritative for location status, and what counts as an attachment
   exception given Phase 2 carries attachment metadata in the envelope?
7. **Q7 — COC grain vs the balance claim.** `CustodyRecord` is
   **per-shipment**, not per-sample: it holds `sample_ids: List[str]`
   (`custody.py:84-90`) and `reconcile()` is per-record (`custody.py:179-190`).
   The COC "presence set" for an event must therefore be defined — union of
   `sample_ids` across the event's COC records — plus rules for a sample
   appearing on more than one COC, and for deciding which store records belong
   to the event at all.
8. **Q8 — Legitimately single-source samples (blocking for the gate).** Some
   samples correctly exist in only one leg: lab QC (`-MB`, MS/MSD) appears
   only in the lab feed; a trip blank may be plan+COC but never a field
   submission. Without an explicit "expected-absent per source" concept the
   balance residual can never be zero and the exit gate becomes
   unfalsifiable. Interacts directly with Q1's taxonomy.
9. **Q9 — Which plan artifact is authoritative.** Follows from the correction
   in §3: `create_sampling_event.SamplingEventPlan` (lifecycle keys) vs
   `sampling_plan.SamplingPlan` (non-lifecycle, per-analyte-group). Decide
   explicitly and state it, because the roadmap's phrase "sampling plan"
   names the wrong one.

### 5.1 Spun-out defect (not Phase 3 scope)

Fable's review found a **new** defect in Tool 2.6 while fact-checking the
landmine: `reconcile_field_lab` matches greedily in field-sample input order,
so an early fuzzy consume can steal a lab record that *exactly* matches a
later field sample — mispairing A↔L with only a warning, falsely reporting B
as `field_only`, and leaving L's true owner unmatched
(`reconcile_survey123_lab.py:84-117`). Same failure family as closed #360 but
order-driven rather than class-driven; not a duplicate of #360, #391, or #39.
Fix direction: two-pass — resolve all exact matches across all field samples
first, then fuzzy over the remainder.

**Filed as issue #395** (2026-07-30) per the project's found-bug-file-an-issue
rule. Deliberately kept out of Phase 3 so the phase carries no behavior change
to shipped code.

### 5.2 Implementation shape (Fable's recommendation, not yet approved)

A new file is right — Tool 2.6 is two-source and carries the fuzzy behavior,
`custody` is COC-only — but the shape should be smaller than a "five-way join
module": a **presence matrix** (`dict[SampleID, per-source flags]` built from
five set-builds) plus per-pair attribute checks. `custody.reconcile()` is
already the per-leg shape, and `_check_pair`'s date/matrix/location checks
(`reconcile_survey123_lab.py:125-139`) are reusable as logic. Confirm against
Q1/Q8 before building.

## 6. Next steps on resume

1. Answer Q1–Q6 (Q1 and Q3 are the blocking ones).
2. Finish brainstorming: propose 2–3 approaches, present design sections for
   approval, then rewrite this file as the approved design.
3. Then `writing-plans` for the implementation plan. **Do not implement before
   the design is approved.**
4. ADR number: **0119** is next free (latest on main = 0118, zero open PRs as
   of 2026-07-30). Re-verify against origin/main + all open PRs before
   claiming — collisions have happened repeatedly.

## 7. Session state

- Branch `worktree-survey123-phase3-spec`, worktree
  `.claude/worktrees/survey123-phase3-spec`, coordination claims resynced.
- Repo clean at start; main was at `6b4eccf`; no open PRs.
- CI is red repo-wide (issue #392, account Actions billing, ignore until
  2026-08-01) — anything shipped this weekend is locally verified only.
- No code written. No tests run. Nothing to revert.
- Design review done by a **Fable**-model advisor agent (Opus advisor was
  overloaded during the outage). It corrected the plan-leg key error in §3,
  added Q7–Q9, resolved Q3's direction, and found issue **#395**. Its
  correction was independently verified against source before acceptance.
- Brainstorming checklist position: steps 1–2 done (context explored, two
  clarifying questions answered). **Resume at step 3** — propose 2–3
  approaches — then design sections, approval, spec rewrite, and only then
  `writing-plans`.
