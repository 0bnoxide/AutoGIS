# ADR-019: ReconcileSampleLocations — stdlib difflib, two-path headless/GDB design

**Status:** Accepted

**Date:** 2026-06-26

## Context

The single most common import failure is a workbook location ID that does not match
the monitoring-well feature class — e.g. `MW-1` in the workbook vs `MW-01` in the GDB,
or `HSS-11` vs `HSS11`. This causes silent join failures downstream: callouts don't
attach, exceedance records are orphaned, and map layers render empty. The problem is
pure text comparison, but it must be runnable both headlessly (for CI, cloud) and
against the live GDB (for production).

Three structural questions needed resolution:

1. **Matching algorithm:** full fuzzy library (rapidfuzz, fuzzywuzzy) vs stdlib `difflib`.
2. **ID normalization contract:** what characters to collapse before comparing.
3. **Two execution paths:** headless `--wells-csv` vs arcpy `--gdb` — shared core or
   duplicated logic.

## Decision

### Matching algorithm: stdlib `difflib.SequenceMatcher`

`difflib.SequenceMatcher(None, norm_a, norm_b).ratio()` is the comparison primitive.
No new dependency. Default threshold `0.8`; configurable via `--threshold`. This is
sufficient for the separator-variation and zero-pad problems that actually occur (`MW-1`
↔ `MW-01`, `HSS-11` ↔ `HSS11`).

### ID normalization contract

`normalize_id(value)`: uppercase + strip whitespace + remove all `-`, `_`, and space
characters. Applied to both sides before exact-match and before fuzzy comparison.
This ensures `MW-1`, `MW_1`, `mw 1` all collapse to `MW1` and match without fuzzy
overhead.

### Severity schema

| Situation | Severity | Category |
|-----------|----------|----------|
| Workbook ID → well match ≥ threshold | `WARNING` | `location_id_typo` |
| Workbook ID → no well match above threshold | `ERROR` | `location_id_unmatched` |
| Well ID absent from workbook | `INFO` | `well_not_sampled` |

Unsampled wells are `INFO` not `WARNING` because dry events and incomplete sampling
rounds are legitimate; missing workbook IDs are the actionable signal.

### Two-path design: shared core, split at well-ID source only

`reconcile_locations.py` (headless, arcpy-free) exposes the full algorithm:

- `normalize_id(value) -> str`
- `reconcile(workbook_ids, well_ids, threshold) -> ReconcileResult`
- `reconcile_to_qa(result) -> QACollector`
- `extract_location_ids(reader, profile) -> list[str]`
- `read_well_ids_csv(path) -> list[str]`

The CLI `reconcile-locations` command takes `--wells-csv` (headless) or `--gdb`
(redirects to the `.pyt` with a clean error). The `.pyt` `ReconcileSampleLocations`
tool reads well IDs via `arcpy.da.SearchCursor` and calls the same `reconcile()` /
`reconcile_to_qa()` core. No algorithm duplication.

`reconcile-locations` is registered as `Runtime.HYBRID` in `capabilities.py` (runs
headlessly via CLI; runs with arcpy via `.pyt`). This is a new runtime category for
the pre-flight tools — distinct from CLOUD (always headless) and LOCAL (arcpy required).

### CSV well-ID reader contract

`read_well_ids_csv(path)`: if the header row contains a `LocationID` column
(case-insensitive), read that column; otherwise treat the first column as data (no
header). Skips blank rows. This handles both a minimal bare-ID export and a full
site-table export.

## Consequences

### Positive consequences

- No new runtime dependency — `difflib` is stdlib
- Headless path is fully unit-testable (9 tests added, all arcpy-free)
- `.pyt` structural integrity verified via AST parse at commit time, not by running arcpy
- `reconcile()` accepts plain lists: trivially mockable in tests and reusable by
  future batch tooling
- `Runtime.HYBRID` registration generalises cleanly to future pre-flight tools
  (`ValidateUnits`, `ManageScreeningLevels`) that share the same pattern

### Negative consequences

- `difflib.SequenceMatcher` is O(n²) in the number of well IDs — fine for < 200 wells
  per typical site; would need batching if ever applied to a project with thousands of
  IDs across many sites
- Threshold `0.8` is a heuristic; a very abbreviated ID (`MW1`) compared to a long one
  (`MW-001A`) may score below threshold even when they intend the same location — user
  must lower `--threshold` manually
- The `--gdb` redirect path always produces a non-zero exit code even when arcpy is
  present, because `run inside ArcGIS Pro` is the design intent; headless arcpy users
  must use `--wells-csv` instead

## Alternatives considered

1. **rapidfuzz / fuzzywuzzy:** Better edit-distance algorithms (Levenshtein vs ratio).
   - **Rejected:** New dependency not justified for the separator-variation problem.
     `difflib.ratio()` produces correct suggestions for all observed real-world cases
     (`MW-7A` ↔ `MW-07A`). Can be revisited if false-negative reports accumulate.

2. **Exact-only matching (no fuzzy):** Normalize then compare; report unmatched with no
   suggestions.
   - **Rejected:** The whole value of this tool is the suggestion — "did you mean
     MW-07A?" turns a confusing import failure into a one-click fix. Exact-only would
     not surface that.

3. **Integrate fuzzy match into `normalize_groundwater` / table normalizers directly:**
   Apply suggestions at parse time during import.
   - **Rejected:** Import is a write path; fuzzy suggestions are inherently ambiguous
     and must be human-confirmed before a record is written. Keeping reconcile as a
     standalone read-only pre-flight tool preserves that review step.

## Related decisions

- [ADR-001: Core-plus-adapters architecture](0001-core-adapters-separation.md) — `reconcile_locations.py` is core; CLI and `.pyt` are adapters
- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — algorithm never imports arcpy
- [ADR-006: .pyt toolbox as primary UI for LOCAL tools](0006-pyt-toolbox-as-primary-ui.md) — extended here to HYBRID tools
- [ADR-005: Thread-safe QA substrate](0005-thread-safe-qa-substrate.md) — `reconcile_to_qa` returns a `QACollector`
