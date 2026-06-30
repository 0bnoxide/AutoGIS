# Autonomous 5-Feature Batch — Decision Log

**Date:** 2026-06-29
**Branch:** `feat/headless-envmon-batch-2026-06-28`
**Context:** User requested 5 features implemented autonomously, "use best
judgment and log those decisions accordingly." User unavailable for questions.

This file records each judgment call made during the run: what was chosen, what
was rejected, and why. One section per feature plus cross-cutting decisions.

---

## Cross-cutting decisions

### D0.1 — Feature selection criteria
**Chosen:** Implement 5 headless (arcpy-free) tools that already have an
**Approved** design spec under `docs/superpowers/specs/` but **no implementation
module** in `autogis/core/envmon/`.
**Why:** Headless tools are fully testable in the existing arcpy-free pytest
suite (clean 698-test baseline). Approved specs mean requirements are settled, so
no clarifying questions are needed — appropriate for an autonomous run. Picking
already-spec'd gaps avoids inventing scope.
**Rejected:** Tackling LOCAL (arcpy) tools (2–8) — can't be exercised headless,
so I couldn't verify them. Also rejected the open Guard KeyError bug (#62) and
Lab EDD Importer rework — those are fixes/reworks, not the "5 features" asked for
(though export-lab-request is adjacent and chosen).

### D0.2 — Selected features
1. `build-monitoring-report-appendix` (Tool 9.2) — multi-sheet Excel appendix
2. `list-available-env-tools` (Tool 10.1) — CLI tool registry/discoverability
3. `build-analytical-exceedance-event` (Tool 4.4) — exceedance selectors + tiers
4. `export-lab-request` (Tool 2.11) — lab analytical request workbook
5. `build-dashboard-data-mart` — denormalized `Dash_*` mart tables

### D0.3 — Record / I/O convention
**Chosen:** Follow the *lightweight* convention used by the most recent headless
batch on this branch (`max_result_dataset.py`, `compliance_summary.py`,
`qc_sample_summary.py`): a small `@dataclass` with snake_case fields, input as
raw `csv.DictReader` dict rows (keys `LocationID`, `AnalyteName`, `ResultValue`,
`ResultQualifier`, `ReportedUnits`, `SampleDate`, `SampleID`), screening levels
as a `{analyte: level}` dict, and a module-local CSV/Excel writer.
**Why:** Consistency with the sibling tools committed on this very branch matters
more than matching the older canonical `AnalyticalResultRecord`/`records_csv`
path. New CLI commands and tests will look identical to the existing batch.
**Rejected:** The canonical `gdb_schema.AnalyticalResultRecord` + `records_csv`
round-trip — heavier, and the new analytical tools don't need GDB field-name
fidelity.

### D0.4 — Sequencing for durability
One feature at a time: tests first (TDD), then module, then CLI wiring, then run
the **full** suite, then commit. Committed features survive a session
interruption; half-built ones don't.

---
<!-- per-feature sections appended as each feature lands -->

## Feature 1 — build-monitoring-report-appendix (Tool 9.2)

**Status:** DONE — `report_appendix_builder.py` + `build-report-appendix` CLI +
9 tests (8 unit + 1 CLI smoke). Full suite 707 passed.

### D1.1 — Sheet layout orientation
**Chosen:** rows = analytes, columns = (well × event-date), per the spec's
explicit "Sheet Layout" / Public-API docstring ("rows = analytes, cols = wells
then date sub-cols").
**Why:** The spec's prose "Approach" bullet ("Columns: Well ID, then one date
column per event") and its concrete layout table agree once you read the table:
each well heads a block of its event-date columns. Followed the concrete table.

### D1.2 — Summary rows are per-column
**Chosen:** "Detects" (d/n frequency) and "Max" summary rows computed **per
(well,date) column**, not per well aggregate.
**Why:** The spec's layout shows six summary values for six well-date columns
(`1/2 2/2 1/2 0/2 ...`), i.e. one per column. Detection frequency = detected
analytes / analytes-present in that column.

### D1.3 — Non-detect / detection / exceedance classification
**Chosen:** ND = qualifier in {ND,U,BDL} OR non-numeric ResultValue. Detected =
numeric & not ND. Exceedance = numeric value > screening level (strict `>`).
Yellow fill = detected ≤ SL; red = detected > SL; ND = no fill.
**Why:** Matches sibling `max_result_dataset.py` ND set and the spec's
conditional-format rules. Strict `>` so a value exactly at the SL is not flagged
an exceedance (conservative; the regulatory convention here treats SL as the
"not-to-exceed" ceiling — equal is compliant). Logged because `>=` is a
defensible alternative the reviewer may prefer.

## Feature 2 — list-available-env-tools (Tool 10.1)

**Status:** DONE — `ToolCapability` + `TOOL_REGISTRY` in `capabilities.py`,
`tool_registry.py` (get_all_tools/filter_tools/format_tool_table), `list-tools`
CLI + 11 tests (9 unit + 2 CLI smoke). Full suite 719 passed.

### D2.1 — Spec's `ToolCapability` did not exist; added parallel registry
**Chosen:** The spec assumed `capabilities.py` already had a `ToolCapability`
dataclass to extend. It does not — it has only `TOOLS: dict[str, Runtime]` and
`requires_arcpy()`. I added a NEW `ToolCapability` dataclass + `TOOL_REGISTRY`
list **alongside** `TOOLS`, leaving `TOOLS`/`requires_arcpy`/`Runtime`
untouched.
**Why:** `TOOLS`/`requires_arcpy` drive the runtime guard and have many call
sites; mutating their shape risks breaking the guard. An additive registry
satisfies the spec's intent (single metadata source in `capabilities.py`,
no separate YAML manifest, not click-introspection-only) with zero blast radius.
**Rejected:** Rewriting `TOOLS` into rich objects (high risk); deriving the list
purely from click `--help` (spec explicitly rejected — no metadata).

