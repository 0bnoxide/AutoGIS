# ADR-0089: CAD layer properties and Civil 3D TIN LandXML

**Status:** Proposed

**Date:** 2026-07-17

## Context

ADR-0088 completed the headless point handoff and the basic
`ExportCAD` call for issue #166, but deliberately left two functional gaps:

1. `BuildCADExportPackage` resolved a GIS-to-CAD mapping but did not apply
   the configured layer name, color, or linetype to the exported drawing.
2. `ExportContoursForCivil3D` emitted points only; it could not hand an
   existing ArcGIS Pro TIN to Civil 3D as a triangulated surface.

Both paths require arcpy and therefore remain ArcGIS Pro toolbox operations.
Core modules must remain arcpy-free (ADR-0002), and every arcpy call must meet
ADR-0077's current-documentation bar. Current ArcGIS Pro 3.6 documentation now
provides the missing evidence: `AddCADFields` creates reserved CAD fields, the
DWG/DXF reserved-field reference identifies writable `Layer`, `LyrColor`, and
`LyrLnType` fields, `ExportCAD` consumes those fields, and `TinTriangle`
converts a TIN to triangle polygons.

## Decision

### 1. Apply CAD mappings to scratch copies

`BuildCADExportPackage` copies each validated input feature class into
`arcpy.env.scratchGDB`, calls
`arcpy.conversion.AddCADFields(..., "ADD_LAYER_PROPERTIES", ...)`, and fills
`Layer`, `LyrColor`, and `LyrLnType` with an `arcpy.da.UpdateCursor`. The tool
passes those staged copies to `ExportCAD` and deletes them in `finally`.

The original feature classes are never modified. This matters because
`AddCADFields` changes its input table in place. The existing mapping report
remains as an auditable sidecar, but it now describes properties actually
applied to the CAD file rather than a manual remediation plan.

Verified ArcGIS Pro 3.6 references:

- https://pro.arcgis.com/en/pro-app/3.6/tool-reference/conversion/add-cad-fields.htm
- https://pro.arcgis.com/en/pro-app/3.6/help/data/cad/reserved-cad-fields-for-dwg-and-dxf-files.htm
- https://pro.arcgis.com/en/pro-app/3.6/tool-reference/conversion/export-to-cad.htm

### 2. Export existing Pro TINs as LandXML surfaces

The `.pyt` toolbox adds `ExportContoursForCivil3D`. It accepts an existing TIN,
surface name, EPSG code, linear unit, and output XML path. The adapter:

1. verifies that the TIN is projected and that the requested EPSG code and
   unit match its spatial reference, including a defined vertical coordinate
   system;
2. verifies, checks out, and later checks in the 3D Analyst extension;
3. calls `arcpy.ddd.TinTriangle` into the scratch geodatabase;
4. reads each triangle as `SHAPE@JSON` with `arcpy.da.SearchCursor`;
5. converts x/y/z coordinates to LandXML northing/easting/elevation order and
   deduplicates shared vertices; and
6. writes a named LandXML 1.2 `<Surface>` with `<Pnts>` and `<Faces>` through
   the shared, stdlib-only `core.common.landxml` writer.

The temporary triangle feature class is deleted in `finally`. Civil 3D can
rebuild contours from the imported TIN, so a second contour-polyline export is
not added. This is the smallest complete surface handoff and avoids two
potentially divergent representations of the same model.

Verified ArcGIS Pro 3.6 references:

- https://pro.arcgis.com/en/pro-app/3.6/tool-reference/3d-analyst/tin-triangle.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/data-access/searchcursor-class.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/classes/spatialreference.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/classes/vcs.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/functions/checkextension.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/functions/checkinextension.htm
- https://pro.arcgis.com/en/pro-app/3.6/arcpy/geoprocessing_and_python/defining-parameter-data-types-in-a-python-toolbox.htm

Autodesk documents LandXML TIN surface definitions and Civil 3D's full-import
preservation of faces:

- https://help.autodesk.com/cloudhelp/2023/ENU/Civil3D-UserGuide/files/GUID-4D10ABA5-5EA0-41A8-BB61-C3F446CE7C6B.htm

## Consequences

### Positive consequences

- CAD mapping configuration now controls the drawing's layer name, color, and
  linetype without mutating the user's geodatabase.
- Civil 3D receives the actual triangulation, not only points from which it
  might build a different surface.
- Both write paths clean up their scratch datasets on success or failure.
- Geometry-to-LandXML conversion and LandXML authoring remain arcpy-free and
  unit-testable.

### Negative consequences

- Surface export requires ArcGIS Pro with a licensed 3D Analyst extension
  because `TinTriangle` is a 3D Analyst tool.
- LOCAL-tool calls cannot run end-to-end in headless CI. The arcpy seams are
  covered with fakes, but a real-Pro smoke test remains release QA.
- When the TIN has no defined vertical coordinate system, the export must
  trust that its z-values use the selected LandXML unit. A defined mismatched
  or positive-down vertical coordinate system is blocked.

## Alternatives considered

1. **Add reserved CAD fields directly to source layers.** Rejected because it
   permanently changes user data and can collide with schema ownership.
2. **Calculate only `Layer`, omitting color and linetype.** Rejected because the
   existing mapping contract already carries all three values and the current
   reserved-field documentation verifies them.
3. **Reconstruct a TIN from the headless point CSV.** Rejected because the new
   triangulation can differ from the reviewed ArcGIS Pro model.
4. **Export both the TIN and derived contour polylines.** Rejected for this
   issue because Civil 3D derives contours from the imported surface; a second
   representation adds drift without improving the handoff.
5. **Write LandXML inside the `.pyt` adapter.** Rejected because XML authoring
   and validation do not require arcpy and belong in the shared core module.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0006: `.pyt` toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
- [ADR-0077: Current arcpy API verification](0077-arcpy-api-currency-policy.md)
- [ADR-0088: Civil 3D/CAD arcpy legs](0088-civil3d-cad-export-arcpy-legs.md)
- [Agent decisions — 2026-07-17](logs/2026-07-17-agent-decisions.md)
- [GitHub issue #166](https://github.com/0bnoxide/AutoGIS/issues/166)
