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

## Feature 4 — export-comparison-excel (Tool 4.8)

**Status:** DONE — `export_comparison_excel.py` + `export-comparison-excel` CLI +
8 tests. Registered CLOUD. Suite 913 → 921.

### D4.1 — Fixed an off-by-one blank-row bug in the plan's openpyxl code
The plan set `ws.freeze_panes = ws["A2"]`. Accessing the cell object `ws["A2"]`
**materializes** an empty cell at row 2, so the subsequent `ws.append()` writes
the first data row at row 3 — leaving a blank row 2 and mis-placing the
TrendClass fill (which targets `ws.max_row`). The plan's 4 tests passed only
because they never checked cell positions; my stricter tests (fill at row 2,
exceedance-sheet row count) caught it. Fixed to the string form
`ws.freeze_panes = "A2"`.

### D4.2 — Dropped the plan's openpyxl try/except ImportError
openpyxl is a required dep (ADR-008); kept the lazy import (arcpy-free invariant)
but removed the dead missing-openpyxl branch.

## Feature 5 — generate-job-queue (Tool 10.4)

**Status:** DONE — `job_queue.py` + `generate-job-queue` CLI + 8 tests.
Registered CLOUD. Suite 921 → 929.

### D5.1 — Implemented per spec; filled the CLI body
Module given by the plan (orders jobs CLOUD→HYBRID→LOCAL from `capabilities.TOOLS`,
site×tool cross-product, per-tool/per-site arg merge). Filled the `...` CLI body:
read manifest YAML (sites/tools/args), write the queue as a JSON array of
`{tool, site_id, runtime, args, order}`. No deviations.

---

## Batch 3 run summary

All 5 headless tools implemented TDD-first, each committed individually. Suite
grew **830 → 929** (99 new tests, 0 failures). Three plan-bug fixes surfaced by
strict tests and logged: trend-charts empty-input crash (D1.1), soil-interval
ND/NO_DATA contradiction (D3.1), and the comparison-excel freeze_panes blank-row
off-by-one (D4.1). New CLI commands all registered in `TOOLS` + `TOOL_REGISTRY`
(CLOUD); the registry drift-guard stays green. Next: adversarial review before PR.

## Adversarial review (pre-PR) — findings + resolutions

Two independent review agents ran before the PR (as requested).

**envmon-spec-checker → PASS:** all 5 structural invariants verified empirically
(arcpy-free, no core→adapter, canonical config untouched, DRAFT stubs intact,
registry drift-guard holds).

**pr-reviewer → REQUEST CHANGES (3 blockers + should-fixes), all addressed:**

- **B1/B2 (export-comparison-excel) — producer/consumer contract mismatch.**
  Verified against primary source `compare_events.py`: `_exc()` emits
  CurrentExceedance as `"Y"/"N"/""` (my filter checked `"1"` → Exceedances sheet
  always empty), and `_classify()` emits `INCREASED/DECREASED/STABLE/
  NEW_DETECTION/NO_LONGER_DETECTED/NONDETECT_BOTH/INDETERMINATE` (my `_TREND_HEX`
  only matched `STABLE`). **Fix:** re-keyed `_TREND_HEX` on the real tokens;
  exceedance filter now matches `{Y,YES,1,TRUE}`. **Root cause was masked by
  self-consistent fixtures** — rewrote the test fixtures to use the producer's
  actual vocabulary so they exercise the real contract.
- **B3 (well_trend_charts) — chart/data corruption at ≥20 points.** Fixed-20-row
  blocks overwrote the prior series when `n ≥ 20` (the common quarterly-over-5yr
  case). **Fix:** `data_start_row += max(_BLOCK_ROWS, n + 2)`. Added a 24-point
  long-series regression test (with valid ISO dates) that fails on the old code.
- **Should-fix:** `select-soil-intervals` now exposes `--fail-on` like the other
  four commands; `load_history_csv` sorts dates via ISO parse (not lexicographic).
- **Nits:** guarded non-numeric GeoJSON coordinates (→ WARNING, x/y null);
  documented the `comment_id`-includes-text caveat; documented that soil HOTSPOT
  trusts the canonical `ExceedsScreeningLevel` flag.

Post-fix suite: **903 passed**.
