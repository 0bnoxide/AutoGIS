# Survey123 add-on Phase 3 — five-source event reconciliation design

**Status:** APPROVED DESIGN — owner sign-off 2026-08-01 (section-by-section
review). Supersedes the 2026-07-30 outage checkpoint that previously lived in
this file. Next step: `writing-plans`, then implementation. **Do not implement
without the plan.**
**Date:** 2026-07-30 (checkpoint) / 2026-08-01 (approved).
**Track:** Survey123 optional add-on roadmap (ADR-0112), Phase 3.
**Phase start:** explicit owner decision 2026-07-30 (not roadmap momentum).
**ADR:** next-free was 0119 on 2026-07-30 — **re-verify vs origin/main + all
open PRs before claiming** (collisions are frequent).

## 1. Scope

One event reconciliation across five sources:

```text
sampling plan -> Survey123 submission -> COC -> laboratory result -> GDB record
```

Report missing, duplicate, unexpected, mistyped, wrong-matrix, wrong-analyte,
dry/inactive-location, date, and status exceptions. Exact stable keys decide
matches; fuzzy matching may suggest a candidate but **never** changes an
identity automatically.

**Exit gate (roadmap):** a sanitized event reconciles every planned and
observed sample to one explicit outcome, totals balance across all five
sources, and no ambiguous match is silently accepted. The final leg — a
sanitized *real* owner event reconciling end-to-end — is owner-gated and will
be recorded as a Proposed sign-off item in the ADR (ADR-0091 precedent).

**Deliberately out of this slice** (record in the ADR):

- **Attachment exceptions.** No source carries attachment content hashes;
  only the raw sync envelope stream has counts, keyed by GlobalID, not
  SampleID (`survey_sync.py:71`, populated `:386-390` with id/name/size/
  content_type only; `payload_hash` `:99-103` excludes attachments). The
  out-of-band `AttachmentIndex.checksum` (`core/common/schema/attachments.py:23`)
  requires a separate harvest run and is not part of the reconciliation
  stream. Rather than a half-check, slice 1 does not cover attachments.
