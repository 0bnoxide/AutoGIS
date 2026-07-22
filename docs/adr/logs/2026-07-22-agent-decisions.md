# Agent-decision log — 2026-07-22

Autonomous judgment calls made while scoping and building roadmap Phase 4 (the
monitoring-event review notebook). Design decision recorded in **ADR-0099**;
this log holds the per-decision "free will" audit. User was async ("I approve
recommended items, log your judgement") after approving the recommended items.

## D1 — Task selection: roadmap Phase 4

**Decision:** After the user delegated task choice and noted another session
holds Phase 3, picked **Phase 4** (next in sequence; the roadmap's stated first
user-facing milestone). Earlier candidates were dismissed with the user:
#272-option-5 (already shipped), #244 (deprioritised by the user mid-session),
#272-option-4 (advisor + I judged it low-leverage forward-drift-only, clone-only
until CI exists).

**Reasoning:** Isolated surface (one notebook) that only consumes existing core,
so low collision risk with the Phase 3 session and the in-flight GUI branch.

**Revisit if:** the user reprioritises, or Phase 4 turns out to need arcpy/GDB
work that isn't isolated.

## D2 — Public renderer, not the private gather function

**Decision:** The notebook calls the public `generate_event_report_html(...)`
and displays it via `IPython.display.HTML`, rather than importing
`generate_event_report._gather_event_data` (private, leading underscore).

**Reasoning:** No new API surface, no duplicated presentation logic, and it
respects the module's public boundary. Fable flagged the private import.

**Revisit if:** a section needs data the HTML renderer doesn't expose — then
promote a public accessor in core, not reach into the private function.

## D3 — Cut `compliance_summary` and `qc_sample_summary` from slice 1

**Decision:** Excluded both from the notebook's slice-1 sections.

**Reasoning:** Neither is among the roadmap's nine mandated sections;
`qc_sample_summary` already carries a `ponytail:` deferral. YAGNI.

**Revisit if:** a reviewer asks for compliance/QC-trend panels — add as a cell
calling the existing producer.

## D4 — Headless records-CSV fixture, not GDB import, not gen-synthetic-workbook

**Decision:** Build the reference event as a synthetic two-event **results
records-CSV** (+ samples CSV, schedule YAML, screening YAML) and chain the CSV
producers. Did **not** route through `import-edd` (GDB/arcpy) or
`gen-synthetic-workbook`.

**Reasoning:** Every review producer consumes CSVs; `import-edd` needs ArcGIS
Pro; `gen-synthetic-workbook`'s output has no importer path to a results CSV
(verified — only cell-level parser tests consume it). The CSV path keeps the
whole phase (and its verification test) arcpy-free.

**Revisit if:** a future review section genuinely needs GDB-only data.

## D5 — Fable as the design-gate advisor

**Decision:** Per the user's mid-session directive ("call in fable for advisor
checks at transitions"), ran a Fable subagent to adjudicate the Phase 4 design
(does the notebook need to exist; smallest slice; verifiability) before writing
code. Its corrections (public renderer, cut scope, fixture-is-the-real-work,
nbclient dependency) are folded into ADR-0099.

**Reasoning:** Explicit user instruction; the transition from design to
implementation is a decision point worth an independent check.

**Revisit if:** the user changes the advisor model or cadence.

## D7 — Fixed the compare-events → report TrendClass mismatch in core

**Decision:** Applied a 1-line fix to `generate_event_report` so the trend
section recognizes the `TrendClass` column `compare-events` emits (it read only
`TrendLabel`/`TrendVsPrevious`, which no producer writes → the section rendered
all-UNKNOWN). Added a focused regression test. Amended ADR-0099's "zero new core
code" claim to reflect this.

**Reasoning:** Root-cause fix (ponytail): the notebook's trend section depends on
it, it's a genuine latent bug, and a 1-line change beats a per-notebook column
rename hack. Pure stdlib `dict.get` — no arcpy, so no ADR-0077 doc-verify.

**Revisit if:** compare-events' output column is renamed again — keep the report's
recognized-column set in sync (or promote a shared column constant).

## D8 — Verification env: fresh arcpy-free venv

**Decision:** Ran the authoritative full-suite green check in a purpose-built
arcpy-free venv (`pip install -e .[dev,notebook]`, Python 3.14, no arcpy) after
finding both local envs unsuitable: system Python 3.14 has a **corrupted** autogis
distribution (`~%togis`) that breaks subprocess-spawning tests, and the
`autogis-py3` conda env **has arcpy** (from Pro) so every `*without_arcpy*` guard
test fails there. Clean venv result: 2262 passed, 7 skipped, 0 failed (notebook
test ran, not skipped).

**Reasoning:** "Suite green" must be proven in the canonical arcpy-free
environment, not one with known env-mismatch failures.

**Revisit if:** a maintained arcpy-free dev venv is established — use it directly.

## D9 — Readiness reads the notebook's own run, not a fixture (codex review R2)

**Decision:** Round-1 committed a synthetic `run_history.csv` fixture and read
readiness from it. Codex (R2) flagged that this renders `PASS` regardless of what
the current run produced — stale/synthetic readiness. Repointed cell 7 at the
notebook's OWN run (`WORK/run_history.csv`, written by cell 2 with
`AUTOGIS_RUN_HISTORY` redirected), scoped `required_tools` to `["apply-screening"]`
— the only headless producer this review runs that records a site identity — and
**deleted the fixture** (also removing the `.gitignore` negation from R1).

**Reasoning:** Codex is right — readiness must reflect the real run. Empirically,
`compare-events`/`run-history-report` take no `--site`, so they can't satisfy a
site-scoped readiness gate; `apply-screening` does. A cell note states the scope
(a full pre-delivery gate also needs the LOCAL import→figures tools this headless
review doesn't run). Deleting the fixture is the ponytail win — no gitignore trap,
no synthetic data. (Aside: chased a phantom "RunHistory reads 0 records" while
debugging — it was an MSYS `/tmp` vs Windows-path mismatch in the test shell, not
a code bug.)

**Revisit if:** the headless producers gain site tagging, or the readiness section
should gate the real event-production toolchain.

## D6 — ADR number 0099

**Decision:** Assigned ADR-0099 (0098 highest on disk; no open PR claims 0099).

**Reasoning:** ADR-number collisions have bitten before (ADR-0030/0031); checked
disk and the empty open-PR list before assigning.

**Revisit if:** a concurrent session lands an 0099 first — renumber before merge.
