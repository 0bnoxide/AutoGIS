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
producers onto it. This is the join key for all five sources — Phase 3 must
not introduce a second key notion.

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
| Plan | `sampling_plan.py` (178 ln) | `PlannedSample`, `BottleCountRow`, `SamplingPlan`, `create_sampling_plan`, `read_well_network_csv` |
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
3. **Q3 — Fuzzy fix scope.** Fix `reconcile_field_lab`'s auto-consume at the
   root (affects existing Tool 2.6 callers + tests), or leave Tool 2.6 alone
   and have Phase 3 use exact-only matching with its own suggestion channel?
   Root-cause fix is the ponytail-correct instinct, but it is a behavior
   change to shipped code and may warrant its own issue/PR.
4. **Q4 — Module boundary.** New `reconcile_event.py`, or extend Tool 2.6
   in place? Tool 2.6 is 166 lines; a five-source join plus outcome
   assignment will not fit comfortably without the file doing too much.
5. **Q5 — Command surface.** Command name and output formats
   (`envmon reconcile-event`? JSON + CSV? QA report via `_render_qa`?).
6. **Q6 — Dry/inactive locations and attachments.** Which source is
   authoritative for location status, and what counts as an attachment
   exception given Phase 2 carries attachment metadata in the envelope?

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
