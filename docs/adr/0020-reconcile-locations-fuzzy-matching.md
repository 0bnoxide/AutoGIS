# ADR-0020 — ReconcileSampleLocations: stdlib difflib for fuzzy ID matching

**Status:** Accepted  
**Date:** 2026-06-26  
**Deciders:** Greg / Claude Code  
**Related:** ADR-002 (arcpy-free core), ADR-008 (openpyxl base dep)

---

## Context

`ReconcileSampleLocations` must detect likely typos between workbook location IDs
(e.g. `MW-7A`) and the monitoring-well feature class (e.g. `MW-07A`). The match
must work offline (no internet, no ArcGIS), in the headless `--wells-csv` path as
well as the `.pyt` GDB path.

Several third-party fuzzy libraries exist (`thefuzz`/`rapidfuzz`, `fuzzywuzzy`).

---

## Decision

Use `difflib.SequenceMatcher` from the Python standard library.  No new package
dependency is added.

Normalization before comparison: uppercase, strip, then remove all `-`, `_`, and
space characters (`normalize_id`).  This collapses `MW-07A`, `MW_07A`, and
`mw 07a` to the same normal form `MW07A`.

Threshold default: `0.8` (80% SequenceMatcher ratio).  Below that, no suggestion
is emitted (ERROR); at or above, a WARNING with the suggestion is emitted.

---

## Rationale

| Option | Pros | Cons |
|---|---|---|
| `difflib.SequenceMatcher` | stdlib; no dep; sufficient for short alphanumeric IDs | Slightly slower than C-backed libs for large lists |
| `rapidfuzz` | Fast; Levenshtein/token-sort | New dependency; overkill for <200 well IDs; not in arcgispro-py3 by default |

Our well-ID lists are short (< 200 entries). The performance difference is
negligible. Adding a dependency that isn't in the default arcgispro-py3 env creates
an install-step friction cost that outweighs the speed gain.

`normalize_id` handles the most common real-world patterns (leading zeros, separator
style) before SequenceMatcher runs, so the score is applied to already-normalized
forms — this makes the 0.8 threshold more reliable than on raw strings.

---

## Consequences

- No new package in `pyproject.toml` / `requirements*.txt`.
- `reconcile_locations.py` is a pure stdlib + `autogis.core.common` module, fully
  testable headless.
- If very large feature classes (>5,000 wells) ever appear, the `O(n²)` matching
  loop becomes the bottleneck; switching to `rapidfuzz` later would be a drop-in
  replacement for `SequenceMatcher.ratio()`.