- **Per-record observation delivery tracing** ("did water-level reading #87
  reach the GDB?") — that is issue **#414** (submission provenance tracer),
  a separate proposed tool. Phase 3 reports observation *counts* only (§4.4).
- COC signature platform (Phase 6 exclusion carries over).

## 2. Decisions — all locked, do not re-litigate

- **D1 — All five sources in one slice** (owner, 2026-07-30). The value is
  the five-way join on one stable key; a 3-source subset would be a third
  overlapping reconciler meeting no gate.
- **D2 — Sample grain** (owner, 2026-07-30). One row per SampleID; lab
  analyte coverage compared as an attribute (expected vs received analyte
  sets), not sample×analyte rows.
- **D3 — Cascading anchor; plan optional per sample** (owner, 2026-08-01).
  The reference for a sample is the **earliest source that has it**: plan if
  planned, else the field record. Field crews add samples at their
  discretion; not all site work is formally planned. A field-added sample
  flowing cleanly downstream is *Reconciled* (origin noted `field-added`),
  not an exception; it is expected-absent from the plan column. For
  unplanned samples the crew's entry is taken at face value — only
  downstream inconsistencies with it are flagged. Plan-vs-field exceptions
  fire only when a plan entry exists.
- **D4 — Outcome taxonomy: six closed outcomes** (owner Q1, 2026-08-01).
  See §4.1. Detail codes ride along; one outcome per row.
- **D5 — Expected presence by QC class, plan can override** (owner Q8,
  2026-08-01). A built-in table maps QC class (from the ID suffix via
  `sample_id.qc_class`) to the sources it is expected in (e.g. `-MB`/MS/MSD
  lab-only; trip blank plan+COC+lab but never field). The plan may override
  per sample for odd cases. Field-origin samples are expected-absent from
  plan by D3. This is what makes "totals balance" falsifiable.
- **D6 — Observation partition by record type, never by ID parseability**
  (owner, 2026-08-01). Much Survey123 entry is observations, not samples.
  See §4.4.
- **D7 — Exact-only matching; fuzzy = post-hoc suggestions** (Q3, resolved
  2026-07-30, confirmed). Suggestions are computed after set-differences,
  consume nothing, never cross QC classes (the #360 guard), and never
  involve NODATE IDs. No behavior change to Tool 2.6 (its auto-consume
  defect is issue #395, out of scope here).
- **D8 — Optional dry-wells input** (owner, 2026-08-01). The field/survey
  path carries **no** dry/inactive status (verified: zero occurrences in
  `survey_sync.py` / `normalize_survey123.py` / `survey123_form_builder.py`;
  status exists only on the water-level grain via `normalize_groundwater.py:74-81`,
  and `data_gaps.py:62` already takes `dry_wells` as an externally supplied
  `LocationID -> reason` mapping). The reconciler follows the `data_gaps`
  pattern: an optional dry-wells mapping annotates *Not collected* rows;
  without it the rows simply carry no reason.
- **D9 — One ID policy** (2026-08-01). Every leg normalizes through
  `sample_id` (single owner, ADR-0113), then uppercase **exact** compare.
  Shipped tools currently diverge (custody is case-sensitive exact,
  `custody.py:182-189`; Tool 2.6 uppercases and fuzzy-matches,
  `reconcile_survey123_lab.py:112-124,144-151`) — the reconciler picks this
  one policy and states it in output.
- **D10 — Plan leg is `create_sampling_event`, not `sampling_plan`** (Q9).
  `sampling_plan.py:139-142` builds a deliberately non-lifecycle ID
  (`parse_sample_id` returns None for it). The lifecycle plan producer is
  `create_sampling_event.SamplingEventPlan.expected_samples`
  (`ExpectedSampleRow.sample_id` via `build_sample_id`, `:195,:214`) — also
  what `custody.records_from_plan` already consumes (`custody.py:204-206`).

## 3. Architecture — presence matrix

New module `autogis/core/envmon/reconcile_event.py`, headless/arcpy-free,
behind the `survey123` extra (ADR-0112). Consumes plain row dicts; any live
extraction stays in existing seams. Five steps:

1. **Gather** — five existing readers (§5). Any source may be omitted;
   omitted legs are not judged and are reported as "not provided" (an
   expected-presence rule for a missing leg cannot count against balance).
   A source that was *provided but fails to read* is a hard error — never an
   empty set (an unreadable custody store must not report every sample as
   missing from custody).
2. **Normalize IDs once** — through `sample_id`; uppercase; `-DUP`/`-D`
   spellings resolved to QC class before comparison (D9).
3. **Build the grid** — `dict[SampleID, PresenceRow]`: five presence flags +
   the per-source attributes each leg carries (§5).
4. **Judge each row** — compute the expected-presence mask (D5 QC table +
   plan override + D3 field-origin rule), anchor at the earliest present
   source, run per-pair attribute checks downstream of the anchor (reusing
   `_check_pair` date/matrix/location logic and `custody.reconcile` for the
   COC leg), assign exactly one outcome (§4).
5. **Report** — per-sample CSV, JSON summary with the balance block
   (per-source counts − expected absences = residual, must be zero, with
   the offending rows named when it is not), QA report via the standard
   collector (exit 0 clean / standard failure exit otherwise), and the
   suggestions section (D7).

## 4. Outcomes

### 4.1 The six outcomes (D4)

| Outcome | Meaning |
|---|---|
| `reconciled` | Present everywhere expected (per mask), attributes agree. Covers planned, field-added (origin noted), and QC samples matching their mask. |
| `stalled` | Present in a contiguous prefix of the chain, absent after some stage. Report names the last stage that has it. (The submitted-but-held-in-client-QA/QC case that motivated the taxonomy.) |
| `not_collected` | Planned, appears nowhere else. Dry-wells mapping (D8) annotates the reason; with an annotation it is informational, not an error. |
| `orphan` | Appears downstream with no upstream trail (e.g. non-QC sample only in lab or only in GDB). |
| `detail_conflict` | Present as expected but sources disagree on date, location, matrix, or lab analyte coverage vs requested. |
| `needs_review` | Tool refuses to guess: hole in the middle of the presence pattern, sample on >1 COC form, near-miss suggestion exists, or a sample-form record with a garbled ID (§4.4). Humans decide; the tool never auto-resolves identity. |

### 4.2 Precedence

When several apply, the more serious wins the headline; the rest become
detail codes. Order: `needs_review` > `orphan` > `not_collected` > `stalled`
> `detail_conflict` > `reconciled`. ("Stalled after COC, and the COC date
disagrees with field" = `stalled` + a conflict code.)

### 4.3 Billing mapping

`reconciled` + `stalled` = work performed (record provably produced and in
the chain), regardless of what the client's endpoint shows. Observation
counts (§4.4) complete the "records generated by the crew" figure.

### 4.4 Observation partition (D6)

The normalizer already splits sample records from observation records (water
levels emit as a separate stream with no SampleID —
`normalize_survey123.py:96-105` vs `:123-136`). The reconciler:

- puts **sample records** in the grid;
- keeps **observation records** out of the grid entirely — they cannot be
  orphans and cannot inflate balance — but reports them as a counted block
  by type in the summary, so crew-generated totals stay explainable;
- a **sample-form record whose ID is garbled stays in the grid as
  `needs_review`** — partition is by record type, never by whether the ID
  parses, because demoting a real sample to "observation" is exactly the
  silent loss this tool exists to catch. This is the engine/API-level
  contract (`reconcile_event(garbled=...)`); **corrected 2026-08-02,
  ADR-0123 (pr-reviewer F3)** — at the CLI's `--submissions-csv` seam
  specifically, a sample-form row with a blank `WellID` never reaches this
  branch: the normalizer rejects it first with a loud `SEV_ERROR` QA record
  (`missing_required_field`) and drops the row, which exits `1` under the
  default `--fail-on error` rather than silently demoting to
  `needs_review`. The CLI's own blank-`SampleID` check is defense-in-depth
  for any other caller of the same code path, not the live route for this
  case.

## 5. Per-source readers — verified surface (2026-08-01, file-checked)

| Source | Reader | Join key | Attributes available |
|---|---|---|---|
| Plan | `create_sampling_event.SamplingEventPlan.expected_samples`; `ExpectedSampleRow` (`create_sampling_event.py:30-43`) | `sample_id` :32 | `location_id` :33, `event_date` :34, `matrix` :35, `analyte_group` :36, `sample_type` :37, `coc_number` :42, `assigned_to` :43. No location-status, no attachments. |
| Field | **Normalized submissions** (`normalize_survey123.py:123-136`), *not* raw envelopes — `SubmissionEnvelope` has no typed sample fields (`survey_sync.py:48-73`) | `SampleID` :127 | `LocationID` :126*, `SampleDate` :129, `Matrix` :130, `SampledBy` :131, `COCNumber` :132, `IsDuplicate`/`DuplicateType` :133-134. |
| COC | `custody.CustodyRecord` (`custody.py:83-92`); presence set = union of `sample_ids` across the event's records, **de-duplicated** (#422) | `sample_ids` :90 | `coc_number` :85, `event_date` :88, `lab_name` :89, `state` :91, audit trail :73-80. Temperature/carrier only in untyped `AuditEntry.details` — not used for checks. Reuse `custody.reconcile()` (`:179-190`) for the per-form leg. |
| Lab | `reconcile_survey123_lab.LabSample` (`:31-37`) / EDD canonical via `canonical_read.canonical_records` | `sample_id` / `SampleID` | date, matrix, location; analyte set from `AnalyteCanonicalName` (+ `Qualifier`, `Is*` flags) on `AnalyticalResultRecord` (`gdb_schema.py:467-501`). `canonical_read` drops QC-typed rows (`:52`) — lab QC presence for the D5 mask is read pre-filter. |
| GDB | `canonical_read` row dicts; live extraction = existing `export_snapshot.export_event_snapshot` seam (pragma no-cover, `:113`) | `SampleID` | `Env_Samples` grain (`gdb_schema.py:43-49`): location, date, matrix, `IsDuplicate`, `LabSampleID`. **No `COCNumber`/`SampledBy` — see #420.** |

\* line numbers per 2026-08-01 verification pass; re-check on implementation.

**Consequence of #420:** until it lands, COC-number attribute checks run only
between field and custody legs; the design picks the GDB leg up automatically
once the columns exist.

## 6. Command surface

`envmon reconcile-event` (register in `runtime/capabilities.py`). Inputs
(**amended 2026-08-01 after format verification** — no plan file or GDB row
export exists as an artifact today):

- **Plan leg:** rebuilt in-process from `--site/--event/--analytes` config
  paths via `build_sampling_event_plan` — the exact `envmon coc generate`
  pattern (`cli.py:2519-2536`). There is no persisted SamplingEventPlan.
- **Field leg:** raw Survey123 submissions CSV, normalized in-process via
  `load_survey123_csv_submissions` (`normalize_survey123.py:140-156`) — no
  tool writes normalized rows to a file. Its two-stream return (water
  levels, samples) *is* the observation partition (§4.4).
- **COC leg:** custody store JSON via `custody.load_store`.
- **Lab leg:** canonical `AnalyticalResultRecord` CSV via `read_records_csv`
  (same contract as `export-wqx`, `cli.py:2740-2743`); QC-typed rows kept
  for presence.
- **GDB leg:** CSV export of `Env_Samples` via
  `read_records_csv(path, SampleRecord)` (same documented-CSV convention as
  `evaluate-rpd-qa --samples-csv`, `cli.py:625-628`) — nothing exports GDB
  rows headlessly today, so the operator supplies the table export.

Plus optional dry-wells mapping (D8) and optional presence-overrides JSON
(D5). Any of the five legs omissible (§3 step 1). Event-window filtering
(§7) is thinned to a deferral: plan/custody are event-scoped by
construction and the three CSV legs are event exports in practice; a date
filter is additive later (record in the ADR).

Outputs: per-sample CSV (outcome, origin, five presence flags, last stage
reached, detail codes) — the progress-billing artifact; JSON summary
(per-source counts, expected absences, residual, outcome totals, observation
counts, legs-run list); QA report (standard severity gating, exit 0/2);
suggestions section (never applied).

## 7. Edge rules

- **Event membership** (**amended 2026-08-02, ADR-0123** — as-shipped, not
  as originally drafted): plan and custody are event-tagged by
  construction, and the field/lab/GDB CSVs are event exports in practice,
  so no `--date-from`/`--date-to` window filter is implemented — the
  operator scopes each CSV at export time. `ReconcileEventResult.excluded`
  is plumbed end-to-end (always `{}` today) so a real date-window filter
  is additive later without a breaking change.
- **Multi-COC sample** → `needs_review` + code (no winner picked).
- **NODATE IDs** (`sample_id.py:62`, uuid-disambiguated; `date_compact=""`
  on parse): exact match only; never in suggestions.
- **Suggestions:** never cross QC classes (`qc_class` guard); computed from
  leftovers only.
- **Unreadable provided input** = hard error (§3 step 1). Omitted ≠ unreadable.
- **Blank `WellID` at the `--submissions-csv` seam** (**added 2026-08-02,
  ADR-0123, pr-reviewer F3**): rejected loudly by the normalizer (`SEV_ERROR`
  `missing_required_field`, row dropped, exit `1` under default
  `--fail-on error`) *before* the CLI's own blank-`SampleID`/`garbled`
  routing can fire — that routing is the engine/API-level
  `needs_review`/`UNPARSEABLE` contract (§4.4) and remains defense-in-depth
  at this CLI seam, not the live path for a real Survey123 export.
- **Dry-annotated `not_collected`** (**added 2026-08-02, ADR-0123,
  pr-reviewer F4**): per §4.1, informational, not an error — the row's
  downstream `REQUIRED` masks relax to `OPTIONAL`, contributing 0 residual.

## 8. Testing

- Engine is pure dict-in/dict-out: direct unit tests for every outcome, the
  D5 mask (incl. plan override + field-origin), cascade anchoring,
  precedence, and balance arithmetic. Arcpy-free.
- **Golden fixture event** exercising every outcome at least once: clean
  planned sample, field-added, stalled, orphan, detail conflict, garbled
  sample-form ID, QC blanks per mask, multi-COC sample, observations to
  partition, dry well via mapping. Must balance to zero residual.
- CLI-level test + **real Windows console smoke** (CliRunner masks cp1252
  console crashes — Phase 6 lesson, PR #296).
- Owner-gated exit-gate leg: sanitized real event end-to-end (Proposed
  sign-off item in the ADR).

## 9. Related issues

- **#395** — Tool 2.6 greedy fuzzy mispairing (spun out 2026-07-30; not
  touched by this phase).
- **#414** — submission provenance tracer (observation/record transport
  accounting; separate proposed tool, owner-filed 2026-08-01).
- **#420** — `route-survey123` silently drops `COCNumber`/`SampledBy`/
  `SampleSource` at `Env_Samples` (limits the GDB COC check, §5).
- **#421** — planner drops `matrices[1:]` silently (a planned-matrix gap
  will surface in this tool as lab-side conflicts until fixed).
- **#422** — `CustodyRecord.sample_ids` duplicates (reconciler de-dupes its
  union regardless; fix belongs in `custody.records_from_plan`).

All three new defects (#420-#422) were found during the 2026-08-01 design
verification pass and filed per the standing found-bug policy.
