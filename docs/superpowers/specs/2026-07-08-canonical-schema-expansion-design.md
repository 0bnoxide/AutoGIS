# Canonical Envmon Schema Expansion + Key Redesign — Design (Step 1 of 3)

**Date:** 2026-07-08
**Status:** Proposed
**Program:** discipline-agnostic, multi-format lab-data ingestion (environmental only
for now — see Non-goals). This is **step 1 of 3**:

1. **This spec.** Canonical schema expansion + idempotency-key redesign.
2. WQX CSV/JSON/XML vertical slice (separate future spec — reuses the *existing*
   reader/normalizer seam, adds one `wqx_reader.py` + one profile; no new
   abstraction layer).
3. EQuIS-dialect deterministic profile drafting (separate future spec — Montana
   Mining, Montana WMRD, NYSDEC v5, EPA Region 4; parses each dialect's
   description-file + valid-values-enum deterministically rather than guessing;
   the heuristic synonym-matcher from the superseded
   `2026-07-08-lab-profile-drafting-tooling-design.md` becomes the fallback mode
   for opaque exports like the proprietary `SXSAMP` PFAS export).

Ordering is **strictly sequential, not parallelizable**, for reasons given below.
Steps 2 and 3 are out of scope for this document except where their requirements
constrain what this step must freeze now (additive-only migration means schema/key
names get exactly one shot — see Approach).

---

## Problem

The canonical GDB schema (`Env_Samples` / `Env_AnalyticalResults`,
`autogis/core/envmon/gdb_schema.py`) cannot currently represent data present in
real-world formats catalogued from a sample of regulatory and commercial lab
exports (EPA WQX, Montana Mining EDD, Montana WMRD/EQuIS, NYSDEC v5 EDD, EPA
Region 4 EDD, and a proprietary flat PFAS export): CAS registry numbers, QC/batch
linkage (method blanks, LCS, matrix spike/spike duplicate, surrogate recovery),
per-result method detail beyond what's captured today, and vapor-intrusion
building-survey attributes.

Worse, the current dedup key for `Env_AnalyticalResults` — `SiteID, Matrix,
LocationID, SampleID, SampleDate, AnalyteCanonicalName, DepthIntervalText,
SourceCell` (`gdb_schema.py:337-339`) — cannot distinguish rows that legitimately
share every one of those fields but differ in ways the current schema doesn't
track: **same-sample/same-analyte results split by fraction** (e.g. WQX's Total
vs. Dissolved), by **QC type** (a field duplicate vs. the parent result), or by
**method/dilution** (a diluted re-run of the same analyte). In the EDD import
path `SourceCell` is always `""` (`edd_importer.py:264`), so today these
legitimately-distinct rows collide and the second one is silently dropped by
`append_records_idempotent`'s dedup (`import_to_gdb.py:152`).

This is not a hypothetical risk confined to the richer EQuIS dialects — **it
already breaks on WQX data**, the very first format the ingestion program plans
to add (step 2). A WQX import of any sample with both Total and Dissolved results
for the same analyte will silently lose one of the two today.

## Non-goals

- **Any discipline beyond environmental water/soil/well data.** Per the user's
  explicit decision this session: one clean, documented extension seam for future
  disciplines (industrial hygiene, air monitoring), zero discipline-specific code.
  Nothing in this spec adds discipline abstraction — it only expands the
  environmental schema's own richness.
