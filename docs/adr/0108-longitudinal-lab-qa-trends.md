# ADR-0108: Longitudinal laboratory-QA trends (Phase 7, slice 1)

**Status:** Accepted

**Date:** 2026-07-23

## Context

Production-roadmap Phase 7 (`docs/production-roadmap.md`) calls for trending
blank detections, surrogate/spike recovery, duplicate RPD, reporting-limit
changes, and qualifier frequency by laboratory, method, matrix, and analyte —
beginning with deterministic rules and CSV/XLSX outputs, without automating
professional conclusions.

The lab-QC data already lands canonically: `equis_reader` forks lab-QC rows into
the `Env_QCResults` table (`QCResultRecord`, `gdb_schema.py`), which carries
`QCType`, `PercentRecovery` + `RecoveryLowerLimit`/`UpperLimit`, `RPD` +
`RPDControlLimit`, `ResultNumeric`/`IsNonDetect`, `ReportingLimit`, `Qualifier`,
`MethodID`, `Matrix`, `AnalyteName`, and `AnalysisDate` — everything the trends
need except a laboratory identifier (see constraints below).

Constraints discovered during design:

1. **No headless QC export.** `export_event_snapshot` copies `Env_QCResults`
   GDB→GDB and requires arcpy (`# pragma: no cover`). Nothing emits QC results to
   CSV headlessly. So the tool's input contract is defined explicitly as a CSV of
   `QCResultRecord` rows (what an `Env_QCResults` export naturally produces),
   read via the existing `records_csv`; production of that CSV is out of slice 1.
2. **No `LabName` on `Env_QCResults`.** Regular results (`Env_AnalyticalResults`)
   carry `lab`, but the QC table does not — so "by laboratory" grouping is
   deferred until the schema adds it.
3. **Gate verification is not autonomously closable.** The gate's "results
   reproduce a manually reviewed set of historical events" leg needs real
   historical QC data and a reviewer; a synthetic fixture authored alongside the
   rule would test the rule against itself. That leg is recorded below as a
   Proposed acceptance item for owner sign-off (gate amendments are owner
   decisions — cf. ADR-0091).

## Decision

Add `autogis/core/envmon/lab_qa_trends.py` (headless, arcpy-free) and the
`envmon lab-qa-trends` CLI. Slice 1 covers **two** of the five dimensions:

- **Recovery** — membership is data-driven: any `QCResultRecord` with a
  `PercentRecovery` participates (exactly surrogates/LCS/MS/CCV…). Flagged when
  recovery is outside `[RecoveryLowerLimit, RecoveryUpperLimit]`; row limits from
  the lab EDD take precedence, a cited configurable default window (70–130%) is
  the fallback.
- **Blank** — QC rows whose `QCType` is a blank (configurable set + `*BLANK*`
  substring) flagged as detected when `ResultNumeric >= blank_rl_multiple × RL`
  (default 1.0). Missing RL → positive result counts as detected, with a QA
  warning rather than a guessed limit.

Both aggregate per `(Matrix, MethodID, Analyte)` across all events, reporting
`n_total`, `n_flagged`, `flag_rate`, the `AnalysisDate` span, the worst offender,
and — per the gate — **the threshold applied and its citation on every output
row**. Thresholds (`LabQAThresholds`) are configurable via an optional
YAML/JSON. Output is a `LabQATrendRow` CSV via `records_csv`.

The CLI accepts repeatable `--qc-results` (one CSV per event = the longitudinal
set), optional `--thresholds`, and `--out`. Registered `lab-qa-trends` (CLOUD)
in `capabilities.TOOLS` + `_REGISTRY_SEED`.

## Consequences

### Positive

- Deterministic longitudinal recovery + blank trending with cited, configurable,
  in-output thresholds — the buildable core of the Phase 7 gate.
- Reuses `records_csv` + `QCResultRecord` (no new schema, no new dependency);
  data-driven recovery membership avoids a drift-prone QC-type enum.
- Synthetic-fixture-verified (rules/arithmetic) + real-console CLI run.

### Negative / deferred

- **Three dimensions deferred** (additive later slices): duplicate RPD (data is
  in `Env_QCResults.RPD`/`Env_RPDResults`), reporting-limit changes, qualifier
  frequency.
- **"By laboratory" grouping deferred** — `Env_QCResults` lacks `LabName`; add
  the column (and populate it in `equis_reader`) to enable it.
- **Headless QC-results exporter is a dependency, not built here** — the tool
  reads an `Env_QCResults`-shaped CSV; a LOCAL export-snapshot-to-CSV (or a
  headless exporter) must produce it for a real run.
- **No XLSX output** yet (roadmap allows CSV *or* XLSX; CSV shipped).

### Proposed gate item (owner sign-off)

The Phase 7 production gate's "results reproduce a manually reviewed set of
historical events" leg is **not** met by this slice and cannot be self-certified.
Proposed for owner acceptance: run `lab-qa-trends` against a real multi-event QC
export the owner has manually reviewed, and confirm the flagged counts match the
reviewer's findings. Until then Phase 7 is "slice 1 shipped; acceptance pending".

## Alternatives considered

- **Invent a bespoke input schema** — rejected; `QCResultRecord` already is the
  canonical QC row and `records_csv` round-trips it.
- **Hardcode a recovery QC-type list** — rejected; data-driven "has
  PercentRecovery" is exact and drift-free.
- **Build all five dimensions now** — rejected; roadmap says begin deterministic
  and small. Recovery + blank share one aggregation engine the rest plug into.
- **Guess a blank limit when RL is absent** — rejected; flag the ambiguity (QA
  warning) instead of fabricating a threshold.

## Related decisions

- [ADR-0087: Post-catalog production roadmap ordering](0087-post-catalog-production-roadmap.md)
- [ADR-0091: Pro qualification runner — precedent for owner gate amendment](0091-arcgis-pro-qualification-runner.md)
- `Env_QCResults` schema + `QCResultRecord` (`core/envmon/gdb_schema.py`); EQuIS QC fork (`equis_reader.py`)
