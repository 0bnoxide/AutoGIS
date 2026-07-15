# ADR-0084: EDD Step 3 slice 2 — key-collision resolution

**Status:** Accepted, **partially reverted post-merge** — the analytical method
fold stands; the QC run-instance auto-resolution was reverted to a fail-safe
blocking guard after a post-merge review found two data-integrity gaps. See
**Post-merge revision (2026-07-15)** below. The QC half of #230 is reopened.
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
   must not be silent — emit a QA record (WARNING, named `edd_true_duplicate` as
   built — see Implementation refinement 4) naming the collapsed rows.

Each reader's recipe extension is documented in its profile/ADR, per the
ADR-0075 §3 convention.

## Consequences

- **No frozen-key change**, so dedup behavior for every *other* lab format is
  untouched — the blast radius is one reader family, not the whole schema. (One
  caveat: the QC run-instance token lives in `normalize_qc_rows`, which every
  format's QC stream flows through, so the surrogate-rerun resolution applies to
  any profile that ever produces colliding QC rows — a strict improvement, not a
  regression, but not EQuIS-exclusive. The analytical method fold *is*
  EQuIS-only, in `equis_reader`.)
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

## Implementation (as built)

Five refinements settled while implementing option 1; the judgment calls are
logged in `docs/adr/logs/2026-07-15-agent-decisions.md`.

1. **Method fold is analytical-stream-only.** `equis_reader._compose_dilution_key`
   appends `lab_anl_method_name` only for non-QC rows. `MethodID` is already a
   frozen `Env_QCResults` key part, so folding it into the QC recipe would
   distinguish nothing and only churn QC keys on reimport. Still per-row
   deterministic (the stream is intrinsic to the row, not batch state) — no
   conflict with the ADR-0080/0082 "same physical row keys the same" rule.
2. **The QC run-instance token is surgical.** `edd_importer._assign_qc_run_instance`
   appends `#N` to `MethodDilutionKey` only inside groups that actually collide
   on the frozen key, so a non-repeated QC row keeps its slice-1 key verbatim.
   This shrinks the reimport re-key from "every QC row" to "colliding QC rows
   only" (plus every analytical row from refinement 1) — strictly smaller than
   the Consequences note's worst case.
3. **`#N` numbers distinct data signatures, not raw positions.** Within a
   colliding group the ordinal is assigned by first appearance of each distinct
   `_data_signature` (all record fields except provenance), in source order. A
   real rerun (differing measured value) gets a fresh number and persists; a
   genuine duplicate (identical data, differing only in `SourceRow`) reuses its
   number and therefore still collapses — satisfying §3 without keeping a
   spurious row.
4. **Genuine-duplicate surfacing reuses the format-agnostic collision guard.**
   `detect_within_file_key_collisions` now splits a surviving collision: rows
   identical except provenance → non-blocking `edd_true_duplicate` WARNING;
   rows that differ → blocking `edd_key_collision` ERROR (the #230
   under-discrimination safety net, unchanged for formats without the recipe
   extension). The category is `edd_`-prefixed, not the proposal's `equis_`,
   to match its sibling `edd_key_collision` — the guard is not EQuIS-specific.
5. **The token is assigned at the reader→record seam** (`normalize_qc_rows`),
   the only place with canonical analyte names, parsed numeric values, and the
   record objects the frozen-key grouping needs — not the raw sheet reader.

No separate design spec: the decision and these refinements live here (ADR-0075
§3 already sanctions recipe extension as the mechanism, so no new architecture
was introduced).

## Post-merge revision (2026-07-15)

PR #235 merged before an incoming Codex cold review finished. That review found
two P1 data-integrity gaps in the QC run-instance mechanism (§2/§3) and one P2
storage-boundary issue. The QC mechanism was reverted to a fail-safe blocking
guard in a follow-up; the analytical method fold (§1) is unaffected and stands.

- **P1a — the ordinal is cohort/order-dependent, so not cross-file
  deterministic.** The surgical "only colliding groups get a token" choice
  means a physical row keys as `K` alone but `K#1` when a later or revised
  export also contains a rerun; append-only reimport then duplicates it, and a
  distinct rerun arriving alone retains `K` and is silently skipped against the
  stored `K`. This violates the ADR-0080/0082 per-row/cross-batch determinism
  invariant — an ordinal drawn from within-file cohort cannot satisfy it.
- **P1b — value equality does not prove a genuine duplicate.** `#N` numbered by
  data signature collapses two rows with equal normalized values, but separate
  surrogate analyses can legitimately share a rounded `ResultNumeric` /
  `PercentRecovery`. Collapsing them (to a non-blocking `edd_true_duplicate`
  WARNING) drops a distinct run — the exact silent loss this ADR set out to
  prevent, and *worse* than the pre-slice guard, which blocked every QC
  collision. Without a source-provided run identity, value equality is not
  sufficient evidence.
- **P2 — the composed key can exceed `MethodDilutionKey` TEXT(64).** The
  analytical method fold (and the withdrawn `#N`) append with no length bound;
  an overlength key dedups correctly in memory but truncates on write, breaking
  idempotency on reimport.

**Resolution (fail-safe, signed off 2026-07-15):**
1. **Reverted §2/§3** — `_assign_qc_run_instance` and the `edd_true_duplicate`
   downgrade are removed. A within-file QC collision is again a **blocking
   `edd_key_collision` ERROR** (never a silent collapse): no data is lost, a
   human adjudicates. The QC surrogate-rerun auto-import is **reopened** as a
   known limitation — it cannot be resolved without either a stable
   source-provided run identity or a DB-aware (read-existing-keys) import
   strategy. Both P1a and P1b are gaps of the ordinal approach itself, not just
   the surgical variant, so no ordinal reshaping fixes them.
2. **§1 stands** — the analytical `MethodID` fold is a per-row, source-alone
   deterministic value (the method is a real column), immune to P1a/P1b; it
   resolves the analytical half of #230 and is retained.
3. **P2 guarded** — `detect_overlength_keys` blocks (ERROR `edd_key_too_long`)
   any `MethodDilutionKey` over 64 chars before the append, so a truncatable
   key never reaches the GDB. Upgrade path if real recipes approach the limit:
   a bounded prefix+hash encoding, not raising the ceiling.

Net: #230's **analytical** collision is fixed and shipped; its **QC** collision
is downgraded from "silently dropped" (pre-slice and, worse, the merged §2/§3)
to "safely blocked, pending a run-identity design." Refinements 2–3 and 5 of the
Implementation section below described the withdrawn QC mechanism and no longer
apply; refinement 1 (analytical-only fold) and 4 (format-agnostic guard, now
always-blocking) stand.

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