### D2.2 — `runtime` field is a display string, not the `Runtime` enum
**Chosen:** Registry `runtime` is one of `CLOUD|LOCAL|DRAFT` (strings).
`DRAFT` marks pre-production stubs (`manage-screening-levels`, per CLAUDE.md).
**Why:** The discovery view needs a "not production-ready" signal the `Runtime`
enum (CLOUD/LOCAL/HYBRID) can't express. Kept separate from the guard enum.

### D2.3 — Registry is hand-curated, covers all ~55 envmon commands
**Chosen:** Explicit seed list mapping each command → name/roadmap/runtime/
status/domain/description. Includes the two not-yet-built tools from this batch
(`build-analytical-exceedance-event`, `build-dashboard-data-mart`,
`export-lab-request`) so the registry is forward-consistent with the rest of
the run.
**Why:** A curated registry is the spec's chosen source of truth. Drift risk is
accepted as a known tradeoff (a future drift-guard test against the live click
group could be added). plan_path left blank for now (optional in the API).

## Feature 3 — build-analytical-exceedance-event (Tool 4.4)

**Status:** DONE — `build_exceedance_event.py` + `build-exceedance-event` CLI +
11 tests (10 unit + 1 CLI smoke). Full suite 730 passed.

### D3.1 — Grouping granularity: (location, analyte), not (location)
**Chosen:** Group rows by (LocationID, AnalyteName); apply the selection rule
within each group → one record per location-analyte pair.
**Why:** The spec's API docstring and test strategy both say "one record per
location-analyte pair", but its prose for `max_exceedance_per_location` reads
"per location: row with highest result/screening_level". Those only reconcile if
"per location" means per location-analyte. Chose the grouping that makes the
stated output shape correct; exceedance ratios are analyte-specific anyway.

### D3.2 — Tier boundaries lower-bound-inclusive; exceedance at ratio ≥ 1.0
**Chosen:** `lo <= ratio < hi` per tier; ratio 1.0 → "1x-2x"; has_exceedance =
ratio >= 1.0. ND or missing screening level → ratio None → tier "below",
has_exceedance False.
**Why:** Resolves the spec's overlapping bracket endpoints (its table lists both
"0–1.0 below" and "1.0–2.0 1x-2x"). Making 1.0 the start of exceedance keeps the
tier label and the has_exceedance flag mutually consistent (test 4).

### D3.3 — Did NOT reuse build_current_event.select_samples()
**Chosen:** Implemented selection inline rather than delegating to the existing
`select_samples()` in `build_current_event.py`.
**Why:** `select_samples` operates on differently-keyed dict rows
(`ExceedsScreening`, `NumericValue`, `IsDetected`) and returns *rows* for a
GDB-bound pivot, not the (loc,analyte) ratio/tier records this tool emits. A thin
wrapper would have needed an adapter layer larger than the direct implementation.
The spec called it a "thin wrapper" but the upstream signature mismatch made a
direct, sibling-consistent implementation simpler and clearer. Logged per advisor
note that the wrapper framing was aspirational.
## Feature 4 — export-lab-request (Tool 2.11) — DROPPED (superseded by PR #84)