- **Building the WQX reader or the EQuIS-dialect drafter.** Steps 2 and 3.
- **Generalizing `LabEDDProfile` to support N-table relational sources** (a
  `sheets:`/`joins:` list, multi-key joins). Verified and rejected — see
  "Frozen boundary: the reader seam" below. `_read_two_tab_xlsx` and
  `sample_sheet`/`result_sheet` stay exactly as they are, serving only
  `flat_csv`/`two_tab_xlsx` forever. Relational flattening (needed for
  Mining/WMRD/NYSDEC's 3-38 sheet exports) is step 3's concern, done inside a
  per-dialect reader module, never by generalizing the shared profile shape.
- **A reader Protocol / pluggable-mapper registry.** Rejected per ADR-0016
  precedent and this project's tracer-bullet convention: the existing
  `read_edd_file` format dispatch + fully format-agnostic `normalize_edd_rows`
  (`edd_importer.py:75`, consumes only flat row dicts via
  `profile.resolve_column`) already *is* the extensible architecture. No new
  abstraction until a second real family (step 3) proves the repetition.
- **`DialectSpec` (step 3's richer draft-time profile model).** Confirmed step 3
  needs its own data model (type/required/enum/parent-table structure that
  `LabEDDProfile.columns` structurally cannot hold — see Verified Findings
  below) — but it's a step-3 concern, projected down to a flat `LabEDDProfile` at
  runtime. No step-1/2 change for this.
- **A WQX name → CAS number lookup (via EPA's SRS).** WQX emits
  `CharacteristicName` (a controlled vocabulary), not CAS directly; deriving CAS
  from it needs an SRS lookup. Out of scope — `cas_rn` stays unpopulated for
  WQX-sourced rows, exactly as expected since CAS is a step-3/EQuIS field.
- **Per-sheet column disambiguation for EQuIS's relational sheets** (e.g.
  `sys_sample_code` recurring across Location/Sample/Result sheets with
  different meaning). A step-3 reader-internal concern; the superseded
  `2026-07-08-lab-profile-drafting-tooling-design.md` (lines 152-167) already
  anticipated this and is cited there as precedent.
- **Whether EQuIS well-construction/water-level/VI sheets get read via this EDD
  path or the existing separate water-level path** (`WaterLevelRecord`,
  `Env_WaterLevels`, already has its own table/key — confirmed a producer for it
  from EQuIS sheets does not yet exist). A genuine scope fork; belongs in step
  3's spec, not resolved here.
- **Writing `validate_database`'s missing results-table duplicate-key check.**
  `validate_database.py:23` imports `UNIQUE_KEYS` but never uses it; its
  `duplicate_sample_key` check is hardcoded to `Env_Samples` only
  (`validate_database.py:77-82`). Worth doing eventually, driven off
  `UNIQUE_KEYS["Env_AnalyticalResults"]` rather than hardcoded — but it's
  optional integrity tooling, not required for this schema expansion to be safe.

---

## Approach

**Chosen shape: append-only fields with defaults, plus one new companion table
for lab-internal QC.** Verified constraints that drove this:

- Both `SampleRecord` and `AnalyticalResultRecord` are constructed with
  exhaustive keyword arguments in their only two producers
  (`table_normalizer.py:153/194`, `edd_importer.py:204/225`) and consumed by
  ~13 test-factory helpers across the suite that do the same. **Any new
  required field breaks both producers and every one of those factories.**
  Every new field on the existing tables must therefore be optional/defaulted.
- `create_or_update_gdb_schema` (`gdb_schema.py:412-454`) is **additive-only** —
  `AddField` for any column missing from an existing table, `CreateTable` only
  for a wholly missing table, **never** rename/retype/drop
  (module docstring, `gdb_schema.py:1-6`). This is a deliberate, ADR-0018-backed
  design choice (full migration-script tooling was explicitly rejected as
  overkill for an additive-only model) — meaning **every field/table name and
  every `UNIQUE_KEYS` composition frozen here gets exactly one shot.** There is
  no later rename.
- The existing migration mechanism — `upgrade_schema.py`'s
  `upgrade_gdb_schema()`, the `Env_SchemaVersion` version-stamp table, and the
  wired `autogis envmon upgrade-schema <gdb>` CLI — already does everything this
  expansion needs. **No new migration framework.** Bump `SCHEMA_VERSION`
  (`upgrade_schema.py:13`, currently `"2.1"`) to `"2.2"` as one coherent version
  bump covering all of this spec's changes at once (matches ADR-0018 §4's own
  precedent: all-at-once beats phased for a fully-designed schema change).

**Rejected: a full non-additive migration framework (Alembic-style).** Already
rejected by ADR-0018 for this project's additive-only model, and nothing here
changes that calculus — everything in this spec is either a new nullable column
or a new table.

**Rejected: folding lab-internal QC rows into `Env_AnalyticalResults` alongside
field results.** Verified interaction: the in-memory sample-level dedup layer
(`edd_importer.py:94-203`, `seen_sample_keys`) and `validate_database`'s
`orphan_result` check (`validate_database.py:99-105`, keyed
`SiteID/Matrix/SampleID`) both assume every analytical result traces back to a
real field `Env_Samples` row. Lab-internal QC (method blanks, LCS, matrix
spike/spike-dup with a lab-batch-only ID and no field sample) has no such row —
if written to `Env_AnalyticalResults`, every one would be flagged as an
`orphan_result` integrity error, which is exactly backwards. **A companion table
with its own `UNIQUE_KEYS` entry avoids teaching both of those layers a QC
exemption.**

---

## Schema changes

### 1. New fields on `Env_AnalyticalResults` / `AnalyticalResultRecord`

All optional, all default to a value that preserves today's dedup behavior for
existing rows (`""` for text/code fields used in the key — **never `None`**;
see "Discriminator defaults" below for why).

| Field | Type | Purpose | Real-data producer |
|---|---|---|---|
| `CASNumber` | TEXT | CAS registry number | Step 3 (EQuIS dialects ship it natively as `cas_rn`) |
| `ResultFraction` | TEXT | Total / Dissolved / Total Recoverable / etc. | **Step 2 (WQX `ResultSampleFractionText`)** — the field that must exist before step 2's first real import |
| `QCType` | TEXT | Field-level QC discriminator (e.g. field duplicate vs. parent) — **not** lab-internal QC, which goes to the companion table | Step 3 (WQX's QC activities get their own `ActivityIdentifier`, so this rarely fires on WQX data — see field/QC-type distinction below) |
| `MethodDilutionKey` | TEXT | Distinguishes same-method reruns at different dilution, or genuinely different methods for the same analyte | Step 3 (dilution reruns are an EQuIS/lab-EDD phenomenon, not present in WQX) |
| `MethodID` | TEXT | Analytical method identifier | **Step 2 (WQX `ResultAnalyticalMethod/MethodIdentifier`)** |
| `MethodName` | TEXT | Analytical method name | **Step 2 (WQX `MethodName`)** |
| `AnalysisDate` | DATE | When the analysis was run | **Step 2 (WQX `AnalysisStartDate`)** |
| `LimitType` | TEXT | Which limit `ReportingLimit`/`DetectionLimit` represents (MDL vs. RL vs. other) | **Step 2 (WQX `DetectionQuantitationLimitTypeName`)** — partial; full MDL/RL distinction is a step-3/EQuIS richness |

### 2. New companion table: `Env_QCResults` / `QCResultRecord`

Lab-internal QC results (method blank, LCS, LCSD, matrix spike, matrix spike
duplicate, surrogate recovery) — first real producer is step 3 (WMRD's
`Batch_v1`, EPA-R4's `_TST_v1`, NYSDEC/Montana QC sheets all carry this
natively; WQX has no batch/QC-linkage concept at all, so step 2 populates
nothing here).

Representative fields (subject to the required paper-mapping pass before
implementation — see "Required pre-implementation step" below):

- `ImportBatchID`, `SiteID`, `Matrix`, `PrepBatchID`, `AnalysisBatchID`
- `QCType` (method blank / LCS / LCSD / MS / MSD / surrogate)
- `ParentSampleID` (the field sample this QC run is associated with, where
  applicable — nullable, since e.g. a method blank may not have one)
- `AnalyteCanonicalName`, `ResultNumeric`, `Units`
- `SpikeAmount`, `PercentRecovery`, `RecoveryLowerLimit`, `RecoveryUpperLimit`
- `SourceWorkbook`, `SourceSheet`, `SourceRow` (same provenance convention as
  the other tables)

`UNIQUE_KEYS["Env_QCResults"]` — proposed `SiteID, Matrix, AnalysisBatchID,
AnalyteCanonicalName, QCType` (exact composition finalized during the paper
mapping — this table has no legacy rows to stay backward-compatible with, so
its key has more freedom than `Env_AnalyticalResults`'s).

### 3. `UNIQUE_KEYS["Env_AnalyticalResults"]` redesign

```python
# Before (gdb_schema.py:337-339):
"Env_AnalyticalResults": ["SiteID", "Matrix", "LocationID", "SampleID",
                          "SampleDate", "AnalyteCanonicalName",
                          "DepthIntervalText", "SourceCell"],

# After:
"Env_AnalyticalResults": ["SiteID", "Matrix", "LocationID", "SampleID",
                          "SampleDate", "AnalyteCanonicalName",
                          "DepthIntervalText", "SourceCell",
                          "ResultFraction", "QCType", "MethodDilutionKey"],
```

**All three discriminators are added now**, even though step 2 (WQX) only
populates `ResultFraction` with real data. Verified: `QCType` and
`MethodDilutionKey` collisions are lab-EDD/EQuIS phenomena (merged
result+QC sheets in WMRD/NYSDEC/EPA-R4; dilution reruns), not WQX ones — but
since this key can never be widened again without a second irreversible schema
change, and step 3 is the only planned consumer that will ever exercise them,
they must be frozen here, not deferred to a "step 3.5 key bump."

**Discriminator defaults must be `""`, never `None`.** `_norm_key_part`
(`import_to_gdb.py:114-121`) maps `""` → `""` but passes `None` through
unchanged, and `d.get(k)` on a dict missing the key yields `None` — so a
`None` default risks `None`-vs-`""` key mismatches across re-imports of the
same data, breaking idempotency. `SourceCell`'s existing `""` convention is the
pattern to match.

**Discriminator values must be deterministic from source data.** A
non-deterministic default (e.g. import timestamp) would make the same source
file produce a different key on every re-import, breaking the whole point of
`append_records_idempotent`.

### 4. `compute_unique_key()` extraction (required, not optional)

`import_to_gdb.py:152` currently computes the dedup key inline:
`tuple(_norm_key_part(d.get(k)) for k in key_fields)`. Extract this into a pure
function in `gdb_schema.py` (which already owns `UNIQUE_KEYS`, and is
arcpy-free):

```python
def compute_unique_key(record_dict: dict, table_name: str) -> tuple:
    """The exact key append_records_idempotent dedups on. Pure, arcpy-free —
    the load-bearing seam the synthetic key-distinctness tests exercise."""
```

This is required because `append_records_idempotent` is arcpy-gated
(`import_to_gdb.py:137`) — the current test suite only reaches it through
monkeypatched fakes (`tests/test_edd_importer.py:265-308`). Without extracting
the real key computation into a pure helper, any new test asserting key
distinctness would validate a hand-copied/drifting reimplementation instead of
the actual dedup logic.

### 5. `value_maps` — generalize `matrix_map`

`Matrix` is already a `UNIQUE_KEYS` field that gets **value-normalized before
entering the key** via `matrix_map` (`edd_importer.py:133`). The new
code-valued discriminators (`QCType`, `ResultFraction`) inherit exactly the
same need: dedup is cross-batch against existing GDB rows
(`import_to_gdb.py:144-145`), and `_norm_key_part` does no code translation —
so two batches spelling the same logical QC type differently ("TB" vs. "TRIP
BLANK") would produce two different keys and both insert as if distinct.

Generalize `LabEDDProfile.matrix_map: dict[str, str]` into
`value_maps: dict[str, dict[str, str]]` (field name → code → canonical value),
defaulting to `{}`. Keep `matrix_map` itself as-is (or make it a thin alias)
for backward compatibility with the existing TestAmerica profile — this is a
small, additive change to `LabEDDProfile`, not a rewrite.

### 6. Fix: `run_edd_import` never ensures the schema

Verified gap: `run_edd_import` (`edd_importer.py:299-346`, invoked via the
`import-edd` CLI at `cli.py:1658-1689`) never calls
`create_or_update_gdb_schema` — only the workbook-import path (`run_import`,
`import_to_gdb.py:279`) does. Once this spec's new key columns exist in
`TABLE_SCHEMAS` but a real site's GDB hasn't been upgraded yet,
`_existing_key_set`'s `SearchCursor` on the new (nonexistent) columns will make
**every EDD import crash** against an un-upgraded GDB.

Fix: add a `create_or_update_gdb_schema` call at the top of `run_edd_import`,
mirroring what `run_import` already does. This is the self-healing behavior the
workbook path already has — the EDD path should match it, independent of
whether this spec's specific fields are the trigger.

### 7. VI-field grain placement

Vapor-intrusion building-survey attributes (building type, heating fuel type,
foundation type, etc. — seen in NYSDEC's `VI_*` sheets and WMRD) describe the
**sampling event / building being surveyed**, not an individual analytical
result. **Decision: these are `Env_Samples`-grain fields** (new optional
columns on `SampleRecord`/`Env_Samples`), not a new table and not
result-grain columns — a VI building survey applies once per sampling
event/location visit, matching how `Env_Samples` already represents "one row
per physical sample." Exact field list deferred to the required paper-mapping
pass (VI fields are entirely a step-3/NYSDEC-WMRD concern; step 2/WQX populates
none of them) — but the **grain** (which table they live on) is fixed now,
since table placement is exactly as unrenameable/unmovable as a field name
under the additive-only migration model.

### 8. Frozen boundary: the reader seam (ADR content, not code)

The step-1 ADR must explicitly document (not just implicitly rely on) two
architectural facts already true today, so step 3 doesn't try to change either:

- **The flat-row-dict list returned by `read_edd_file` is the permanent reader
  contract.** `normalize_edd_rows` (`edd_importer.py:75`) is already fully
  format-agnostic — it never touches the source file, only
  `profile.resolve_column(row, field)` over flat dicts. Any N-table relational
  flatten (WQX's 2-level hierarchy in step 2; Mining/WMRD/NYSDEC's 3-38 sheet
  relational exports in step 3) collapses to this same contract **inside a
  per-dialect reader module** — the pattern `_read_two_tab_xlsx`
  (`edd_importer.py:42-68`) already establishes via parent→child
  denormalization. Join topology lives in reader code; column→canonical
  mapping stays in YAML. `normalize_edd_rows` itself never needs to change
  again for a new format.
- **`LabEDDProfile` stays flat and 2-sheet-shaped permanently.** Verified: its
  `columns: dict[str, str | list[str]]` is canonical-field-keyed and
  `resolve_column` hard-codes str/list handling
  (`edd_profile.py:50-62`) — it structurally cannot express EQuIS's
  many-to-many "Database Mapping(s)", per-field types/required flags, or a
  relational graph of >2 tables. Step 3's richer draft-time model
  (`DialectSpec` or similar) is a **separate type that projects down** to a
  flat `LabEDDProfile` at runtime; it never persists relational/typed structure
  into the profile itself. This repo already has the precedent for a richer
  profile shape when one is genuinely needed —
  `ParserProfile`/`SheetProfile` (`core/common/config.py:127-216`) — so step 3
  reusing that pattern (not retrofitting `LabEDDProfile`) is consistent with
  existing conventions, not a new one.

---

## Read-side impact: the canonical-read policy (required deliverable)

Widening `Env_AnalyticalResults`'s uniqueness grain from "≤1 row per `(sample,
analyte, depth)`" to "≤1 row per `(sample, analyte, depth, fraction, QC-type,
method/dilution)`" means **every consumer that currently pivots/groups results
by analyte alone will double-count or silently drop data the moment step 2
populates a real `ResultFraction` value** (e.g. a WQX Total/Dissolved pair).

Verified concretely broken in `build_current_event.py`:
- `:109-111` — max-detect pooling filters by `AnalyteCanonicalName` only,
  would pool Total+Dissolved and pick a max across fractions.
- `:162-163` — duplicate/RPD reconciliation groups by
  `(LocationID, parent, AnalyteCanonicalName, DepthIntervalText)`, no
  fraction/QC-type — would reconcile Total against Dissolved as if they were
  duplicate measurements of the same thing.
- `:258` — the wide-table pivot itself,
  `{r["AnalyteCanonicalName"]: r for r in rows}`, silently overwrites on a
  second row per analyte (it already detects and QA-warns on this at
  `:259-265`, but every Total/Dissolved pair would now trip that warning or
  silently drop a fraction).

**Required for this spec:** a shared **canonical-read helper** — default
behavior: exclude `QCType`-flagged rows, resolve to a single canonical
fraction — with `build_current_event.py` converted to use it as the reference
implementation, since it's the confirmed-broken case and the wide-table pivot
most directly used for regulatory reporting.

**Named as a step-2 merge gate, not fixed in this spec:** the ~10 other
analyte-pivoting consumers that read `Env_AnalyticalResults` —
`dashboard_data_mart.py`, `export_summary.py`, `export_summary_tables.py`,
`generate_event_report.py`, `compare_events.py`, `history_report.py`,
`schedule_vs_actual.py`, `data_gaps.py`, `apply_screening.py`,
`export_geojson.py`, `draft_plume_boundary.py`. Nothing breaks in the interim —
discriminators stay `""` until step 2 actually imports WQX data — but step 2's
spec/plan must include auditing and converting each of these to the canonical-read
helper **before** step 2 ships a real WQX import, or the first Total/Dissolved
pair in production data silently corrupts a regulatory summary or dashboard.

---

## Testing plan (all arcpy-free)

Step 2's real WQX data will only exercise `ResultFraction` and the partial
method-detail fields — everything else this spec adds (`CASNumber`, `QCType`,
`MethodDilutionKey`, the `Env_QCResults` table, spike/surrogate recovery, VI
fields) has **no real producer until step 3** and, being additive-only, can
never be renamed if step 1 gets a name wrong. This spec cannot rely on step 2
to validate itself — it ships its own synthetic test suite:

1. **Key distinctness.** Using `compute_unique_key()` directly (not through the
   arcpy-gated `append_records_idempotent`), assert distinct key tuples for:
   a field result vs. a `QCType`-flagged row sharing the same
   `SampleID`/analyte/date; a `ResultFraction`="Total" vs. "Dissolved" pair;
   a same-method-different-`MethodDilutionKey` pair.
2. **Backward compatibility.** Records in today's shape (all three new
   discriminators defaulted `""`) must produce keys with unchanged *relative*
   uniqueness — run the existing TestAmerica EDD and workbook-import fixtures
   through the widened key and assert dedup behavior is identical to today.
3. **Field-projection round-trip.** Construct a record populating every new
   field (`CASNumber`, method detail, etc.) and assert each survives
   record → `TABLE_SCHEMAS`-driven row projection (a dataclass-attribute name
   that doesn't exactly match its `TABLE_SCHEMAS` entry silently projects to
   `None` — this is a real, previously-latent failure mode being tested for the
   first time here). Same round-trip for `Env_QCResults` against its own
   `UNIQUE_KEYS` entry.
4. **`run_edd_import` schema-ensure fix.** A test confirming the schema-ensure
   call now happens on the EDD path (mirroring existing coverage of the
   workbook path).
5. **`build_current_event.py` canonical-read conversion**, tested against a
   synthetic Total/Dissolved pair to confirm the pivot no longer silently drops
   or double-counts.
6. **Delete `record_to_row`** (`gdb_schema.py:404-406`) — confirmed dead code,
   zero callers anywhere in the codebase or tests. No reason to carry a
   hardcoded-field-list footgun through a schema expansion when nothing uses
   it.

---

## Required pre-implementation step: the paper mapping

Because the additive-only migration model means every field/table name and key
composition frozen here is permanent, **before this spec's field names are
implemented**, produce a column-by-column mapping of every cataloged real
format — Montana Mining EDD, Montana WMRD/EQuIS, NYSDEC v5 EDD, EPA Region 4
EDD, EPA WQX, and the proprietary SXSAMP PFAS export — onto the fields
proposed above. This spec's field list (the tables in "Schema changes" above)
is a first-pass proposal grounded in the cataloging pass already done this
session, not yet an exhaustive column-by-column verification against every
format's full field dictionary (e.g. Mining's 49-column `LabResult` sheet,
NYSDEC's 65-column `TestResultQC_v5`). The paper mapping is what step 3's
deterministic parser will also consume (it parses the same description +
valid-values files) — doing it once, before freezing names, keeps step 1 and
step 3 aligned instead of discovering a mismatch after the fact.

This mapping pass, and writing the ADR that records its outcome (the field
list, the `Env_QCResults` shape, the three frozen boundaries in "Frozen
boundary: the reader seam" above, the VI grain decision, and the
`SCHEMA_VERSION` 2.1→2.2 bump), are the first tasks of the implementation plan
for this spec — not yet done here.

---

## Handoff contracts (for whoever writes steps 2 and 3's specs)

**Step 1 → Step 2:** step 1 must ship first, not reorderable or meaningfully
parallelizable — WQX's real data hits the `ResultFraction` collision on its
very first import, and the read-policy fix must exist before step 2 populates
real fraction data (else it silently corrupts consumers immediately). The only
safe concurrency: step 2's `wqx_reader.py` module and its `LabEDDProfile` YAML
can be *authored* against this spec's design while it's in review, but must not
merge or run real imports until step 1 lands. Step 2 needs, at minimum:
`ResultFraction` in the schema/dataclass/key, the method-detail fields, `""`
discriminator defaults, `compute_unique_key()`, the canonical-read helper, and
the `run_edd_import` schema-ensure fix.

**Step 2 → Step 3:** confirmed safe, no rework expected. The reader/normalizer
seam already generalizes to step 3's relational dialects via a per-dialect
reader module (same pattern step 2 establishes for WQX) — no structural change
to `LabEDDProfile` needed in step 2 to make step 3 possible. Step 3's own
richer draft-time profile model is genuinely a separate concern (see "Frozen
boundary" above), not an extension of what step 2 builds.
