# Agent decisions — 2026-07-23

Context: The owner set a session goal — "continue development of roadmap items
until none remain other than gated/deferred items" — and granted autonomy
("log your judgement calls but don't expect responses to permission asks").
These are the autonomous judgement calls made building Phase 6. Durable
decision: ADR-0107 (electronic chain-of-custody lifecycle).

## Picked Phase 6 (COC lifecycle) as the next task

**Decision:** Build Phase 6 rather than skipping to Phase 7/8.

**Reasoning:** Phases 1–5 are shipped/at-gate on main (Phase 5: ADR-0103/0104,
example recipes #288, GUI Save #291). The roadmap governance mandates strict
phase ordering — each phase reaches its gate before the next starts — so Phase 6
is the next-free item. A stale collab-channel handoff showed another session
"leaning Phase 7/8," but that was an unclaimed preference and would violate
ordering; the coordination registry showed no session holding any Phase 6+
branch/file claim. Phase 6 is also headless/arcpy-free (extends the existing COC
draft), so no GUI/arcpy/Pro-QA collision.

**Revisit if:** the owner reorders phases or another session posts a Phase 6
claim to `collab:autogis`.

## Claimed the phase before writing (collision avoidance)

**Decision:** `memory_write` a STATUS to `collab:autogis` claiming Phase 6, then
`EnterWorktree` + `resync`, *before* building — not after.

**Reasoning:** Four sessions were sitting on the main root in identical
"orienting" state; if each applied the same ordering logic they would all pick
Phase 6. The branch/file claim protects files only once you are writing them, so
intent had to be announced up front. (Advisor concurred this was the only
time-sensitive step.)

## Phase 5 gate judged met headlessly (did not build GUI recipe-load)

**Decision:** Treat Phase 5 as at-gate without a GUI "Load recipe" button.

**Reasoning:** The gate wording is "saved, reopened, validated, and repeated
deterministically." `run-recipe` reopens the YAML, `validate-recipe` validates,
both example recipes shipped (#288). GUI-Load is explicitly deferred in
`gui/app.py` and is not in the gate wording. Building it would be scope outside
the goal's next-free phase.

**Revisit if:** the owner wants GUI recipe-load as a Phase 5 completion item.

## Current-state doc + embedded audit list (not event-sourcing)

**Decision:** Store each COC as a current-state document with an embedded
append-only `audit` list, rather than deriving state from a pure event log.

**Reasoning:** Event-sourcing forces a replay on every read for no slice
benefit; the embedded audit list *is* the append-only record the gate requires,
and `state` is stored for O(1) reads. Ponytail: laziest correct model for
single-writer-per-COC access.

## Per-event JSON store, atomic write, no cross-process lock

**Decision:** One JSON file per event keyed by COC number; atomic temp-file +
`os.replace`; no OS byte-range lock (unlike `run_history.py`).

**Reasoning:** A COC store is single-writer in practice (one operator advances
one event's COCs), so the run_history sentinel-lock is unneeded complexity here.
Marked `ponytail:` in-code with the lock as the named upgrade path if concurrent
multi-operator writes to one event ever appear.

## `reconciled` reachable only via `reconcile`; `exception` terminal

**Decision:** Exclude `reconciled` from `advance --to` choices so it is only
reachable through the `reconcile` command; make `exception` terminal this slice.

**Reasoning:** The gate is "reconciles ... without a manual comparison
spreadsheet." Gating `reconciled` behind the command that actually computes the
planned-vs-received comparison enforces that at the state-machine level — you
cannot mark a COC reconciled without a recorded comparison. Exception-resolution
(`exception → reconciled`) is deferred with an in-code upgrade note; no real
workflow needs reopening yet (YAGNI).

## Generic `advance --set k=v` instead of six typed commands

**Decision:** One generic `advance` (with repeatable `--set` details) covers
released/lab-received/results-received/exception; only `generate` and `reconcile`
are special.

**Reasoning:** The real business rule is *which transitions are legal*, which
lives in core and is validated there. Six bespoke commands would be surface for
no gain. Temperature/carrier/reason ride in `--set` (light bool/int/float
coercion) and land in the audit details. Ponytail: add typed per-state field
validation when operators need it.

## Non-ASCII console-output bug caught by a real run (not CliRunner)

**Decision:** Replace `→`/`—` in `click.echo` strings with ASCII `->`/`-`.

**Reasoning:** The 22 CliRunner tests passed because CliRunner buffers output
in-memory and never hits the Windows cp1252 console codec. A manual
`python -m autogis envmon coc ...` run crashed with `UnicodeEncodeError` on the
arrow character — and the crash happened *after* the state persisted but *before*
`SystemExit`, so it also broke the reconcile exit code. Lesson reinforced: a real
end-to-end console run catches what the test harness structurally cannot.

## Post-advisor hardening (two correctness fixes before PR)

**Decision:** After the advisor flagged them, (1) make `coc generate` refuse to
overwrite COCs already in the store, and (2) guard `reconcile` to require
`laboratory_received`/`results_received`.

**Reasoning:** (1) All tests/manual runs used a fresh store, so re-generating
onto an in-progress store — which would reset state and *discard the audit
trail* — was unexercised. On an audit tool that is exactly the gate-item-6
data-loss case; refuse-on-conflict is the minimal safe fix (regenerate into a
fresh store). (2) Without the guard, a clean reconcile from `generated` errored
(illegal →reconciled) while a discrepancy silently succeeded (→exception) —
inconsistent; the guard makes both outcomes reject pre-lab-receipt. Deferrals
the advisor surfaced (run-history logging, field-duplicate blind-ID
reconciliation) are now recorded in ADR-0107 rather than left silent.

---

# Phase 7 — longitudinal laboratory-QA trends (ADR-0108)

After Phase 6 (PR #296), continued the roadmap to Phase 7 in the same autonomous
session. Durable decision: ADR-0108. Branch `feat-phase7-labqa`, **stacked on the
Phase 6 branch**.

## Stacked Phase 7 on the Phase 6 branch (not fresh from main)

**Decision:** Branch Phase 7 from the Phase 6 HEAD, not from origin/main.

**Reasoning:** Phase 7 edits `cli.py` + `capabilities.py`, which Phase 6 also
edited (both add an envmon command + TOOLS/seed rows in the same regions). A
fresh-from-main branch would conflict with Phase 6 at whichever merges second;
stacking makes Phase 7 build on Phase 6's edits, so the diffs compose. Advisor
concurred. Strict phase ordering is preserved (Phase 6 gate met before Phase 7
started; Phase 7 PR is based on the Phase 6 line).

## Gate's "reproduce a manually reviewed historical set" leg — Proposed, not met

**Decision:** Do NOT hand-build a "historical set" fixture and call the gate met;
record that leg as a Proposed owner-sign-off item in ADR-0108.

**Reasoning:** Authoring both the deterministic rule and its expected output is
circular for the one thing that gate exists to test (do the rules match a real
reviewer). Synthetic fixtures verify the *arithmetic*; real-historical acceptance
needs owner data + judgment. Gate amendments are owner decisions (ADR-0091
precedent). This is the recurring shape for phases 8–10 too — external verifiers
(agency validator, live hosted service, real 6–9 output) can't be self-certified.

## Input contract = Env_QCResults CSV; production scoped out of slice 1

**Decision:** Define the tool's input as a `QCResultRecord`-shaped CSV read via
`records_csv`; do not build the exporter that produces it in this slice.

**Reasoning:** Verified (not inferred) that `export_event_snapshot` is arcpy-only
GDB→GDB and nothing emits `Env_QCResults` to CSV headlessly. Rather than invent a
schema, reuse the canonical `QCResultRecord`; note the headless exporter as a
dependency. Advisor flagged nailing this before building — done.

## Two dimensions, data-driven recovery membership

**Decision:** Slice 1 = recovery + blank only (of five); recovery membership is
"row has PercentRecovery," not a hardcoded QC-type list.

**Reasoning:** Ponytail smallest-useful-slice; recovery + blank share one
group/aggregate engine the other three plug into later. Data-driven membership
avoids a drift-prone enum of lab QC-type spellings. "By laboratory" grouping
deferred — `Env_QCResults` has no `LabName` column (documented).

## Cited, configurable, in-output thresholds

**Decision:** Every `LabQATrendRow` carries `threshold_applied` + `citation`;
lab row-limits override cited defaults; missing blank RL flags a QA warning
instead of guessing a limit.

**Reasoning:** The gate explicitly requires thresholds "configurable, cited, and
represented in QA output" — non-optional even in slice 1. Fabricating a limit
when RL is absent would be a silent professional judgment; a QA warning keeps it
honest.