**Status:** DROPPED from this PR. While this branch was being built, PR #84
landed an independent `lab_request_exporter.py` + `export-lab-request` command on
`main` from the same spec (identical public function names). When rebasing this
work onto current `main` for the PR, my Feature 4 was dropped in favor of #84's
already-merged version (user decision, 2026-06-29). My `list-tools` registry
entry for `export-lab-request` is retained and points at #84's command, which is
correct. The original Feature-4 implementation/tests remain on the local
`backup-5feat` tag if a later comparison is wanted.

## Feature 5 — build-dashboard-data-mart (Tool 6.7)

**Status:** DONE — `dashboard_data_mart.py` (10 transformation fns + arcpy
orchestrator) + LOCAL `build-dashboard-data-mart` CLI + 12 tests (11 unit + 1
guard smoke). Registered LOCAL in `capabilities.TOOLS`. Full suite 753 passed.

### D5.1 — LOCAL tool; only the transformation layer is unit-tested
**Chosen:** Per spec, this is a LOCAL (arcpy) tool. I implemented all 10
`build_dash_*` transformation functions as pure Python (fully tested) and the
`build_dashboard_data_mart()` orchestrator with `# pragma: no cover` (lazy arcpy
import, truncate + InsertCursor repopulate). CLI routes through `_guard()` like
tools 2–8.
**Why:** Matches the spec's chosen architecture (Python transform + arcpy I/O)
and the project invariant that core stays arcpy-free and testable headless. Added
the command to `capabilities.TOOLS` as `Runtime.LOCAL` so `_guard` resolves it
(otherwise it raises the "not registered" KeyError — the guard smoke test asserts
that message is absent).

### D5.2 — Trend lives in GWLevelSummary, not WellStatus (schema over spec test)
**Chosen:** `build_dash_well_status` emits `GWEDelta_ft` (per the Dash_WellStatus
schema, which has NO Trend column); the Rising/Falling/Stable `Trend` label is
emitted by `build_dash_gw_level_summary` (whose schema DOES have Trend). My tests
check Trend on the GWLevelSummary function.
**Why:** The spec's test-strategy item attributes `Trend` to
`build_dash_well_status`, but the `gdb_schema.py` Dash_WellStatus table has no
Trend field — that would write a column that doesn't exist. Followed the schema
(the durable contract) over the test-strategy prose. Thresholds: Δ>0.1 Rising,
Δ<-0.1 Falling, else Stable (per spec Transformation Notes).

### D5.3 — LabReceived / readiness use subset coverage
**Chosen:** `LabReceived` (and `LabReady`) = every sampled LocationID has ≥1
result row. Partial results → 0/False.
**Why:** Matches spec test 2 ("partial lab results → LabReceived=False") with a
simple, explainable rule. GIS/QA/Model readiness left 0 (those signals come from
other tools — `EvaluateReportReadiness` owns the full readiness logic).

---

## Run summary

All 5 features were implemented and committed individually on the original
branch (suite 698 → 754). Four ship in this PR (appendix, list-tools,
exceedance-event, dashboard-mart); Feature 4 (lab-request) was dropped as a
duplicate of the already-merged PR #84. Invariants verified: new core modules
import with no arcpy/arcgis present and have no core→adapter deps; DRAFT stubs
untouched. The `superpowers` TDD loop (red → green → full suite → commit) was
followed for each feature.

---

## Post-review corrections (advisor pass)

### D6.1 — Registry name drift fixed (the D2.3 risk materialized in-batch)
**Found:** The feature-2 registry seed listed `build-analytical-exceedance-event`,
but feature 3 registered the command as `build-exceedance-event`. So `list-tools`
advertised a non-existent command and omitted the real one. No test caught it
because nothing cross-checked registry names against live commands — exactly the
drift accepted in D2.3.
**Fix:** Corrected the seed `command` to `build-exceedance-event` (kept
`name=BuildAnalyticalExceedanceEvent`); also added a `list-tools` self-entry.
**Permanent guard:** Added `test_registry_commands_exist_in_live_cli` — a
ONE-DIRECTIONAL check (every registered command must exist in the live `envmon`
click group). Deliberately not the reverse, so top-level/agol/sub-group commands
stay out of scope (per D2.3). Suite 753 → 754.

### D6.2 — Dashboard orchestrator caveat
`build_dashboard_data_mart()` (arcpy path) is validated only by matching the
`build_dash_*` output dict keys against the `Dash_*` schemas in `gdb_schema.py`
(verified: SiteStatus/EventStatus/WellStatus/CurrentExceedances keys + LastUpdated
TEXT width all line up). The arcpy `TruncateTable`/`InsertCursor` runtime behavior
is unexercised headless and **needs one ArcGIS Pro smoke run** before production use.
