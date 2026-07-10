# WQX Step-2 Import — vertical slice design

**Date:** 2026-07-10
**Status:** Implemented this session (Step 2 of the 3-step ingestion program)
**Parents:** `2026-07-08-canonical-schema-expansion-design.md` (Step-1 spec, AMENDMENT authoritative),
`2026-07-09-edd-paper-mapping-outcome.md` (verified WQX column map), ADR-0075 (frozen schema/key),
ADR-0079 (merge gate — **this slice must merge AFTER PR #223**).

## Problem

Step 1 froze the schema and key that WQX data needs; the merge gate (ADR-0079) converted every
analyte-pivoting consumer to the canonical-read policy. What remains is the producer: nothing can
read an EPA WQX / Water Quality Portal export today. Per the Step-1 program text, Step 2 is
"one `wqx_reader.py` + one profile; no new abstraction layer" on the existing
`read_edd_file → normalize_edd_rows` seam.

## What already exists (reuse — no new abstraction)

- WQP's physical/chemical result export is a **flat CSV** — one row per result, activity columns
  repeated. `csv.DictReader` loads it; the reader-seam contract (flat list of row dicts) holds.
- `normalize_edd_rows` already resolves **every Step-1 frozen field** through
  `profile.resolve_column` / `map_value`: `result_fraction`, `qc_type`, `dilution_factor`,
  `method`, `method_name`, `analysis_date`, `limit_type`, `lab_name`, `prep_method`, `prep_date`,
  `result_basis`, `method_speciation`. The normalizer does not change for WQX (one generic gap
  aside, D2 below).
- `core/common/units.py` (`convert`, `same_dimension`, `UnitError`) implements exactly the
  limit-unit conversion the load policy needs.
- CLI: `envmon import-edd --profile-path …` takes any profile YAML — **zero CLI change**.
- `result_parser.parse_result_value` already understands `ND` and `<value` tokens — non-detect
  synthesis reuses it rather than teaching the parser about WQX.

## What is genuinely new

A `wqx_reader.py` whose job is only the WQX-specific **load-time transforms** a flat column map
cannot express. It loads the CSV, applies per-row (and one per-file) transforms that write
**synthesized `__wqx_*` columns** into each row dict, and returns the same flat-dict contract.
The `wqx.yaml` profile maps canonical fields to real WQX columns or synthesized ones. Join
topology/transform logic in reader code; column→canonical mapping in YAML — exactly the frozen
seam boundary.

## Decisions

**D1 — Scope: WQP CSV serialization only in this slice.** The Step-1 program line names
"CSV/JSON/XML"; the paper mapping verified the CSV-oriented dictionary and a real USGS CSV
export, and WQP's default deliverable is CSV. The reader splits *loading* (`_load_csv`) from
*transforming* (`_transform_rows`), so JSON/XML later are loader-only additions feeding the same
transform — deferred until a real JSON/XML consumer exists (YAGNI).

**D2 — One generic normalizer addition: optional `detection_limit` column.** Today
`DetectionLimit` has no column path (only parsed-from-result-text). WQX's routed MDL needs one,
and so does every Step-3 format (`method_detection_limit` in mining/wmrd/epar4). This is a
format-agnostic gap in the Step-1 normalizer, mirroring the existing `reporting_limit` override —
not a seam change. ~6 lines.

**D3 — Non-detect synthesis (amended per advisor review).** WQX signals ND via
`ResultDetectionConditionText` with an empty `ResultMeasureValue` (which would otherwise parse as
BLANK → `IsNotAnalyzed=1` — silently wrong). The reader consults the profile value_map
`detection_condition` (raw text → `ND`); on a match it synthesizes `__wqx_result` = plain `ND` —
NOT `<{limit}`: `_RE_NONDETECT` has no exponent form, so a unit-converted limit rendered
`1e-05` would silently fail to parse as a nondetect; the reporting limit reaches the record via
the routed `__wqx_reporting_limit` column override instead, and `float()` parses scientific
notation fine. Rules the advisor review pinned down:
- Unmapped non-empty condition text + empty result → reader QA-WARN (`wqx_unmapped_detection_condition`)
  — the normalizer never surfaces parse warnings, so without this the row goes `IsNotAnalyzed=1`
  with zero trace.
- Non-empty `ResultMeasureValue` + mapped ND condition → the condition wins (`ND` + QA-WARN):
  a stated non-detect with a stray number is a data conflict, not a detection.
Profile ships the common vocabulary (`Not Detected`, `Not Present`, `Below Detection Limit`,
`Below Method Detection Limit`) under a **DRAFT banner** pending real-data verification;
`Detected Not Quantified` is deliberately NOT mapped — it is a detection.

**D4 — Limit routing + unit policy (first enforcing code for ADR-0075 decision 5).**
`DetectionQuantitationLimitMeasure/MeasureValue` routes to `__wqx_reporting_limit` or
`__wqx_detection_limit` by `DetectionQuantitationLimitTypeName`, via the profile value_map
`limit_type_route` (type name → `RL` | `DL`; unmapped → RL + QA-WARN, since WQX's generic limit
is closest to a reporting limit and `LimitType` keeps the raw name for provenance — routing to
neither would strand the value). The shipped route vocabulary (DRAFT-bannered): quantitation/
reporting-type names → RL; method-detection-level / EDL-type names → DL. Unit handling:
- Same-unit short-circuit first (strip/casefold equality, and empty limit unit = assume result
  units): otherwise every pH/temperature/turbidity row with units outside the registry raises a
  spurious `UnitError` warning even though no conversion is needed.
- Otherwise convert via `common/units.convert`; on `UnitError` keep the raw value + QA-WARN
  (`wqx_limit_unit_mismatch`) — convert-at-load, warn-on-unconvertible, per the frozen policy.
  No `DetectionLimitUnits` column.

**D5 — `MethodDilutionKey` recipe (amended per advisor review: unconditional fold).**
`__wqx_method_dilution_key` = `|`-join of the **non-empty** of [`SubstanceDilutionFactor`,
`StatisticalBaseCode`, `ResultWeightBasisText`]. ADR-0075 decision 3 sketched folding the basis
"when dual-reported", but a per-file dual-reported scan is cross-batch key-unstable: the same
physical wet row imported first from a file with no dry twin and later from a file that has one
computes two different keys → a duplicate GDB row instead of an idempotent dedup skip. The frozen
things are the key composition and column names, "not the recipe" (ADR-0075 decision 3 itself) —
the unconditional fold is per-row deterministic, cross-file stable, and deletes the group-scan
machinery. There is no legacy WQX data to stay compatible with; the recipe must be settled before
the first real import. Recorded as an explicit recipe refinement in the Step-2 ADR.

**D6 — Speciation fold, reader-side.** Where `MethodSpeciationName` is non-empty, the reader
folds it into the analyte column (`__wqx_analyte` = `"{CharacteristicName} {speciation}"`, e.g.
`Nitrate as N`) so `AnalyteCanonicalName` incorporates it per the frozen key-safety convention.
`MethodSpeciation` still lands in its own column via the normal mapping. Dictionary-miss on the
folded name falls back to the raw folded name + the existing WARN — key-safety preserved.
**Dictionary rule (guard):** a speciated alias must map to a speciated canonical — an alias like
`Nitrate as N → Nitrate` would strip speciation post-fold and recreate the as-N/as-NO3 key
collision the convention exists to prevent. Pinned by a test.

**D7 — QA threading.** `read_edd_file(path, profile)` gains an optional `qa: QACollector = None`
parameter (reader transforms emit warnings); `run_edd_import` constructs its collector before the
read. Back-compatible — existing callers pass nothing and the WQX reader no-ops its warnings into
a throwaway collector.

**D9 — Format registration (the one edit to frozen seam files).** `profile.format = "wqx_csv"`:
a new branch in `read_edd_file` dispatching to the reader module, plus `"wqx_csv"` added to
`_VALID_FORMATS` in `edd_profile.py`. Nothing else in the seam changes.

**D10 — Row-status handling.** Rows whose `ResultStatusIdentifier` casefolds to `rejected` are
**skipped with a QA-WARN** (`wqx_rejected_row_skipped`) — importing rejected results would let
them reach screening summaries as ordinary detections. `Preliminary`/`Provisional`/`Final` and
all other statuses import as-is (recorded disposition). `ResultValueTypeName` (`Estimated` etc.)
is deferred — `Qualifier` already carries `MeasureQualifierCode`, and `IsEstimated` derivation
reads the qualifier per the frozen convention; revisit only if real data shows estimated-value
rows without a J-type qualifier.

**D11 — Unmapped `ActivityTypeCode` → QA-WARN.** `ActivityTypeCode` is WQX's ONLY QC
discriminator. `map_value` passes unmapped codes through silently, making the row truthy-`QCType`
— imported but invisible to every canonical-read consumer with zero signal. The reader WARNs on
codes absent from the profile's `qc_type` value_map; the shipped map (DRAFT) sends known non-QC
codes (`Sample-Routine`, `Field Msr/Obs`, composite/integrated routine variants) → `""` and known
QC codes to canonical values (`Quality Control Sample-Field Replicate` → `FIELD_DUP`, blanks →
`FIELD_BLANK`/`TRIP_BLANK`/`EQUIPMENT_BLANK`). Truthy passthrough stays the fail-safe direction.

**D8 — Deliberately NOT mapped this slice** (recorded so nobody re-derives):
- `ActivityDepthHeightMeasure` → depth interval: single ambiguous-unit depth vs. top/bot
  interval is lossy; defer until real data shows a need.
- `ActivityEndDate`/`ActivityEndTime` → `SampleEndDate` etc.: deferred with the VI/duration
  fields per the Step-1 AMENDMENT (explicitly deferred "despite a WQX ActivityEnd* driver").
- Statistical columns beyond `StatisticalBaseCode` (which folds into the dilution key).
- WQX→CAS via EPA SRS lookup (Step-1 non-goal; `CASNumber` stays a Step-3 field).
- JSON/XML loaders (D1).

## Column map (from the verified paper mapping)

| canonical field | WQX column(s) |
|---|---|
| sample_id | `ActivityIdentifier` |
| location_id | `MonitoringLocationIdentifier` |
| event_date | `ActivityStartDate` |
| matrix | `__wqx_matrix` (reader coalesce: subdivision else media — `resolve_column` does NOT fall through on empty cells, and CSV always supplies `""`, so a profile-level alternate list cannot express this) |
| analyte | `__wqx_analyte` (reader: CharacteristicName + speciation fold) |
| result | `__wqx_result` (reader: ResultMeasureValue or ND synthesis) |
| units | `ResultMeasure/MeasureUnitCode` |
| qualifier | `MeasureQualifierCode` |
| reporting_limit | `__wqx_reporting_limit` (reader: routed + unit-converted) |
| detection_limit | `__wqx_detection_limit` (reader: routed + unit-converted; new normalizer column, D2) |
| result_fraction | `ResultSampleFractionText` |
| qc_type | `ActivityTypeCode` via value_map (`Sample-Routine` → `""`; QC types → canonical codes; unmapped raw passes through truthy = safe direction, canonical read drops it) |
| dilution_factor | `__wqx_method_dilution_key` (reader composite, D5) |
| method | `ResultAnalyticalMethod/MethodIdentifier` |
| method_name | `ResultAnalyticalMethod/MethodName` |
| analysis_date | `AnalysisStartDate` |
| limit_type | `DetectionQuantitationLimitTypeName` |
| lab_name | `LaboratoryName` |
| prep_method | `LabSamplePreparationMethod/MethodIdentifier` |
| prep_date | `PreparationStartDate` |
| result_basis | `ResultWeightBasisText` |
| method_speciation | `MethodSpeciationName` |
| lab_sample_id | `SampleContainerLabelName` (nearest equivalent, weak — per mapping doc) |

Matrix value_map (minimal, verified-only): `Groundwater→GW`, `Soil→SOIL`; everything else passes
through as-is with the existing `edd_unknown_matrix` warning.

## Testing (all arcpy-free)

- Unit tests per transform: ND synthesis (mapped condition → `ND`; unmapped condition → WARN;
  value-vs-condition conflict → condition wins + WARN), limit routing (RL/DL/unmapped→RL+WARN),
  limit-unit conversion (convertible; same-unit short-circuit incl. unregistered units;
  UnitError-keep-raw-warn), dilution-key composite (each component alone; all three; all empty →
  `""`), speciation fold (+ dictionary rule: speciated alias maps to speciated canonical),
  matrix coalesce, rejected-row skip + WARN, unmapped ActivityTypeCode WARN.
- End-to-end: synthetic WQP CSV → `read_edd_file` + `normalize_edd_rows` → records; assert the
  frozen fields land (`ResultFraction`, `QCType` mapping, `MethodID`, `AnalysisDate`, `LimitType`,
  `LabName`, `PrepMethodID`, `ResultBasis`, `MethodSpeciation`).
- Key distinctness: a Total/Dissolved pair on one grain yields two distinct
  `compute_unique_key()` values (the collision Step 1 exists to prevent).
- Profile validation: `wqx.yaml` passes `validate_edd_profile`.

## Merge order

This PR is gated by ADR-0079: it must merge **after** PR #223 (the consumer conversions), or the
first real Total/Dissolved import could corrupt a summary through an unconverted consumer.
