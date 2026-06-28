# ADR-0028 — Cloud-tools batch (2026-06-28): five headless QA / export / reporting tools

**Status:** Accepted
**Date:** 2026-06-28
**Deciders:** Greg / Claude Code
**Related:** ADR-0002 (arcpy-free core), ADR-0014 (schema-dataclass package),
ADR-0017 (run-history CSV log), ADR-0026 (night-implementer batch 2026-06-27)

---

## Context

Following the ADR-0026 batch, five more catalog tools were queued as fully
pre-written plans (`docs/superpowers/plans/2026-06-28-*.md`). As with ADR-0026,
the work runs in web/cloud sessions where **arcpy is absent**, so the batch was
deliberately scoped to headless, arcpy-free tools that honor the core invariant
(ADR-0002). The plans were drafted against a tree that had since moved ~48
commits, so the implementing session verified every reused seam
(`AnalyticalResultRecord`, `read_records_csv`, `QACollector`, `_render_qa`,
`RunHistory`, `capabilities.TOOLS`) before executing, and treated the plan code
as drafts — driven by TDD, not transcribed.

This ADR records the batch selection and the functional-structure decisions made
during implementation, including a new GeoJSON property-key convention, so they
are not re-litigated later.

---

## Decision

Ship five headless, arcpy-free tools, each registered `Runtime.CLOUD` in
`autogis/runtime/capabilities.py`, each independently committed and tested:

1. **CompareScheduleVsActual** — `envmon compare-schedule-vs-actual`
   → `core/envmon/schedule_vs_actual.py`
2. **DroneGCPCheckpointQA** — `envmon drone-checkpoint-qa`
   → `core/envmon/drone_checkpoint_qa.py`
3. **ExportGeoJSONResults** — `envmon export-geojson`
   → `core/envmon/export_geojson.py`
4. **GenerateMonitoringEventReport** — `envmon generate-event-report`
   → `core/envmon/generate_event_report.py`
5. **RunHistoryQueryCLI** — `envmon run-history`
   → CLI-only over `core/common/run_history.py` (no new core module)

### Shared conventions

- New core modules under `autogis/core/envmon/`, pure stdlib + existing helpers;
  **no arcpy, no arcgis, no openpyxl** (CSV/JSON/Markdown in and out).
- `AnalyticalResultRecord` CSV inputs loaded via the existing
  `read_records_csv(path, record_class)` (`evaluate_rpd_qa.py`).
- QA via `QACollector` (`core/common/qa.py`); CLI exit/report via the existing
  module-level `_render_qa(qa, report, fail_on)` in `cli.py`.
- TDD: failing tests first, one `tests/test_*.py` per tool (37 new tests).

### Functional-structure decisions (locked)

**CompareScheduleVsActual**
- Schedule is a plain YAML dict (`site_id`, `wells`, `required_analytes`,
  optional per-well `well_analytes`), parsed to a dict — not a config dataclass;
  no canonical schedule loader exists in `core/common/config.py`, so ADR-0003
  does not apply. The shape matches the existing `validate_schedule.py`.
- `well_analytes[well]` is a per-well **override** of `required_analytes` (use
  it *instead of* the site list for that well), matching the established
  `data_gaps.py` contract — the same key means the same thing across both tools.
  (Originally implemented as a union/"extras"; corrected on cold review to avoid
  divergent semantics for the same YAML key.)
- Status ∈ {`MISSING`, `SAMPLED`, `UNEXPECTED`}. UNEXPECTED covers **both**
  unexpected *wells* (LocationID absent from `wells`) **and** extra *analytes*
  sampled at a scheduled well but not on its schedule — so the advertised "gap +
  excess" analysis is complete, not half. (The latter case was added on cold
  review; see Consequences.)
- "Detected/sampled" keys on `AnalyteCanonicalName` (alias-stable), excludes
  `IsNotAnalyzed` rows, and is windowed: current event date inferred as the max
  `SampleDate` unless `--event-date` is given; results within `--window-days`
  (default 30) before it count.

**DroneGCPCheckpointQA**
- Pure-stdlib (`math`) accuracy check. Input CSV `gcp_id, expected_x/y/z,
  measured_x/y/z`. Horizontal error per point = `sqrt(dx² + dy²)`, vertical =
  `abs(dz)`; aggregate HRMS/VRMS are root-mean-square over points. Thresholds
  `--hrms-threshold` (0.05 m) / `--vrms-threshold` (0.10 m) in metres.
