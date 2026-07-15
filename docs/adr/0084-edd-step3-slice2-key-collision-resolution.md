# ADR-0084: EDD Step 3 slice 2 — key-collision resolution (PROPOSAL)

**Status:** Proposed (awaiting sign-off — do not implement until Accepted)
**Date:** 2026-07-15
**Addresses:** #230
**Builds on:** ADR-0075 (frozen keys), ADR-0082 (slice 1, limitation recorded)

## Context

Real-file verification in PR #229 (EQuIS WMRD export `B25030623`, 575 rows)
surfaced two key collisions that idempotent dedup silently absorbs — **silent
data loss** — recorded as a known limitation in ADR-0082 and tracked in #230.
Slice 2 (mining / epar4 / NYSDEC profiles) multiplies exposure to the same
collision classes with every added dialect, so ADR-0082's slice map requires
slice 2 to **open with this key decision** rather than re-derive it per profile.

The two frozen keys (`gdb_schema.UNIQUE_KEYS`):

- **`Env_AnalyticalResults`** (11): `SiteID, Matrix, LocationID, SampleID,
  SampleDate, AnalyteCanonicalName, DepthIntervalText, SourceCell,
  ResultFraction, QCType, MethodDilutionKey`. **`MethodID` is not a component.**
- **`Env_QCResults`** (9): `SiteID, Matrix, AnalysisBatchID, SampleID, QCType,
  AnalyteCanonicalName, ResultFraction, MethodID, MethodDilutionKey`.

### Two distinct root causes
1. **Analytical (242/243 distinct):** the same analyte (Total Extractable
   Hydrocarbons) analyzed under **two different methods** on the same
   sample/date/fraction. Differing `MethodID/MethodName/AnalysisDate/ResultNumeric`,
   but identical on all 11 key parts → second method silently overwrites the first.
2. **QC (328/332 distinct):** surrogate rows (2× Decachlorobiphenyl, 2×
   Tetrachloro-m-xylene) identical on all 9 key parts, differing only in
   `ResultRawText/ResultNumeric/PercentRecovery` — a missing run-instance
   discriminator. `MethodID` is already in the QC key and does **not** help here.
   One of the four pairs differs *only* in `SourceRow`: a genuine source
   duplicate, not a key defect.

### The governing constraint (ADR-0075)
ADR-0075 froze both key **compositions** "never widened again," but decision #3
explicitly holds that **extending the per-reader `MethodDilutionKey` value
recipe later is safe** — "the frozen things are the key composition and column
names, not the recipe." That clause is the intended escape hatch for exactly
this situation.

## Decision (proposed)

Resolve both collisions by **extending the per-reader `MethodDilutionKey` value
recipe — never the frozen key composition.**

1. **Analytical — fold the method discriminator into the recipe.** For readers
   whose format reports multiple methods per analyte/sample (EQuIS family), the
   reader appends `MethodID` (or the format's method run-token) to its
   `MethodDilutionKey` composition. The frozen 11-component key is untouched;
   only the *value* the reader computes for `MethodDilutionKey` changes.
2. **QC — fold a run-instance discriminator into the recipe.** The QC reader
   appends a deterministic surrogate run-instance token (the lab's per-analysis
   instance id where present; otherwise a stable ordinal within the
   batch/sample/analyte/fraction group, assigned in source order) to its
   `MethodDilutionKey`. This distinguishes repeated surrogate recoveries without
   widening the 9-component QC key.
3. **Genuine source duplicates — explicit, visible policy.** Rows identical on
   every mapped field including the run-instance token (the `SourceRow`-only
   pair) are a true duplicate; idempotent dedup dropping one is *correct*, but it
   must not be silent — emit a QA record (`equis_true_duplicate`, WARNING) naming
   the collapsed rows.

Each reader's recipe extension is documented in its profile/ADR, per the
ADR-0075 §3 convention.

## Consequences

- **No frozen-key change**, so dedup behavior for every *other* lab format is
  untouched — the blast radius is one reader family, not the whole schema.
- **Re-import migration cost (must be surfaced):** appending a non-empty token to
  `MethodDilutionKey` changes the key *value* for all of that reader's rows, not
  only colliding ones. Because the token is non-empty, `_norm_key_part`'s
  NULL/`""` collapse does **not** absorb it, so re-importing WMRD data imported
  under the old recipe would create duplicates. Mitigation: land the recipe
  change before WMRD/EQuIS sees production use (slice 1 verified exactly one real
  file), and note the one-time re-key in the reader's changelog. This cost is
  inherent to any fix and is strictly smaller here than under key-widening.
- Colliding rows now persist distinctly; `n_results`/QC counts stop under-counting.
- Slice 2's new profiles inherit the pattern instead of re-deciding it.

## Alternatives considered

- **Widen the frozen keys** (add `MethodID` to the analytical key; a run-instance
  ordinal to the QC key). Rejected: directly breaks ADR-0075's "never widen
  again," and re-keys **every existing row of every format** → mass re-import
  duplication and a cross-format `_norm_key_part` interaction, for a problem
  localized to one reader family.
- **Hybrid** (recipe extension for analytical; a dedicated new discriminator
  *column* for the QC run-instance). Rejected as the default: a new schema column
  is a `SCHEMA_VERSION` bump and cross-format surface change for what the recipe
  hatch already handles; revisit only if a downstream tool needs the run-instance
  as a queryable field rather than a dedup discriminator.
- **Do nothing / keep as known limitation.** Rejected: silent data loss compounds
  with every slice-2 dialect.

## Related decisions
- [ADR-0075](0075-canonical-schema-expansion-step1.md) — frozen keys + §3
  value-recipe extensibility (the enabling clause)
- [ADR-0082](0082-edd-step3-equis-wmrd-slice1.md) — slice 1; recorded this limitation
- [ADR-0080](0080-wqx-step2-import.md) — prior per-reader `MethodDilutionKey`
  recipe extension (StatisticalBaseCode / ResultBasis fold) — precedent that
  recipe extension is the established mechanism
