# Roadmap §8 Duplicate Tools — Fold Decision

**Date:** 2026-06-28
**Status:** Decided — no separate specs written for the two tools below

---

## Context

`docs/envmon-feature-roadmap.md` §8 re-uses the numbers "8.2 / 8.3 / 8.4" for a
second set of tools (lines ~1608–1657) that overlap earlier, more detailed §8 tools.
While closing the spec-coverage gap (every named tool gets a plan or spec), two of
these were judged **duplicates** and folded rather than given their own specs —
avoiding the duplicate-plan churn the repo already cleaned up once (PR-merge commit
`2af0976`, "resolve 8 duplicate-plan conflicts").

---

## Folded tools

### RegisterDroneSurveyProducts (roadmap §8 "8.4", line ~1641)

**Folds into:** `RegisterDroneFlight` (8.6) + `ImportDroneProducts` (8.8), both of
which already have plans/specs, and the `schema/drone.py` dataclasses
(`DroneFlight`, `DroneControlPoint`, `DroneCheckpoint`, `DroneProductRecord`) that
already ship. RegisterDroneSurveyProducts is an earlier, lower-detail restatement of
the same "catalog drone deliverables" need — orthomosaic / DSM / DEM / point cloud /
control report / CRS / accuracy notes — all covered by 8.6 (flight + product record)
and 8.8 (product import). No distinct behavior remains to spec.

### ValidateSurveyDeliverable (roadmap §8 "8.3", line ~1623)

**Folds into:** `ValidateRTKSurvey` (8.4), which has a plan
(`2026-06-27-validate-rtk-survey.md`) and a CLI command (`validate-rtk-survey`).
ValidateSurveyDeliverable's checks — duplicate point IDs, missing elevations, invalid
codes, coordinate outliers, wrong units, wrong CRS, missing control points — are the
same QA set `ValidateRTKSurvey` already covers. The only nominal difference is
"generic survey CSV/CAD/GIS" vs "RTK"; the validation logic is identical and the RTK
spec's check list is the superset. Generalizing the input format is a future
enhancement to `validate-rtk-survey`, not a separate tool.

---

## Coverage accounting

This makes "every named §2–11 tool has a plan or spec" well-defined:

```
79  named tools in the roadmap (§2–11)
-48  already name-covered by an existing plan/spec
- 2  shipped/implemented, design in code+ADR (GenerateDraftGWContours 4.2 = gw-contours;
                                               BuildAnalyticalCallouts 5.1 = build-callouts)
- 2  folded as duplicates (this document)
-27  new design specs written 2026-06-28 (this batch)
———
  0  remaining
```

## Scope boundary — what "all planned features" includes

The §2–11 catalog is **not** the only doc that names tools. The boundary used here:

- **IN — geostatistical / conditional tools (8) from `ROADMAP_UPDATE_2026-06-25.md`.**
  These are acknowledged-planned but "need architecture review before integration."
  Covered by `2026-06-28-geostatistical-conditional-tools-design.md` (a DEFERRED stub
  naming the shared blockers), the same way §11 AI tools are covered by a deferred
  stub. (One of the eight, `GenerateRegulatoryTables`, already has a full plan.)
- **OUT — `docs/candidates/` roadmaps.** The boring-survey-drone and
  survey123-agol-dashboard roadmaps are explicitly **pending hybrid-harness fit
  evaluation** (see memory `candidate-roadmaps-pending-evaluation` and
  `docs/candidates/EVALUATION_RESULTS.md`) — i.e. *candidate*, not yet *planned*. A few
  names there are not in §2–11 (e.g. `BackupAGOLProjectItems`,
  `BuildClientDeliverablePackage`, `GenerateWellInspectionReports`); these are
  deliberately excluded until the candidate roadmaps are accepted. When/if they are
  promoted into the canonical roadmap, they enter scope and need specs.
- **`IMPLEMENTATION_ROADMAP_PRIORITIZED.md`** names only tools already in §2–11 — no
  new tools, nothing additional to cover.
