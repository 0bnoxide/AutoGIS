# ADR-0026 — Night-implementer batch (2026-06-27): three headless analysis/survey/QA tools

**Status:** Accepted
**Date:** 2026-06-27
**Deciders:** Greg / Claude Code
**Related:** ADR-0002 (arcpy-free core), ADR-0014 (schema-dataclass package),
ADR-0018 (upgrade-schema), ADR-0017 (run-history), ADR-0025 (EDD duplicate RPD)

---

## Context

A roadmap status review (`docs/ROADMAP_STATUS_2026-06-27.md`) reconciled the
79-tool envmon catalog against the codebase: ~17 tools fully shipped, ~8 with
foundation laid, ~54 not started. We need to queue a batch of work for the
night implementer, which runs in web/cloud sessions where **arcpy is absent**, so
candidate tools must honor the arcpy-free core invariant (ADR-0002).

Several high-headline remaining tools are poor fits for that constraint:

- AGOL/dashboard tools (6.7–6.11) need a live AGOL connection and item registry.
- Cartography tools (5.6 `GenerateSiteMapSeries`, 5.8 `UpdateLayoutDynamicText`)
  are arcpy/`.pyt`-bound.
- AI-assisted tools (§11) need an LLM seam that doesn't exist yet.

Conversely, the schema package (ADR-0014) + upgrade-schema (ADR-0018) already
shipped the *tables* for the survey, boring, drone, and dashboard domains. The
processing logic that fills them is pure-Python, deterministic, and testable —
the ideal night-implementer shape.

This ADR also records the **functional-structure decisions** made by best
judgement while drafting the three plans, so the implementer does not re-litigate
them (per the session request to "use best judgement … and document so").

---

## Decision

Queue three headless, arcpy-free, schema-backed tools, each a single new `click`
command on the existing `envmon` group, each independently shippable:

1. **CompareMonitoringEvents (4.7)** — `envmon compare-events`
   → `core/envmon/compare_events.py`
2. **ProcessLevelLoop (8.1)** — `envmon process-level-loop`
   → `core/envmon/level_loop.py`
3. **IdentifyMonitoringDataGaps (4.10)** — `envmon identify-data-gaps`
   → `core/envmon/data_gaps.py`

Plans: `docs/superpowers/plans/2026-06-27-{compare-monitoring-events,
process-level-loop,identify-monitoring-data-gaps}.md`.

### Shared conventions (all three)

- New core module under `autogis/core/envmon/`, pure stdlib + existing helpers;
  **no arcpy, no arcgis, no openpyxl** (these three are CSV-in/CSV-out).
- Inputs loaded with the existing `read_records_csv(path, record_class)` loader
  (`evaluate_rpd_qa.py`) where the input is an `AnalyticalResultRecord` CSV.
- QA via `QACollector` (`core/common/qa.py`); CLI exit/report via the existing
  module-level `_render_qa(qa, report, fail_on)` in `cli.py`.
- Output is a list of new frozen `@dataclass` records (one per tool) written to
  CSV by the command, mirroring `RPDRecord` / `evaluate-rpd-qa`.
- TDD: write failing tests first, one `tests/test_*.py` per tool.

### Functional-structure decisions (best-judgement, locked for the implementer)

**CompareMonitoringEvents (4.7)**
- Pairing key is `(LocationID, AnalyteCanonicalName)` — canonical name, not raw
  `AnalyteName`, so alias drift between events does not split a series. Matrix is
  carried but not part of the key (a location is one matrix in practice; if a
  location appears under two matrices the tool emits a `mixed_matrix` WARNING and
  keys on `(LocationID, AnalyteCanonicalName, Matrix)` for that location only).
- "Current" vs "previous" events are chosen by `SampleDate` **per location**, not
  globally: current = latest date present for that location/analyte, previous =
  the next-latest. This tolerates locations sampled on different days within an
  event. A `--current-event-date` option overrides current to an explicit date.
- `TrendClass` ∈ {`INCREASED`, `DECREASED`, `STABLE`, `NEW_DETECTION`,
  `NO_LONGER_DETECTED`, `NONDETECT_BOTH`, `INDETERMINATE`}. `STABLE` band is
  `abs(PercentChange) <= --stable-threshold` (default 10.0). Non-detect handling:
  a value is "detected" iff `IsDetected == 1 and ResultNumeric is not None`.
  `Delta`/`PercentChange` are computed only when both events are detected;
  otherwise they are `None` and the class is one of the qualitative classes.
- Exceedance change fields `CurrentExceedance`/`PriorExceedance` come straight
  from `ExceedsScreeningLevel` (0/1/None → "Y"/"N"/"" string).

