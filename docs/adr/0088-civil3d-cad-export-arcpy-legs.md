# ADR-0088: Close issue #166's LandXML-sharing ask and 8.9's Export-to-CAD leg; scope the remainder

**Status:** Accepted

**Date:** 2026-07-15

## Context

Issue #166 tracked two unbuilt arcpy legs flagged in a 2026-07-05 gap-analysis
survey (originally raised in #105):

- `ExportContoursForCivil3D` (8.2): the `--landxml`/contour-polyline leg was
  `.pyt`-only and never written; the CLI's `--landxml` flag just raised a
  guard error.
- `BuildCADExportPackage` (8.9): the arcpy Export-to-CAD call itself was
  never wired; the `.pyt` toolbox had no tool class for it at all.

The issue also asked that these two legs and `export_survey_cad.py`'s
LandXML writer (ADR-0071, issue #164) share one LandXML-serialization
implementation rather than three separate ones.

By the time this was picked up, `write_layer_landxml()` in
`export_survey_cad.py` was already a working, stdlib-only (`xml.etree`)
point-only `<CgPoints>` writer — i.e. the "arcpy required" premise behind
8.2's original design rejection ("LandXML/TIN authoring is niche; gate it
behind the arcpy/Civil path") no longer held for the *points* portion:
`civil3d_points.py`'s whole PNEZD point set can be serialized to LandXML
with zero arcpy.

## Decision

**1. Shared writer.** Promoted the CgPoints writer into
`autogis/core/common/landxml.py` (already home to the read-side TIN parser)
as `write_cgpoints(points: Iterable[CgPoint], output_path)`. Both
`export_survey_cad.write_layer_landxml()` and the new
`civil3d_points.write_pnezd_landxml()` are thin adapters over it. One
writer, two call sites, as the issue asked.

**2. `export-civil3d --landxml` is now headless.** It writes
`points_pnezd.xml` (LandXML CgPoints) alongside the existing CSV + note —
no arcpy guard, no `.pyt` redirect. Reclassified `export-civil3d` from
`Runtime.LOCAL` to `Runtime.CLOUD` in `runtime/capabilities.py` and dropped
it from the GUI's `UNREACHABLE` redirect-only accounting accordingly (it was
already excluded there, now for the right reason — see
`adapters/gui/reachability.py`'s updated comment).

**3. `BuildCADExportPackage` (8.9) is now wired.** Added the `.pyt` tool
class: it validates the GIS→CAD layer plan with the existing (already
arcpy-free, already tested) `resolve_cad_plan()`, blocks on any QA ERROR
(unmapped layer, missing CRS) before touching arcpy, writes the projection
note plus a new `write_mapping_report()` CSV (`cad_layer_map.py`, arcpy-free,
tested), then calls `arcpy.conversion.ExportCAD(in_features, Output_Type,
Output_File)` — signature doc-verified against
`doc.esri.com/en/arcgis-pro/latest/tool-reference/conversion/export-to-cad.html`
(2026-07-15): stable, no deprecation notice, `DWG_R2018` default with the
full `DWG_*`/`DXF_*`/`DGN_V8` `Output_Type` enum. Per ADR-0006/ADR-0077, the
CLI's `build-cad-package` command keeps its guard-then-redirect shape (it
never executed tools 2-8 directly); only the redirect message changed, from
"no `.pyt` entry yet" to "use the `.pyt` toolbox."

**4. Deliberately NOT wired: CAD layer rename.** `ExportCAD` names CAD
layers after the source feature class by default; renaming them to the
mapping config's `cad_layer` values needs `arcpy.conversion.AddCADFields`
plus a field calculate first. Esri's own tool-reference page for
`AddCADFields` documents the tool's five boolean toggles
(`Entities`/`LayerProps`/`TextProps`/`DocProps`/`XDataProps`) but does not
enumerate the actual reserved field names it creates — so unlike `ExportCAD`,
this call is **not** doc-verifiable to the ADR-0077 bar from the fetched
reference alone, and there's no arcpy available in this environment to
confirm it empirically. Shipping a guessed field name (e.g. `"Layer"`, the
long-standing ArcMap/Pro convention) would be exactly the un-verified-arcpy
risk ADR-0077 exists to prevent. Instead: `mapping_report.csv` is written as
the intended-mapping record, and the `.pyt` tool emits an explicit
`addWarningMessage` that the CAD file's layer names aren't renamed yet. This
is a real, disclosed functional gap, not a silent one.

**5. Deliberately NOT wired: contour polylines / TIN surface.** 8.2's
contour-polyline and TIN-surface LandXML export (as opposed to the PNEZD
point export, which is done) still needs real geometry input from an
existing contour feature class and arcpy 3D-surface authoring — a
substantially different, larger piece of work than sharing a point writer,
and explicitly "LOW priority" / "niche" per the tool's own 2026-06-28 design
doc. Left for a future, separately-scoped pass.

## Consequences

### Positive

- Issue #166's explicit "share the LandXML writer" ask is done, cleanly,
  with zero arcpy risk (the writer itself is 100% unit-tested).
- 8.2's LandXML leg (points) and 8.9's core CAD export are both real,
  working, doc-verified functionality where none existed before.
- The genuinely arcpy-risky, doc-unverifiable piece (CAD layer rename) is
  explicitly named and deferred rather than guessed at.

### Negative

- `build-cad-package`'s CAD output has correct geometry/CRS but generic
  (source-feature-class-derived) layer names, not the curated mapping —
  users must apply `mapping_report.csv` manually in their CAD software until
  the rename is wired.
- 8.2's contour-polyline/TIN leg remains unbuilt; `export-civil3d` still only
  emits points.
- Neither new arcpy path (`ExportCAD` call, `.pyt` tool class) has run
  against a real ArcGIS Pro session — untestable in this CI, per every other
  LOCAL tool in this codebase. Tracked as a functional-QA follow-up, same
  pattern as issues #178/#195/#222/#231.

## Alternatives considered

1. **Guess the `AddCADFields` reserved field names and wire the rename now.**
   Rejected — violates ADR-0077's doc-verification bar; "Layer" is a
   plausible but unconfirmed guess, and getting it wrong silently produces a
   CAD file that "works" (exports something) while quietly not doing what
   the mapping config promised.
2. **Leave both legs entirely unbuilt, ship only the writer-sharing
   refactor.** Rejected as too conservative — `ExportCAD`'s signature *is*
   cleanly doc-verified, and shipping only the safe half of a two-part
   ask leaves 8.9 at zero progress for no real risk reduction.
3. **Build a hand-rolled DXF/DWG writer to avoid arcpy risk entirely for
   8.9.** Rejected — same "new dependency reinventing what Export-to-CAD
   already does" rejection as ADR-0071 and the original 8.9 design doc; the
   value here is the mapping/validation discipline, not reimplementing CAD
   authoring.

## Related decisions

- Builds on: ADR-0071 (LandXML format decision, issue #164) — this ADR
  promotes that ADR's writer into a shared location.
- References: ADR-0077 (arcpy API currency policy) — the doc-verification
  bar that scoped out the `AddCADFields` rename.
- References: ADR-0006 (`.pyt` toolbox as primary UI for LOCAL tools) — the
  guard-then-redirect CLI shape kept for `build-cad-package`.

## Issues/PRs

- Partially addresses: #166 (LandXML sharing + 8.9 Export-to-CAD done; CAD
  layer rename + 8.2 contour/TIN leg remain — left open, re-scoped in a
  follow-up comment).
