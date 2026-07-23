# ADR-0101: CompareDroneSurfaces — optional diff-raster output

**Status:** Accepted — user request (this session)

**Date:** 2026-07-22

> Numbering note: PRs #279 (init-site) and #280 (phase4 notebook) were open
> concurrently carrying ADR filenames `0100`/`0099` that already collide with
> merged records, so all three branches renumber against current `main`. This
> ADR takes `0101` (next free vs `main`); a `docs/adr/README.md` index conflict
> at merge is expected and resolved keep-both in numeric order (same as the
> #277/#278 flow).

## Context

`CompareDroneSurfaces` (tool 8.7, LOCAL/arcpy) diffs a primary drone DEM against
a baseline (a second `DroneProductRegistry` DEM, or a LandXML design surface),
classifies every cell against a limit-of-detection threshold, and reports a
one-line `DiffSummary` (changed-cell count, max, mean). In the two-DEM branch it
already computes the full `sa.Minus(primary, baseline)` difference raster — then
**discards it** after converting to numpy for the summary.

Running it live, the user asked for the result to be *mappable* — "this would be
more useful if it output [the diff] not just a tool-tip" — so an analyst can see
*where* the surface changed, not only how much. The difference grid is the exact
artifact that answers that, and it is already being produced and thrown away.

## Decision

Add an optional `diff_raster_out` output to persist the difference raster.

- **Core** (`compare_drone_surfaces.py`): `compare_surfaces(..., diff_raster_out="")`.
  When set, `diff_raster.save(diff_raster_out)` runs **inside** the existing
  `EnvManager(snapRaster=…, extent="MINOF", cellSize=…)` block (extended with
  `overwriteOutput=True`) so the persisted grid is the MINOF-aligned result, not
  whatever the ambient env is at save time (`sa` rasters can evaluate lazily).
  `overwriteOutput` lets a rerun regenerate the derived product — standard GP
  behaviour for a computed output, unlike the refuse-to-clobber stance for
  hand-authored inputs (ADR-0100).
- **Two-layer overwrite safety** (`validate_output_not_input`, codex #281 P1):
  because the save runs under `overwriteOutput=True`, a `diff_raster_out`
  resolving to the primary or baseline `ProductPath` would silently clobber a
  registered source DEM while the registry still points at it. The `.pyt`
  `updateMessages` hook resolves both registered paths and marks a collision as
  an error *before execution*, because ArcGIS can delete a managed Output before
  `execute()` runs. A bare output name is first qualified against
  `arcpy.env.workspace`, matching ArcGIS's documented base-name resolution, so
  the relative-name collision cannot bypass the comparison. The pure
  normcase/normpath check remains at the core save chokepoint as defense in depth
  for direct callers.
- **LandXML baseline is out of scope.** That branch builds a *filtered flat list*
  of per-cell diffs (skipping NoData / out-of-surface cells) with no aligned grid
  to save. Rather than reconstruct one via `NumPyArrayToRaster` (speculative,
  more arcpy surface, needs its own georeferencing verification), a pure guard
  `validate_diff_output(diff_raster_out, baseline_landxml)` **rejects** the
  combination with a clear message. Fail loud beats silently dropping the output.
- **CLI / `.pyt`**: `--diff-raster-out PATH` on `envmon compare-drone-surfaces`
  (validation/signature parity — the command still guards+redirects, ADR-0062),
  and a `DERasterDataset` **Output** parameter appended **last** in the toolbox
  tool (never ahead of existing positional slots — PR #258 review P1). `execute`
  validates, threads it through, and echoes the saved path.

## Consequences

- The two-DEM comparison now yields a mappable difference raster on demand; the
  summary tooltip is unchanged when the output is omitted (opt-in, zero cost).
- LandXML + diff-raster is a documented, tested `ValueError`, not a silent no-op.
  A `NumPyArrayToRaster` LandXML path is the marked upgrade if ever needed.
- Python-toolbox validation fails closed before execution if it cannot prove the
  diff output is distinct from both registered DEM inputs.
- New arcpy surface is `Raster.save({name})`, the `overwriteOutput` env keyword
  on `EnvManager`, and the `DERasterDataset` param type — all doc-verified
  against pro.arcgis.com 3.5 references per ADR-0077 (cited in the PR). The save
  lands in the `# pragma: no cover` seam; the pure `validate_diff_output` guard
  carries the regression tests, and live ArcGIS Pro QA against the user's
  `AUTO_GIS_TESTING.gdb` closes the untestable leg.

## Alternatives considered

- **Also emit a diff raster in the LandXML branch** (`NumPyArrayToRaster` from a
  reconstructed full-shape array): rejected for now — speculative, more arcpy to
  verify, and the approved ask was the two-DEM case. Guarded, not silently
  half-supported.
- **A tabular per-cell CSV/GDB table output** ("A"): the user chose the diff
  raster ("we'll leave it at that") — a raster maps directly; a per-cell table is
  redundant with the raster and the summary.
- **Save unconditionally / to a fixed name:** rejected — opt-in keeps the fast
  summary-only path and lets the user place the output in their own gdb.

## Related decisions

- ADR-0061 — drone/geotech graphics tool batch (CompareDroneSurfaces origin)
- ADR-0062 — LOCAL CLI commands guard + redirect to the `.pyt`
- ADR-0077 — arcpy API-currency doc-verify (Raster.save, EnvManager env, DERasterDataset)
- ADR-0100 — sibling drone tool; overwrite stance contrast (input vs derived output)
