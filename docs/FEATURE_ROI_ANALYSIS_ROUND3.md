# AutoGIS Feature ROI Analysis — Round 3 (2026-06-24)

## Context

This round differs from [Round 2](FEATURE_ROI_ANALYSIS_ROUND2.md) in one important
way: it ranks candidates against **what is actually shipped today**, not against the
full wishlist in [`envmon-feature-roadmap.md`](envmon-feature-roadmap.md). Several
Round 2 Tier-1 items are now done, which changes the frontier.

### What is already built (do not re-propose)

| Capability | Status | Headless? |
|---|---|---|
| Inspect workbook + heuristic parser-profile draft | shipped | yes |
| `validate-config` — per-file **and** cross-file validators | shipped (Phase A) | yes |
| `manage-analyte-dict` | shipped (Phase A) | yes |
| Normalization: GW / soil / metals / IBI / **RPD (with recompute)** | shipped | yes |
| `validate-db` — cross-table integrity checks | shipped | core yes (arcpy read) |
| `build-event` — wide pivot w/ sample-selection + duplicate rules | shipped | core yes |
| Callouts, GW contours, figure export | shipped | no (arcpy) |
| AGOL publish-layer | shipped | yes |

### Committed-but-not-yet-coded

- **`ReconcileSampleLocations`** (Phase B) — a design + plan exist
  (`docs/superpowers/plans/2026-06-24-phase-b-reconcile-locations.md`); **no code yet.**

---

## The ranking lens

Round 2 ranked on **impact ÷ effort**. For this codebase that misses the dominant
multiplier: **headless (arcpy-free) tools are worth more per hour.** Per ADR-002 and
the `core/`/`adapters/` invariant, an arcpy-free tool can be:

- fully unit-tested in the 132-test suite (arcpy-free tests),
- run in CI and in the cloud/AGOL harness,
- executed without consuming an ArcGIS Pro license seat.

So Round 3 ranks on **(impact × testability) ÷ effort**. This pushes a few cheap,
pure-logic tools — buried in Round 2's Tier 3 — to the top, and pushes arcpy-bound
scaling tools down until the headless wins are banked.

---

## Tier 1 — Highest ROI (build next)

### 1. ReconcileSampleLocations — *finish Phase B*
- **Headless:** core analysis yes (well list can be supplied as data); arcpy only to
  read the live well layer in production.
- **Effort:** ~4–5h.
- **Why:** The single most common import failure — workbook IDs (`MW-1`) not matching
  the well feature class (`MW-01`, `MW1`, `HSS-11`/`HSS11`). The fuzzy-match core is
  pure and testable; output is read-only suggestions (no data mutation).
- **ROI:** Excellent. It is already the committed branch direction — finish it.

### 2. ValidateAndConvertUnits ⭐ — *most under-rated*
- **Headless:** yes (pure logic).
- **Effort:** ~3h.
- **Why:** Units appear in every config (analyte dictionary, screening levels) but
  **nothing validates them today.** A µg/L ↔ mg/L mismatch silently corrupts
  exceedance flags — i.e. a compliance-grade error that currently has zero guard. The
  tool plugs straight into the existing `screening_for` / `evaluate_screening` path,
  preserves the raw source unit, converts only when an explicit rule is configured,
  and raises a QA error on unknown units.
- **ROI:** Best pure-ROI play on the board — lowest effort, fully testable, guards the
  highest-stakes path.

### 3. ExportAnalyticalSummaryTables — *direct deliverable automation*
- **Headless:** yes (openpyxl only, same class as Tools 1/9/10).
- **Effort:** ~5h.
- **Why:** Automates the actual quarterly deliverable (current-event, historical-by-
  well, exceedance-only, by analyte group, soil-by-depth, RPD summary). Reads the
  existing record dataclasses; no arcpy. Hours saved per report, every report.
- **ROI:** Excellent.

---

## Tier 2 — High ROI (sequence after Tier 1)

### 4. CompareMonitoringEvents
- **Headless:** yes.
- **Effort:** ~4h.
- **Why:** Event-over-event delta + trend class (increased / decreased / stable / new
  detection / no longer detected) over normalized results. Pure logic, reuses the
  `build_event` pivot. Feeds map symbology and the change-log below.

### 5. WriteRunHistory + GenerateEventChangeLog
- **Headless:** yes.
- **Effort:** ~3h + ~2h.
- **Why:** `QACollector` is already thread-safe (ADR-005) — hook it to emit an
  append-only run record (RunID, tool, user, start/end, status, error/warning counts)
  and a human-readable per-event summary ("38 samples imported, 3 benzene
  exceedances, 1 unmatched location, 2 callout collisions"). Cheap observability that
  multiplies debug and PM capacity.

### 6. EvaluateDuplicateRPD — as an explicit QA mode
- **Headless:** yes.
- **Effort:** ~2h.
- **Why:** RPD is **already recomputed** in `normalize_rpd`; this only surfaces
  pass/fail against control limits as explicit QA flags (a sub-mode of `validate-db`).
  Near-free increment on existing logic.

---

## Tier 3 — Defer until headless wins are banked

### 7. BatchImport / RunEnvJobQueue
- **Headless:** no (arcpy + GDB writes).
- **Effort:** ~5–6h.
- **Why deferred:** Big scaling win, but needs GDB locking/transaction safety and is
  far less testable. Do it after the Tier 1–2 headless tools, when a manifest format
  and run-history substrate already exist to build on.

### Also deferred
- **Trend charts / Mann-Kendall** — needs a plotting dependency; specialized.
- **OptimizeCalloutPlacement** — arcpy geometry; medium-high effort; modifies feature
  positions (needs a review workflow).
- **AI-assisted tools** (draft profile, explain-QA, draft figure spec) — parked
  pending LLM model selection; valuable only with robust guardrails + human review.

---

## Summary — recommended next 3

| Priority | Tool | Headless | Effort | ROI |
|---:|---|:---:|---|---|
| **1** | `ReconcileSampleLocations` (finish Phase B) | core | 4–5h | Excellent |
| **2** | `ValidateAndConvertUnits` | yes | ~3h | Excellent (best $/hr) |
| **3** | `ExportAnalyticalSummaryTables` | yes | ~5h | Excellent |

Then **CompareMonitoringEvents** and **WriteRunHistory + ChangeLog** as the next
headless quick wins. Hold **BatchImport** until the manifest + run-history substrate
land.

## Notes

- All new tools follow ADR-001 (core + adapters), ADR-002 (arcpy-free core), and
  ADR-003 (canonical config locations).
- `ValidateAndConvertUnits` should never mutate raw source units; conversion is
  opt-in per configured rule, and unknown units are a QA error, not a silent pass.
- The decisive re-rank vs. Round 2: **ValidateAndConvertUnits** moves from Tier 3 to
  the #2 slot once testability and the unguarded compliance risk are weighed.
