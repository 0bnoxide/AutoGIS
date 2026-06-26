# ADR-019: Workgroup 2 scope — post-import QA + first reporting deliverable

**Status:** Accepted

**Date:** 2026-06-25

## Context

After the Lab EDD Importer (Tool 2.3, Workgroup 1), the roadmap contains 40+ unstarted
tools across data intake, QA/QC, analysis, cartographic, AGOL, field, and reporting
sections. Workgroup 2 must be scoped to a coherent, independently deliverable cluster
rather than working through the roadmap in document order.

Three candidate clusters were evaluated:

- **AGOL fast-track tools** (BuildDashboardDataMart, RouteSurvey123Submission, etc.) —
  rated "strong fit" in the hybrid harness evaluation but require live AGOL connectivity
  to test meaningfully; cannot be validated in an arcpy-free CI environment.
- **Environmental analysis tools** (GroundwaterElevationEvent, EstimateGWFlowDirection,
  BuildAnalyticalExceedanceEvent, etc.) — depend on exceedance logic being correct first;
  premature without ADR-018 in place.
- **Post-import QA + first reporting deliverable** — five items that form a complete
  dependency chain from EDD import to a PM-ready report-readiness gate; all headless or
  near-headless; no new external connectivity required.

## Decision

Workgroup 2 consists of five items in the following dependency order:

| # | Item | Roadmap ref | Effort est. |
|---|---|---|---|
| 1 | `evaluate_screening()` unit-conversion wire-up | ADR-018 | ~2 h |
| 2 | `ReconcileSampleLocations` (Tool 3.2) | §3.2 / §12 priority #2 | ~6–8 h |
| 3 | `EvaluateDuplicateRPD` (Tool 3.6) | §3.6 | ~4–5 h |
| 4 | `ExportAnalyticalSummaryTables` (Tool 9.1) | §9.1, ROI Round 3 #3 | ~5 h |
| 5 | `EvaluateReportReadiness` (Tool 9.0b) | §9.0b, strong-fit #6 | ~4–5 h |

**Dependency chain:** Tool 2.3 produces `Env_Samples` + `Env_AnalyticalResults` →
(1) screening comparisons are unit-correct → (2) location IDs reconcile to GIS features →
(3) RPD duplicate pairs are evaluated → (4) summary tables export to Excel → (5) event
readiness is gated before report delivery.

**Ordering rationale for item 1:** The unit-conversion fix (`result_parser.py:297-305`)
must precede items 3 and 4 because both consume exceedance flags. Building them on top of
a silent wrong-answer engine would require a retroactive correctness sweep.

**Ordering rationale for item 2:** `ReconcileSampleLocations` has an existing design
document (`docs/superpowers/plans/2026-06-24-phase-b-reconcile-locations.md`) and is
roadmap §12 priority #2. The most common post-import failure mode is `MW-1` vs `MW-01`
style ID mismatches that prevent EDD data from joining to GIS features. This must be
resolved before analysis tools consume joined data.

**Items deferred to Workgroup 3+:**

- AGOL fast-track tools: deferred until live-AGOL test infrastructure exists
- Boring/survey/drone tools: schema dataclasses are ready but no field workflow
  prerequisites exist yet; Workgroup 3 candidate
- Environmental analysis tools (contour, exceedance event, plume boundary): depend on
  unit-correct screening and reconciled location data; Workgroup 4 candidate

## Consequences

### Positive consequences

- Workgroup 2 delivers a complete end-to-end cycle: a PM can run an EDD import and
  receive a report-readiness verdict without switching to a different workflow
- All five items are headless or near-headless — CI can validate them without arcpy or
  AGOL credentials
- Item 1 unblocks environmental analysis tools that have been waiting on correct
  exceedance logic
- Item 2 uses an existing design document, reducing design overhead
- The cluster is independently shippable: Workgroup 3 can start from a clean state

### Negative consequences

- AGOL fast-track tools (high business value) are pushed to Workgroup 3, delaying
  dashboard and Survey123 capabilities
- `ReconcileSampleLocations` (~6–8 h) is the most complex item; if the design doc
  requires revision, it may stretch the workgroup timeline
- `ExportAnalyticalSummaryTables` produces Excel output — openpyxl formatting decisions
  may require iteration with the end user before the format is accepted

## Alternatives considered

1. **Start with AGOL fast-track tools:** BuildDashboardDataMart + Survey123 integration.
   - **Rejected:** Requires live AGOL connectivity; cannot be regression-tested in the
     arcpy-free CI environment. Risk of building on unvalidated exceedance logic.

2. **Continue in roadmap document order** (§2 data intake tools 2.4–2.7):
   MigrateLegacyMonitoringData, RegisterSourceDocuments, etc.
   - **Rejected:** These are intake tools, not QA tools. They extend the import pipeline
     horizontally rather than closing the import-to-report loop. No shared dependency
     chain.

3. **Start environmental analysis tools** (§4: GroundwaterElevationEvent,
   BuildAnalyticalExceedanceEvent):
   - **Rejected:** Depend on unit-correct exceedance logic (ADR-018, item 1 of this
     workgroup) and reconciled location data (item 2). Starting them before the
     pre-conditions are met would require revisiting them after WG2 anyway.

## Related decisions

- [ADR-016: Lab EDD Importer design](0016-lab-edd-importer-design.md) — Workgroup 1;
  output types this workgroup consumes
- [ADR-017: CSV-based run history log](0017-run-history-csv-log.md) — `RunHistory` is
  consumed by `EvaluateReportReadiness` (item 5)
- [ADR-018: Unit-conversion gate for screening evaluation](0018-screening-unit-conversion-invariant.md) —
  item 1 of this workgroup; pre-condition for items 3 and 4
