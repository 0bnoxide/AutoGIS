# ADR-015: Absorbed-in-place vendoring for Dan Patterson numpy_geometry

**Status:** Accepted

**Date:** 2026-06-25

## Context

Five pure-numpy geometry algorithms from Dan Patterson's `numpy_geometry` repo are needed for Phase 2-4 tools: coordinate rotation, convex hull, nearest-neighbor, polyline simplification, and point densification. Dan Patterson confirmed free-use license via direct contact (2026-06-25).

The source repo mixes arcpy-dependent I/O wrappers with pure-numpy computation cores in the same files. Any vendoring strategy must isolate the numpy cores from the arcpy dependencies.

## Decision

Absorb the three relevant source files into `autogis/core/common/npg/` (npg_maths.py, npg_geom_ops.py, npg_analysis.py) modified in-place:

- arcpy imports and arcpy-dependent functions stripped at absorption time
- Dan Patterson attribution header prepended to each file
- No submodule, no pip package, no separate repo — the files live directly in the AutoGIS tree

Expose a clean public API via `autogis/core/common/numpy_geom.py`:

- Five functions: `rotate_points`, `convex_hull`, `nearest_neighbors`, `simplify_polyline`, `densify_polyline`
- Each wraps the corresponding `npg/` function in a `try/except (ImportError, AttributeError)` block
- If the `npg/` function is missing or incomplete, a pure-numpy fallback implementation activates silently
- All functions accept and return plain `np.ndarray` — no arcpy, no GIS objects

## Consequences

### Positive consequences

- No external runtime dependency to manage; numpy_geometry source is frozen in the tree
- arcpy-free interface at `numpy_geom.py` makes all five functions testable without a license
- Fallback implementations ensure tests pass even if a Dan Patterson function changes signature upstream
- Attribution is in-tree and auditable via `git log`
- The `try/except` wrapper pattern is self-documenting: readers can see exactly which upstream function backs each public function

### Negative consequences

- `npg/` files are a modified fork — any upstream improvements require manual cherry-pick
- The absorbed files retain Dan Patterson's internal style (may differ from AutoGIS conventions)
- Functions excluded from absorption (arcpy-dependent ones) are commented out but still present, which can confuse readers unfamiliar with the vendoring context
- `numpy>=1.24` is now a hard project dependency (added to `setup.cfg`)

## Alternatives considered

1. **Git submodule:** Pin the upstream repo at a commit.
   - **Rejected:** Still requires stripping arcpy at import time (conditional imports or monkeypatching); submodule adds friction to clone and CI; doesn't solve the mixed arcpy/numpy problem.

2. **PyPI packaging:** Wait for a pip-installable version.
   - **Rejected:** No pip package exists; author distributes via GitHub only.

3. **Copy only the five target functions:** Extract just the five functions into a single `_npg_kernels.py`.
   - **Rejected:** The functions have internal cross-dependencies (e.g., `npg_geom_ops` calls helpers from the same file); copying isolated functions risks breakage if helpers are missed. Absorbing full files is safer.

4. **Reimplement from scratch:** Write equivalent pure-numpy algorithms without any vendored code.
   - **Rejected:** Unnecessary duplication of well-tested implementations; Dan Patterson's code is the reference for correctness.

## Amendments

**2026-07-21:** The public API grew a sixth function, `concave_hull` (wraps
`npg_analysis.concave`, same `try/except` fallback pattern as the original
five — falls back to `convex_hull` if `npg_analysis` is unavailable). Used by
`draft_plume_boundary.py`. The "five functions" framing above is historical;
`autogis/core/common/numpy_geom.py` is the current source of truth for the
public surface.

## Related decisions

- [ADR-002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md) — npg/ and numpy_geom.py uphold this invariant
- [ADR-014: Schema dataclass package](0014-schema-dataclass-package.md)

## References

- License confirmation: `docs/DAN_PATTERSON_NUMPY_TOOLS_INTEGRATION.md`
- Source: https://github.com/Dan-Patterson/numpy_geometry
