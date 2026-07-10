# ADR-0080: WQX Step-2 import — wqx_csv reader on the frozen EDD seam

**Status:** Accepted

**Date:** 2026-07-10

**Parents:** [ADR-0075](0075-canonical-schema-expansion-step1.md) (frozen schema/key/seam),
ADR-0079 (merge gate — **this change must merge after PR #223**)

## Context

Step 1 (ADR-0075) froze the `Env_AnalyticalResults` schema and 11-component key that EPA WQX /
Water Quality Portal data needs; the merge gate (ADR-0079) routed every analyte-pivoting consumer
through the canonical-read policy. Step 2 adds the producer: the first real reader for a format
that populates `ResultFraction` and the method-detail fields. The Step-1 program text scoped it as
"one `wqx_reader.py` + one profile; no new abstraction layer" on the existing
`read_edd_file → normalize_edd_rows` seam. Design spec (advisor-reviewed pre-implementation):
`docs/superpowers/specs/2026-07-10-wqx-step2-import-design.md`; column names verified in the
2026-07-09 paper mapping.

## Decision

1. **`wqx_csv` format on the existing seam.** `autogis/core/envmon/wqx_reader.py` loads WQP's
   flat physical/chemical result CSV and applies the WQX-specific load-time transforms, writing
   synthesized `__wqx_*` columns onto each row dict; `autogis/config/lab_profiles/wqx.yaml`
   (DRAFT-bannered) maps canonical fields to real or synthesized columns. Transform logic in
   reader code, column→canonical mapping in YAML — the ADR-0075 seam boundary, unchanged.
   Registration: `"wqx_csv"` in `_VALID_FORMATS` + one dispatch branch in `read_edd_file`.
   Zero CLI change (`import-edd --profile-path` takes any profile).

2. **Non-detect synthesis.** WQX signals ND via `ResultDetectionConditionText` with an empty
   `ResultMeasureValue` (which would otherwise import as `IsNotAnalyzed=1`). Mapped condition
   texts (profile value_map `detection_condition`) synthesize the result token `ND` — plain `ND`,
   not `<limit`, because `_RE_NONDETECT` has no exponent form and unit-converted limits render
   in scientific notation. Unmapped condition + empty value → QA-WARN (the normalizer never
   surfaces parse warnings). Value-vs-condition conflict → condition wins + QA-WARN.

3. **Limit routing + convert-at-load (first enforcing code for ADR-0075 decision 5).**
   `DetectionQuantitationLimitMeasure/MeasureValue` routes to ReportingLimit or DetectionLimit by
   `DetectionQuantitationLimitTypeName` (profile value_map `limit_type_route`; unmapped → RL +
   QA-WARN — `LimitType` keeps the raw name for provenance). The limit is converted to result
   units via `common/units.convert`, with a same-unit short-circuit (so unregistered-but-equal
   units like pH/deg C never warn) and keep-raw + QA-WARN on `UnitError`. No
   `DetectionLimitUnits` column, per the frozen policy.

4. **`MethodDilutionKey` recipe — unconditional fold (refines ADR-0075 decision 3).** The WQX
   composite is the `|`-join of the non-empty of [`SubstanceDilutionFactor`,
   `StatisticalBaseCode`, `ResultWeightBasisText`]. ADR-0075 sketched folding the basis "when
   dual-reported"; a per-file dual-reported scan is cross-batch key-unstable — the same physical
   row imported from a file without vs. with its dry twin would compute different keys and
   duplicate instead of dedup. ADR-0075 froze the key composition and column names, "not the
   recipe"; the unconditional fold is per-row deterministic and cross-file stable. Settled now,
   before the first real import, because a recipe change after rows land means dup-on-reimport.

5. **Speciation fold.** Non-empty `MethodSpeciationName` folds into the analyte column
   (`Nitrate` + `as N` → `Nitrate as N`) so `AnalyteCanonicalName` incorporates speciation per
   the frozen key-safety convention. Companion dictionary rule, pinned by a test: a speciated
   alias must never map to an unspeciated canonical.

6. **Generic normalizer addition: optional `detection_limit` column.** `normalize_edd_rows`
   gains a `detection_limit` column resolution mirroring the existing `reporting_limit` override.
   This touches the "normalizer never changes" boundary deliberately: it is format-agnostic
   (every Step-3 EQuIS format carries `method_detection_limit` natively), and without it a
   DL-routed WQX limit has no landing path. Also: `read_edd_file` gains an optional
   `qa: QACollector` parameter (back-compatible) for reader-level warnings.

7. **Row policy.** `ResultStatusIdentifier == "Rejected"` (casefold) rows are skipped + QA-WARN;
   all other statuses import as-is. Unmapped `ActivityTypeCode` (WQX's only QC discriminator)
   imports QC-flagged — fail-safe: hidden from canonical reads — but QA-WARNs.

8. **Scope cuts (recorded):** CSV serialization only (JSON/XML are loader-only additions later);
   `ActivityDepthHeightMeasure`, `ActivityEnd*`→`SampleEndDate`, statistical columns beyond
   `StatisticalBaseCode`, WQX→CAS via EPA SRS, and `ResultValueTypeName` all deferred with
   dispositions in the spec (D8/D10).

## Consequences

- The first format that really populates `ResultFraction` can be imported; the Total/Dissolved
  pair that Step 1 exists to keep distinct is pinned end-to-end by tests
  (`tests/envmon/test_wqx_reader.py`, 26 tests incl. key distinctness through
  `compute_unique_key`).
- **Merge order is load-bearing:** per ADR-0079 this must land after PR #223, or a real WQX
  import could corrupt a summary through an unconverted consumer.
- The `wqx.yaml` vocabularies (detection conditions, limit-type routes, activity-type map,
  matrix map) are DRAFT until verified against a production WQP pull — every unmapped value
  fails safe with a QA-WARN, so a wrong guess is a config fix, not a code fix.
- The unconditional `MethodDilutionKey` fold means WQX keys can carry a basis component even
  when only one basis exists — harmless for uniqueness, and it buys cross-batch idempotency.

## Alternatives considered

- **`<{limit}` ND token** — rejected: silent parse failure on scientific-notation limits.
- **Conditional (dual-reported) `ResultBasis` fold** — rejected: cross-batch key instability
  (decision 4).
- **Profile-level `[subdivision, media]` matrix alternates** — impossible: `resolve_column`
  does not fall through on present-but-empty cells and CSV always supplies `""`; coalesced in
  the reader instead.
- **Routing unmapped limit types to neither column** — rejected: strands the value; RL default
  + WARN keeps it recoverable with provenance intact.

## Related decisions

- [ADR-0075](0075-canonical-schema-expansion-step1.md) — Step-1 frozen scope this implements
  against; ADR-0079 — the consumer-side gate this depends on.