- QA categories: `no_checkpoints` (ERROR, empty input), `hrms_exceeds_threshold`
  / `vrms_exceeds_threshold` (ERROR), `individual_points_fail` (WARNING),
  `checkpoint_qa_complete` (INFO). This is a new "Tool 11.x" survey-QA category.

**ExportGeoJSONResults**
- One GeoJSON `Feature` per location; geometry `Point [x, y]` from a
  `location_id, x, y` coordinates CSV (CRS is the caller's — coordinates are
  passed through, not reprojected). Locations with no coordinates are skipped
  with a `missing_coords` WARNING.
- **Property-key convention:** per analyte, the latest record (by `SampleDate`)
  contributes `{key}_value` (DisplayText), `{key}_exceeds` (bool/None from
  `ExceedsScreeningLevel`), and `{key}_date` (ISO). `key` is the canonical
  analyte name with spaces→`_`, commas dropped, slashes→`_`. Distinct analytes
  that sanitize to the same key collide; the tool emits an `analyte_key_collision`
  WARNING (latter overwrites former) rather than dropping silently. (Added on
  cold review.)

**GenerateMonitoringEventReport**
- Pure stdlib, **Markdown** output (not Excel — ADR-008 does not apply). Inputs
  are the CSV outputs of sibling tools (results, compare-events, run-history,
  identify-data-gaps, evaluate-rpd-qa); **all optional** — a missing/absent file
  yields an empty section, never an error. Executive-summary table aggregates
  counts (results, exceedances, gaps, RPD errors). Section tables cap rows
  (history top-10, gaps top-20) with an overflow note.

**RunHistoryQueryCLI**
- CLI-only wrapper over the existing `RunHistory.query(site_id, tool_name, since,
  status)`; no new module. Filters `--site/--tool/--status/--since/--limit`;
  `--format table|csv|json` (default `table`). The human-readable record-count
  summary line is emitted **only** for `table` format, so `json`/`csv` output
  stays machine-parseable (a bug in the draft plan, fixed during implementation).
  Command name `run-history` is distinct from the existing report-rendering
  `run-history-report` (10.1).

---

## Consequences

### Positive

- Five more catalog tools shippable without arcpy, all reusing the established
  `read_records_csv` + `QACollector` + `_render_qa` pattern — low architectural
  risk, 37 new tests, full suite green (555 passing).
- DroneGCPCheckpointQA opens the drone survey-QA track; ExportGeoJSON gives a
  web/AGOL-consumable output with no ArcGIS Pro dependency; GenerateEventReport
  gives reviewers a single triage document; RunHistory makes the ADR-0017 run log
  queryable from the CLI.
- Cold review (envmon-spec-checker + pr-reviewer) ran on the branch: spec-checker
  PASS, pr-reviewer APPROVE. Two correctness should-fixes (schedule "excess"
  completeness, GeoJSON key-collision warning) were landed inline with tests.

### Negative

- ExportGeoJSON passes coordinates through unprojected; callers must supply a
  coordinate CSV already in the desired CRS. No reprojection seam yet.
- CompareScheduleVsActual depends on the same expected-schedule YAML shape as
  DataGaps (ADR-0026) but it is still not validated by `ValidateEnvConfig`
  (10.2) — a future wiring task carried over from ADR-0026.
- GenerateEventReport's Markdown tables do not escape literal `|` in cell values;
  low likelihood given the structured CSV inputs, documented as a known limit.

## Alternatives considered

- **EDD-headless line (fix-import-edd-headless + batch-import-edd):** higher
  foundational value but would spend two of five slots on one feature line and
  depends on a prerequisite fix; deferred to a focused follow-up.
- **export-history-summary-excel** instead of the `run-history` query CLI: the
  query CLI was chosen for machine-parseable JSON/CSV output usable in CI;
  Excel export remains a candidate fast-follow.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0017: run-history CSV log](0017-run-history-csv-log.md)
- [ADR-0026: night-implementer batch 2026-06-27](0026-night-implementer-batch-2026-06-27.md)
- `docs/ROADMAP_STATUS_2026-06-27.md`
