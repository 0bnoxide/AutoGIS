# ADR-0035 — CAD/Civil 3D handoff batch (2026-07-02): BuildCADExportPackage,
ExportContoursForCivil3D

**Status:** Accepted
**Date:** 2026-07-02
**Deciders:** Greg / Claude (Fable plans+reviews, Sonnet implements)
**Related:** ADR-0002 (arcpy-free core), ADR-0006 (`.pyt` as primary UI,
now partially superseded — see below), issue #105 (CLI/.pyt seam
bifurcation), `docs/superpowers/specs/2026-06-28-build-cad-export-package-design.md`,
`docs/superpowers/specs/2026-06-28-export-contours-for-civil3d-design.md`

---

## Context

A prior graph-based repo-structure brief (2026-07-02) verified the README's
"not started" bucket against the specs directory: 6 of 8 listed tools already
had approved 2026-06-28 design docs that were never implemented. This batch
ships the two of those with a resolved, unblocked dependency chain:
**BuildCADExportPackage (8.9)** must land before **ExportContoursForCivil3D
(8.2)**, since the latter's approved spec explicitly reuses 8.9's
`cad_layer_map.py` for CRS/projection-note validation.

Both approved specs were written against the older Tools-2-8 convention:
CLI guards, then unconditionally redirects to a `.pyt` toolbox tool. While
implementing, a check of `autogis/adapters/toolbox.pyt`'s actual
`self.tools` registration (12 entries, last added `ReconcileSampleLocations`)
against the ~9 most-recently-shipped `Runtime.LOCAL` tools in
`capabilities.py` found **none of the 9 have a `.pyt` class** — this is
issue #105 (H2, priority: high), an independent architecture-review finding
already on `main`, unactioned. Issue #105's own recommendation is that
resolving CLI-vs-`.pyt` for LOCAL tools going forward needs its own ADR, not
a per-tool side effect.

## Decision

1. Ship both tools' pure/headless halves in full, TDD, with the specs'
   dataclasses and function signatures as designed:
   - `autogis/core/envmon/cad_layer_map.py` — `CADLayerMapping`,
     `CADExportPlan`, `resolve_cad_plan`, `load_cad_mapping`, `validate_crs`,
     `write_projection_note`.
   - `autogis/core/envmon/civil3d_points.py` — `PNEZDPoint`, `build_pnezd`,
     `load_gwe_points_csv`, `write_pnezd_csv`; re-exports `validate_crs`/
     `write_projection_note` from `cad_layer_map` rather than duplicating
     CRS handling (per the spec's stated reuse).
2. **Do not add `.pyt` toolbox classes for either tool.** Matches the last 9
   LOCAL tools' actual practice, not the older per-spec convention; also
   avoids shipping arcpy-dependent code that cannot be exercised or verified
   in this (arcpy-free) environment. Deferred to whatever direction issue
   #105's eventual ADR picks (CLI-first per generation-2 precedent, or a
   `.pyt` catch-up pass) — not decided piecemeal here.
3. **Do not reuse the older generation's misleading redirect wording**
   ("Use the X tool in the .pyt toolbox") for these two commands, since no
   such toolbox tool exists. Both `build-cad-package` and `export-civil3d
   --landxml` guard, then raise a `ClickException` naming the real
   constraint (arcpy required) and pointing at issue #105, rather than
   implying a working `.pyt` entry.
4. `build-cad-package`, `export-civil3d`: registered `Runtime.LOCAL` in
   `capabilities.py`. `export-civil3d`'s headless CSV/projection-note leg
   runs without a guard (same `if landxml: _guard(...)` conditional-guard
   shape as `update-well-elevations --gdb` / `draft-plume-boundary --gdb`).

### Pinned design decisions (specs left these open)

- Mapping YAML: `{gis_layer: {cad_layer: str, color: int, linetype: str}}`;
  no string-shorthand, no `default` key — an absent/malformed entry is
  `unmapped` and a single aggregated blocking `SEV_ERROR`
  (`unmapped_layers`), not a per-layer record and not a silent default
  (spec explicitly rejected default mappings).
- Layer-name matching is exact/case-sensitive.
- `resolve_cad_plan` owns and returns its own `QACollector` (`plan.qa`), per
  the approved spec signature.
- `build_pnezd` gains a required keyword-only `qa: QACollector` param (the
  spec's public API omitted it, but its own test 5 requires a WARNING on
  missing elevation — matches the `export_survey_to_cad_gis` convention of
  threading `qa` through every core mutator).
- Point-record keys: `location_id, x, y, z[, description]`; `x`=easting,
  `y`=northing (same convention as `export_survey_cad.py` /
  `export_geojson.load_well_coords`).
- Output filenames: `points_pnezd.csv`, `projection_note.txt`; the PNEZD CSV
  has a header row.
- No new dependencies (no `ezdxf`; spec-rejected).

## Consequences

### Positive

- Two more roadmap tools shippable without arcpy for their headless half;
  their pure mapping/CRS/PNEZD logic is fully unit-tested (17 new tests, 9
  + 8) without needing Pro.
- `cad_layer_map.py`'s CRS/projection-note functions are now a shared seam
  for any future CAD/surface-export tool, avoiding duplicated validation.
- Honest guard messaging: a user hitting `build-cad-package` or
  `export-civil3d --landxml` is told the real constraint (needs arcpy, no
  `.pyt` entry yet, see #105) instead of being pointed at a toolbox tool
  that silently doesn't exist — the same failure mode issue #105 already
  flags for two other tools (`optimize-callouts`,
  `manage-callout-overrides`).

### Negative

- Neither tool's arcpy leg (Export-to-CAD, contour polylines/LandXML) is
  implemented or reachable from any interface yet — CLI refuses, no `.pyt`
  entry exists. Both are pure-logic-plus-guard shells until issue #105 is
  resolved and a follow-up implements the arcpy call in whichever seam that
  ADR picks.
- This is the **11th and 12th** instance of the CLI/`.pyt` bifurcation
  issue #105 tracks (9 existing generation-2 tools + these 2 generation-1
  stubs-with-honest-messaging). Not fixed here by design — see Decision §2.

## Alternatives considered

- **Add `.pyt` classes for these two tools** (per the specs' literal
  Architecture section): rejected — untestable in this environment, and
  would add a 13th/14th-tool inconsistency (matching an 8-tool-old
  convention while the 9 most recent tools all skip `.pyt`) rather than
  resolving the actual seam question issue #105 raises.
- **Implement the arcpy calls directly in the CLI** (generation-2 pattern,
  which issue #105 tentatively recommends as the future default):
  rejected for *this* batch — the approved specs explicitly named the
  `.pyt`/Tools-2-8 pattern, issue #105 itself says the CLI-vs-`.pyt`
  question needs its own ADR before being applied case-by-case, and
  converting 2-of-11 tools while the other 9 remain generation-2 doesn't
  resolve the inconsistency, it just adds a third permutation.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0006: `.pyt` toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
- Issue #105: CLI/.pyt seam bifurcation (`docs/reviews/fable-architecture-review.md`)
- `docs/superpowers/specs/2026-06-28-build-cad-export-package-design.md`
- `docs/superpowers/specs/2026-06-28-export-contours-for-civil3d-design.md`
