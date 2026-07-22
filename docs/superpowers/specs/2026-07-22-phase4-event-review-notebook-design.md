# Phase 4 — Monitoring-event review notebook (design)

**Status:** Approved (user, 2026-07-22 — recommended items, async: "I approve
recommended items, log your judgement")
**Roadmap:** `docs/production-roadmap.md` Phase 4; ordering per ADR-0087
**Decision record:** ADR-0099
**Author judgment log:** `docs/adr/logs/2026-07-22-agent-decisions.md`

## Goal

Ship **one** supported notebook that aggregates an event's review sections from
**existing** core producers — an interactive review surface, not a fourth
implementation. Per roadmap governance: reusable behavior stays in
`autogis.core`; the notebook only imports and displays it. **No new domain
logic** (one incidental 1-line core fix: the event report now reads
`compare-events`' `TrendClass` column so the trend section isn't all-`UNKNOWN`;
regression-tested).

## Why a notebook when `generate_event_report` exists

`generate_event_report.py` already renders 5 of the 9 mandated sections (import
results/screening, comparisons, trends, data gaps, RPD QA) as MD **and** HTML.
It does **not** cover: import summary, **readiness state**, **reviewer
decision**, **map-ready data**, **version + input hashes**. No single surface
aggregates all nine today. The notebook's marginal value is *aggregation +
interactivity*, and every missing piece already has a public core producer, so
the notebook stays a thin shell.

## Section → producer map (all verified present, all headless/no-arcpy)

| Section | Producer | Notes |
|---|---|---|
| Version + input hashes | `importlib.metadata.version("autogis")` **with pyproject fallback** (raises `PackageNotFoundError` in a plain venv); input SHA256 via `source_registry.compute_sha256` | reuse, no new code |
| Import summary + QA findings | batch-import CLI outputs: manifest CSV + result-records CSV + QA report CSV | display CSVs |
| Completeness | `identify_data_gaps` | needs a schedule YAML in the fixture |
| Screening | `apply_screening_levels` | fixture ships its **own sanitized** screening YAML — DRAFT stub untouched |
| Comparisons | `compare_events(current_event_date=, stable_threshold=)` | **needs ≥2 events** |
| Trends | `build_history_report` + report HTML trend section | |
| Map-ready data | `export_geojson.results_to_feature_collection` | display feature count / sample |
| Readiness state | `evaluate_readiness(...)` | reads the notebook's OWN run (`WORK/run_history.csv`, `AUTOGIS_RUN_HISTORY`-redirected), scoped to producers that record a site identity (`apply-screening`) — not a canned fixture |
| Reviewer decision | `ingest_reviewer_comments` tracker summary | "none yet" is valid |
| 5-in-1 render | `generate_event_report_html(...)` via `IPython.display.HTML` | **public** renderer, not private `_gather_event_data` |

**Cut from slice 1 (YAGNI):** `compliance_summary`, `qc_sample_summary` — not
among the roadmap's nine sections (`qc_sample_summary` even carries a `ponytail:`
deferral already).

## Cell plan (6 cells, no domain logic in any cell)

1. Provenance: AutoGIS version (defensive) + SHA256 of every input CSV.
2. Run the headless pipeline against the fixture event via the CLI
   (`subprocess`): screen → compare → history → gaps → rpd, with
   `AUTOGIS_RUN_HISTORY` redirected into a temp `WORK` dir so the recorder never
   touches a real `run_history.csv`. This populates the run history readiness
   reads in cell 7 — no fixture run-history needed.
3. Import summary: display manifest + QA CSVs.
4. `generate_event_report_html(...)` inline — 5 sections at once.
5. Map-ready: `results_to_feature_collection` summary (count + one sample).
6. Readiness (`evaluate_readiness`) + reviewer-tracker summary.

## The real work — sanitized reference event fixture

Slice 1's actual cost. `gen-synthetic-workbook` is a **dead end** (its output
has no lab profile / importer path to a results CSV — only cell-level parser
tests consume it). Build instead, via the existing `make_*_fixture.py` pattern:

- one **2-event** synthetic EDD workbook fixture (2 events so comparisons/trends
  are non-empty),
- a small **schedule YAML** for completeness,
- a **sanitized screening YAML** scoped to the fixture's analytes (keeps the
  pre-production `screening_levels.yaml` DRAFT stub intact, per CLAUDE.md).

All generated/synthetic — **no client data, no redaction dependency.**

## Verification (gate: "restart-and-run-all succeeds")

New optional extra `notebook = ["nbclient", "ipykernel"]` (user-approved; the
only new dependency in the phase — opt-in, not in the default install). One
`pytest.importorskip("nbclient")`-gated test executes the notebook fresh against
the fixture in a real kernel and asserts it completes with no exceptions. This
is the honest proof of restart-run-all. The headless dev suite (which lacks the
extra) skips it cleanly and stays green.

## Non-goals / deferred

- No papermill, no nbstripout/`.gitattributes` automation, no notebook
  framework — one notebook doesn't justify it (YAGNI; revisit at notebook #2).
- No branching/parameterization of the notebook beyond the single fixture event.
- No LOCAL/arcpy path: every producer used is headless. A GDB-backed review
  surface, if ever wanted, is a separate phase.

## Risks

1. **Fixture is the critical path** — without ≥2 events, comparisons/trends
   render empty and the gate demo is hollow. Mitigated by building the 2-event
   fixture first and asserting non-empty comparison output in the test.
2. **`nbclient`/`ipykernel` dependency** — isolated to the opt-in extra; default
   install and the arcpy-free suite are unaffected.
3. **Commit the notebook outputs-stripped by hand** (the run-all test
   regenerates outputs in tmp); no tooling until a second notebook exists.
