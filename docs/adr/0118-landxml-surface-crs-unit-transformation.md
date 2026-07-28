# ADR-0118: LandXML surface CRS and unit transformation

**Status:** Proposed

**Date:** 2026-07-27

## Context

CAD surface handoffs sometimes arrive as LandXML in one projected coordinate
system and must return to CAD in another. The same exchange can cross meter,
international-foot, and US-survey-foot coordinate systems. Re-labelling the
LandXML `<Units>` or `<CoordinateSystem>` blocks is not sufficient: horizontal
coordinates must be projected, elevations must be scaled, and the original TIN
faces must remain attached to the same point IDs.

AutoGIS already has a stdlib-only LandXML TIN parser/writer and exact elevation
unit conversion in the DEM and Pro-TIN export paths. The missing piece is an
arcpy-free LandXML-to-LandXML operation usable from the CLI, unified GUI, and
ArcGIS Pro toolbox. The input may omit CRS/unit metadata or contain several
surfaces, so the tool also needs a fail-closed source contract.

## Decision

Add `core.envmon.landxml_transform.transform_landxml_surface` and expose it as
`envmon transform-landxml`, the GUI form generated from that Click command, and
Tool 8.2a `TransformLandXMLSurface` in `toolbox.pyt`.

The operation has these boundaries:

1. It transforms exactly one selected triangulated `<Surface>`. Point IDs,
   triangle faces, and the surface name are preserved; callers may explicitly
   select or rename the surface. Multiple surfaces without an exact selection
   are rejected. Alignments, parcels, breaklines, boundaries, styles, and other
   LandXML/CAD metadata are intentionally not copied into the clean output.
2. Source and target CRSs are explicit EPSG codes and must both be projected.
   `pyproj.Transformer.from_crs` runs with `always_xy=True`,
   `allow_ballpark=False`, and per-point error checking. Each CRS's two
   horizontal axes must use the selected LandXML unit, preventing coordinate
   values and `<Units>` metadata from disagreeing.
3. Horizontal units support every pair among LandXML `meter`, `foot`
   (international foot), and `USSurveyFoot`. Elevations use the exact
   meters-per-unit ratios already shared with the Pro-TIN exporter. An optional
   source elevation unit handles CAD surfaces whose Z unit differs from X/Y;
   output X/Y/Z all use the target unit so one LandXML unit declaration remains
   truthful.
4. Declared source EPSG/unit metadata is checked against the explicit inputs.
   A mismatch blocks conversion unless the caller deliberately enables the
   source-metadata override. Input and output paths must differ, and an existing
   output requires the overwrite option.
5. Malformed points and faces fail closed: duplicate point IDs, non-finite or
   non-3D coordinates, non-triangular/degenerate faces, and unknown face
   references are rejected instead of silently dropping geometry.
6. `pyproj` is a lazy optional dependency in the `landxml` extra. Core remains
   arcpy-free. This slice performs horizontal projected-CRS transformations and
   linear Z scaling only; it does not claim a vertical datum/geoid
   transformation.

## Consequences

### Positive consequences

- CAD surface triangulation survives the coordinate conversion instead of
  being regenerated from points.
- The same pure implementation serves CLI, GUI, and Pro-toolbox users.
- Explicit unit/CRS checks make a wrong-foot or metadata-only conversion fail
  before output is written.
- Mixed horizontal/vertical input units can be corrected without ArcGIS
  extensions.

### Negative consequences

- The output is a normalized single-surface LandXML file, not a lossless rewrite
  of every object and vendor extension in the source document.
- Users must know the source CRS and units when the input omits or misstates
  them, and overriding declared metadata is intentionally explicit.
- Datum transformations can depend on locally available PROJ grids. Disabling
  ballpark operations favors correctness over always producing an output.
- Vertical datum changes remain a separate future capability; converting Z
  units does not convert NAVD88, NGVD29, ellipsoidal, or geoid-based heights.

## Alternatives considered

1. **Change only LandXML metadata.** Rejected because it mislocates or
   mis-scales the surface while making the file appear valid.
2. **Round-trip through an ArcGIS Pro TIN.** Rejected because projection and
   unit scaling do not require arcpy or a 3D Analyst license, and a pure path is
   usable in automation and CI.
3. **Re-triangulate transformed points.** Rejected because CAD must receive the
   reviewed source faces, not a new surface that may contour differently.
4. **Losslessly rewrite every LandXML object.** Deferred because coordinate
   semantics for alignments, parcels, breaklines, and vendor extensions are
   broader than the requested surface handoff and cannot safely be treated as
   opaque XML.
5. **Fold vertical datum conversion into this slice.** Deferred because a
   vertical CRS, transformation-grid availability, and accuracy/provenance
   policy are distinct from linear-unit conversion.

## Related decisions

- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0006: `.pyt` toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
- [ADR-0089: CAD layer properties and Civil 3D TIN LandXML](0089-cad-layer-properties-and-civil3d-tin-landxml.md)
- [Agent decisions — 2026-07-27](logs/2026-07-27-agent-decisions.md)
- [pyproj Transformer API](https://pyproj4.github.io/pyproj/stable/api/transformer.html)
- [pyproj CRS API](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html)
- [Autodesk: supported Civil 3D LandXML data](https://help.autodesk.com/cloudhelp/2025/ENG/Civil3D-UserGuide/files/GUID-4D10ABA5-5EA0-41A8-BB61-C3F446CE7C6B.htm)
- [Autodesk: full versus quick surface import](https://help.autodesk.com/cloudhelp/2024/ENG/Civil3D-UserGuide/files/GUID-FB6846E6-9E14-4C2D-B06A-E96FBD1399DB.htm)
- [ArcGIS Pro: defining Python toolbox parameters](https://pro.arcgis.com/en/pro-app/3.6/arcpy/geoprocessing_and_python/defining-parameters-in-a-python-toolbox.htm)