**ProcessLevelLoop (8.1)**
- Single-loop, height-of-instrument differential leveling. Input CSV columns map
  to `LevelLoopObservation` (`run_id, setup_id, point_id, backsight, foresight,
  intermediate_sight`). The first row of the loop must carry the benchmark as
  `point_id` with a known starting elevation supplied via `--known-elevation`
  (and `--benchmark-id`); the loop is assumed to close back on the same benchmark
  (last foresight returns to it).
- Computation per the standard rod-book rules: `HI = elevation_BM + backsight`;
  each foresight point `elevation = HI - foresight`; intermediate sights use the
  current `HI` without advancing it. Misclosure = `observed_closing_elevation -
  known_elevation`. Adjustment is distributed **equally per setup** (number of
  instrument setups), simplest defensible method; distance-weighted adjustment is
  explicitly out of scope for v1 (documented limitation).
- QA flags (categories): `misclosure_exceeds_tolerance` (ERROR when
  `abs(misclosure) > --tolerance`), `missing_backsight`/`missing_foresight`
  (ERROR), `benchmark_mismatch` (ERROR if loop doesn't close on the BM point_id),
  `negative_reading` (ERROR), `unclosed_loop` (WARNING if no closing shot found),
  `duplicate_turning_point` (WARNING). Tolerance default follows a `0.05 * sqrt(N)`
  ft rule on setups when `--tolerance` is omitted, with the formula surfaced in an
  INFO record.
- Outputs: one `LevelLoopRun` (with `misclosure_ft`, `closure_tolerance_ft`,
  `adjusted`) and the adjusted `LevelLoopObservation` rows. Writing
  `ElevationHistory` is **out of scope** here — that is tool 8.2
  (`UpdateWellElevationsFromLevelLoop`), kept separate so elevation history is
  only ever written behind the approval flag. This tool stops at adjusted
  elevations + QA.

**IdentifyMonitoringDataGaps (4.10)**
- Inputs: (a) an expected-schedule YAML (`--schedule`) listing, per site, the
  well network and the required analyte list (canonical names) for the event;
  (b) the actual `AnalyticalResultRecord` CSV (`--results-csv`); optional
  (c) a dry/inaccessible wells list (`--dry-wells`, CSV of LocationIDs with a
  reason). A `--event-date`/`--event-window-days` selects which results count.
- Gap record categories: `MISSING_WELL` (well in network, zero results in
  window), `MISSED_ANALYTE` (well sampled but a required analyte absent),
  `DRY_OR_INACCESSIBLE` (well in the dry list — informational, not an error),
  `UNEXPECTED_WELL` (results for a LocationID not in the network — WARNING).
- A well present in the dry list suppresses its `MISSING_WELL` gap (downgraded to
  `DRY_OR_INACCESSIBLE`/INFO), so genuinely-dry wells don't read as data loss.
- Output: one `DataGapRecord` per gap + QA summary; severities map
  MISSING_WELL/MISSED_ANALYTE → ERROR, UNEXPECTED_WELL → WARNING,
  DRY_OR_INACCESSIBLE → INFO.

---

## Consequences

### Positive

- Three more catalog tools shippable without arcpy, all reusing the established
  `read_records_csv` + `QACollector` + `_render_qa` + dataclass-record-to-CSV
  pattern — low architectural risk, high test coverage.
- ProcessLevelLoop activates the dormant `survey.py` level-loop schema, opening
  the Phase-4 survey track (8.2/8.5 build directly on it).
- CompareMonitoringEvents and IdentifyMonitoringDataGaps both consume the
  `AnalyticalResultRecord` CSV that import-edd / build-event already produce, so
  no new upstream dependency.

### Negative

- ProcessLevelLoop v1 uses equal-per-setup adjustment, not distance-weighted; a
  follow-up is needed for survey-grade distance weighting (documented limitation).
- CompareMonitoringEvents per-location event selection can pick an unintended
  "previous" event if historical records are sparse; mitigated by the explicit
  `--current-event-date` override and an INFO record naming the two dates chosen
  per series.
- DataGaps depends on a new expected-schedule YAML shape; the plan defines a
  minimal schema, but it is not yet validated by `ValidateEnvConfig` (10.2) —
  a future wiring task.

## Alternatives considered

- **AGOL/dashboard batch (6.7–6.11):** higher business value but needs a live
  AGOL seam and cannot run in arcpy-free night sessions. Deferred.
- **Boring-log import (8.0b):** good schema fit, but the input formats
  (gINT/Survey123/Excel) are heterogeneous and need a profile design pass first;
  larger than a single-night bite.
- **RunEnvJobQueue (10.4):** Phase-1 foundation value, but its job manifest
  needs to orchestrate already-registered commands; better done once more tools
  exist to orchestrate. Deferred.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0014: schema-dataclass package](0014-schema-dataclass-package.md)
- [ADR-0025: EDD duplicate RPD via IsDuplicate flag](0025-edd-duplicate-rpd-via-isduplicate-flag.md)
- `docs/ROADMAP_STATUS_2026-06-27.md`
