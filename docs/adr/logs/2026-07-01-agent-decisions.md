# Agent Decisions Log — 2026-07-01 Headless Tools Batch

Recorded by Claude Code during an autonomous 5-feature implementation session
(web/cloud, arcpy absent). See ADR-0032 for the full write-up; this log
captures the narrower judgment calls behind it.

---

## Feature Selection — 2026-07-01T00:00:00Z

**Decision:** Cross-referenced every candidate in
`docs/candidates/EVALUATION_RESULTS.md` against `capabilities.py`'s
`TOOL_REGISTRY` and `cli.py`'s registered commands before picking anything,
rather than trusting the doc's "strong fit" list at face value.

**Reasoning:** Most of the "strong fit" list turned out to already be
shipped (`ProcessLevelLoop`, `ImportRTKSurveyPoints`, `ImportFieldBoringLogs`,
`RegisterDroneFlight`, `DroneGCPCheckpointQA`, `ImportDroneProducts`,
`BuildDashboardDataMart`, `RouteSurvey123Submission`,
`BuildSurvey123XLSFormFromConfig`, `EvaluateReportReadiness`,
`ExportEventDatabaseSnapshot`). Notably `CreateSurvey123SamplingEvent` is
already shipped as `create-sampling-plan` (tool 7.2,
`core/envmon/sampling_plan.py`) — this was almost picked as feature #4
before the grep turned it up. Trusting the roadmap doc without verifying
against the registry would have produced a duplicate PR.

**Revisit if:** `EVALUATION_RESULTS.md` is regenerated/re-scored — the
already-shipped items should be marked off so future sessions don't re-derive
this cross-reference from scratch.

---

## Runtime filter — 2026-07-01T00:01:00Z

**Decision:** Excluded every AGOL-only candidate and every raster/kriging
candidate from consideration, keeping only pure-stdlib (`csv`/`math`/`json`/
`yaml`) gaps.

**Reasoning:** This session has no `arcgis` credentials to test AGOL calls
against, and no arcpy/scipy for raster work — per ADR-0002, code that can't
be exercised in this environment shouldn't be claimed as tested. Five
genuinely headless gaps were available without stretching scope, so no
AGOL/raster candidate needed a "trust me, it should work" implementation.

**Revisit if:** A future session has live AGOL credentials or a Pro conda
clone available — the excluded candidates (`PublishDashboardFromSpec`,
`AuditAGOLItemDependencies`, `BuildGroundwaterSurfaceModel`, etc.) remain
valid, just untestable here.

---

## RTKControlCheckReport vs DroneGCPCheckpointQA duplication risk — 2026-07-01T00:02:00Z

**Decision:** Gave `rtk-control-check` a different pass/fail convention than
the near-identical-looking `drone-checkpoint-qa` (all-points-must-pass vs.
RMS-threshold gate) instead of just copy-pasting the drone tool under a new
name.

**Reasoning:** A pure rename would have been indefensible under review — two
tools with identical math are one tool with two CLI names. The domains
actually have different real-world conventions (survey control networks
invalidate on a single bad point; photogrammetry checkpoints tolerate
outliers if aggregate RMS is in spec), so encoding that difference makes the
duplication a deliberate, load-bearing design choice rather than copy-paste.

**Revisit if:** A reviewer decides the two tools should share a common
`evaluate_positional_accuracy()` helper — refactoring `drone_checkpoint_qa.py`
was avoided in this batch specifically to keep the diff scoped to new files.

---

## GeneratePortfolioMetrics: no new schema — 2026-07-01T00:03:00Z

**Decision:** Portfolio rollup reuses `RunHistory.query()`/`.latest()` and
`evaluate_readiness()` as-is; the only new logic is `discover_site_ids()`
(a `set` over existing records) and a duplicated 2-line missing-tool check
for the human-readable CSV column.

**Reasoning:** `RunRecord` already carries `site_id`, so "portfolio" is just
"group by site_id" — inventing a new schema or a new readiness-check
implementation would have been unrequested scope. The 2-line duplication
(vs. parsing `evaluate_readiness`'s QA message strings to extract missing
tool names) was chosen because message-parsing is fragile against future
wording changes.

**Revisit if:** `evaluate_readiness()`'s signature changes to return
structured missing-tool data directly — the duplicated check here should
switch to consuming that instead.

---

## ExportSurveyToCADGIS scope cut — 2026-07-01T00:04:00Z

**Decision:** Shipped CSV + optional GeoJSON per feature-code-mapped layer;
explicitly did not attempt DWG/DXF/LandXML generation.

**Reasoning:** `EVALUATION_RESULTS.md` itself flagged CAD export format as an
unresolved blocker requiring either Civil 3D or an external library decision
— that decision isn't this session's to make unilaterally, and no such
library is currently a project dependency. Shipping the GIS-consumable half
now (which was the higher-value half of the original ask) rather than
blocking the whole feature on an unmade library choice.

**Revisit if:** The team picks a CAD export library/approach — add a
`--format dwg` (or similar) option to the same CLI command rather than a new
tool, since the point-grouping/layer-mapping logic would be identical.

---

## GenerateWellInspectionReports: Markdown, no photos — 2026-07-01T00:05:00Z

**Decision:** Markdown output (mirroring `generate_event_report.py`'s
established pattern), no photo-attachment handling.

**Reasoning:** Same rationale as ADR-0028's `GenerateMonitoringEventReport`:
no PDF/Word template system exists in this project yet, so picking one
would be a separate, larger design decision. Photo attachment workflow was
explicitly named as an undesigned blocker in `EVALUATION_RESULTS.md` — not
attempted here rather than inventing an ad hoc photo path.

**Revisit if:** A report-template system is designed for
`GenerateRegulatoryTables` or similar — this tool should switch to it rather
than staying Markdown-only, and photo handling should be designed once,
project-wide, not per-tool.

---

## Test strategy — 2026-07-01T00:06:00Z

**Decision:** One `tests/test_*.py` per tool (41 tests total) at the
core-function level, plus a manual CLI smoke pass (`--help` and one real
end-to-end invocation per command) run directly in the session rather than
committed as a new test file.

**Reasoning:** Every existing tool in this area (e.g. `drone_checkpoint_qa`)
tests the core function directly and has no dedicated CLI test file — CLI
wiring bugs (option-name typos, wrong import path) are real but rare, and a
one-time manual smoke pass catches them without adding a permanent
Click-invocation test suite that duplicates what the core tests already
cover.

**Revisit if:** A CLI wiring regression slips through in review — that would
be the signal to add `tests/test_cli_envmon.py`-style smoke tests for these
five commands going forward.
