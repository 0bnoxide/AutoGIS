# ADR-0071: LandXML as the CAD point-export format for `export-survey-cad`

**Status:** Accepted

**Date:** 2026-07-08

## Context

`export_survey_cad.py` (Tool: `envmon export-survey-cad`) shipped CSV/GeoJSON
layers only — the module's own comment named the gap: "DWG/DXF/LandXML CAD
export needs a template [library/Civil 3D decision]." A prior agent
deliberately declined to make that library/format call unilaterally (see
`docs/adr/logs/2026-07-01-agent-decisions.md`), and issue #164 recorded the
user's decision the same day it was flagged: **LandXML**.

This also bears on the still-unbuilt `--landxml` output leg of
`ExportContoursForCivil3D` (8.2, issue #166) and `BuildCADExportPackage`
(8.9) — both arcpy-gated and out of scope for this change, but worth sharing
serialization logic with once they're built.

## Decision

Add a `write_layer_landxml()` function to `export_survey_cad.py` that writes
one LandXML 1.2 file per layer, containing only a `<CgPoints>` element (one
`<CgPoint name="..." code="..." desc="...">northing easting elevation</CgPoint>`
per point) — no `<Surfaces>` or `<Alignments>`, since these RTK point layers
(monitoring wells, GCPs, benchmarks) carry no surface or alignment data.
Wired as `--landxml/--no-landxml` on `envmon export-survey-cad`, additive
alongside the existing `--geojson/--no-geojson` flag (both CSV plus either
or both of GeoJSON/LandXML can be requested in one run).

Point coordinate order (northing, easting, elevation) follows LandXML's
default convention, matching how Civil 3D and other consumers expect
`<CgPoint>` text content absent an explicit state-plane override.

Implemented with stdlib `xml.etree.ElementTree` — no new dependency; the
output is well-formed XML, not a hand-built string, so caller-supplied point
IDs/descriptions/feature codes are escaped correctly.

## Consequences

### Positive consequences

- Closes issue #164 with the format decision already made; zero new
  dependencies.
- The `northing easting elevation` point serialization is a natural
  candidate to share with #166's arcpy-gated `--landxml` legs once those are
  built — same coordinate convention, same element shape.

### Negative consequences

- Points-only: no surface/alignment support. If a future tool needs to
  export a TIN or an alignment as LandXML, that's new code, not a reuse of
  this writer.
- LandXML output isn't reprojected or unit-tagged (no `<Units>`/`<CoordinateSystem>`
  element) — matches this tool's existing GeoJSON behavior (coordinates pass
  through in the caller's CRS, uninterpreted).

## Alternatives considered

1. **DXF via `ezdxf`:** rejected — new dependency for a format the user didn't
   ask for; LandXML was the explicit decision.
2. **Full LandXML `<Survey>`/`<Alignments>` support:** rejected as
   over-scoped — these point layers have no line/polygon geometry to alignment-ize.

## Related decisions

- Precedes: issue #166 (arcpy-gated `ExportContoursForCivil3D --landxml` /
  `BuildCADExportPackage` CAD export legs) — shares this writer's point
  serialization where practical.

## Issues/PRs

- Closes: #164
