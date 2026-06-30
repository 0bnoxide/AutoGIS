# Headless Envmon Batch 3 — Decision Log

**Date:** 2026-06-30
**Branch:** `feat/headless-envmon-batch3-2026-06-30` (off fresh `main` @ #88)
**Context:** User requested a batch of 5 features, with emphasis on (a) being
mindful of parallel feature development / working from a fresh pull, and (b)
running a thorough adversarial review before opening the PR.

---

## D0.1 — Worked from a fresh `main`, verified no parallel collisions
Synced `main` (fast-forward) before branching; confirmed **no open PRs**; verified
each of the 5 target modules is absent and not shipped by the recent parallel
batches (#84 arcade/changelog/lab-request, #88 my prior 4 tools). This directly
addresses last round's collision (I duplicated #84's `export-lab-request`).

## D0.2 — Selected 5 diverse headless tools with existing Approved plans/specs
1. `generate-trend-charts` → `well_trend_charts.py` (openpyxl LineCharts)
2. `ingest-reviewer-comments` → `ingest_reviewer_comments.py` (CSV/GeoJSON/XLSX parser)
3. `select-soil-intervals` → `soil_interval_selector.py` (stdlib analytical tiering)
4. `export-comparison-excel` → `export_comparison_excel.py` (openpyxl conditional fmt)
5. `generate-job-queue` → `job_queue.py` (JSON job manifest)
Chosen for diversity (charts / parser / analytical / excel / orchestration) to
avoid three near-identical Excel exporters. All headless → testable arcpy-free.

## D0.3 — Baseline test flake investigated and explained (NOT absorbed into features)
First `pytest` on the freshly-checked-out branch reported 813 collected / 1 failed
(`test_registry_commands_exist_in_live_cli`, my drift guard from #88). Root cause:
**stale `__pycache__` from the previously-checked-out branch** (different file set)
caused transient mis-collection on the first invocation. After bytecode rewrite the
suite is **deterministically 830 collected / 0 failed across 10+ runs**, confirmed
with a full `__pycache__` purge. There is no `pytest-randomly` plugin installed, so
collection order is deterministic. Conclusion: a one-time branch-switch bytecode
artifact, not a product defect. Adversarial review will run against this
deterministic green baseline.

---
<!-- per-feature sections appended as each lands -->

## Feature 1 — generate-trend-charts (Tool 4.6)

**Status:** DONE — `well_trend_charts.py` + `generate-trend-charts` CLI + 17
tests. Registered CLOUD in `TOOLS` + `TOOL_REGISTRY`. Suite 830 → 847.

### D1.1 — Fixed the plan's empty-input zero-sheet crash proactively
The plan's `write_trend_charts` removed the default sheet then saved; with an
empty series list that yields a zero-sheet workbook and openpyxl raises
"At least one sheet must be visible" (the plan's own `test_write_empty_series_list`
exposed it). Added a placeholder "No Data" sheet — the same class of bug the
Copilot reviewer flagged on PR #88, fixed here before review.

### D1.2 — Dropped the plan's yaml try/except ImportError
The plan guarded `import yaml` with a json fallback. pyyaml is a required project
dep (cli.py already imports it at top), so the guard is dead code — used `yaml`
directly per the plan's own "no try/except ImportError" constraint.

## Feature 2 — ingest-reviewer-comments (Tool 9.4)

**Status:** DONE — `ingest_reviewer_comments.py` + `ingest-reviewer-comments`
CLI + 52 tests (44 core + 8 CLI). Registered CLOUD. Suite 847 → 899.

### D2.1 — Implemented the plan verbatim (it was fully specified)
The plan provided complete module + test code with stable comment-id hashing,
status lifecycle, multi-format parsers (CSV/GeoJSON/XLSX), and status-preserving
merge. Followed it faithfully; no deviations needed. Live AGOL fetch kept out of
scope (headless boundary) as the plan specifies.

## Feature 3 — select-soil-intervals (Tool — cartography intake)

**Status:** DONE — `soil_interval_selector.py` + `select-soil-intervals` CLI +
14 tests. Registered CLOUD. Suite 899 → 913.

### D3.1 — Fixed an internal contradiction in the plan (ND vs NO_DATA)
The plan's `assign_tier` returned `NO_DATA` for *any* None result_value, but its
own `test_assign_tier_nd` (result_value=None, screening_level=None) expects `ND`
while `test_assign_tier_no_data` (result_value=None, screening_level=5.0) expects
`NO_DATA`. The only differing field is `screening_level`. Implemented the split:
None result + screening_level present → NO_DATA (screened analyte, data gap);
None result + no screening_level → ND (true reported non-detect). Tests are the
contract; the plan's module code would have failed its own test.
