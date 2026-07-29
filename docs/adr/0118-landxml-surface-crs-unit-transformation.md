# ADR-0118: LandXML surface CRS and unit transformation

**Status:** Proposed

**Date:** 2026-07-27

## Context

CAD surface handoffs sometimes arrive as LandXML in a geographic or projected
coordinate system and must return to CAD in another projected system. The same
exchange can cross meter, international-foot, and US-survey-foot coordinate
systems and may require a named datum transformation. Re-labelling the LandXML
`<Units>` or `<CoordinateSystem>` blocks is not sufficient: horizontal
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
2. The source accepts an authority-coded geographic or projected CRS (for
   example `EPSG:4326` or `ESRI:102700`). The output remains a projected EPSG
   CRS because the shared LandXML writer requires a machine-readable
   `epsgCode`. LandXML `P` values remain northing/easting/elevation, so a
   geographic input is latitude/longitude/elevation; pyproj receives
   longitude/latitude through `always_xy=True`.
3. Horizontal units are inferred from the CRS axes. The target CRS's unit
   becomes the output LandXML `<Units>` value. Former `source_unit` and
   `target_unit` inputs remain accepted only as deprecated consistency
   assertions; the CLI hides them and the Pro toolbox keeps their original
   positional slots as optional parameters.
4. The selected surface is parsed before operation selection. Its bounds are
   resolved to a geographic area of interest and passed to
   `pyproj.TransformerGroup` with `authority="any"`, `always_xy=True`, and
   `allow_ballpark=False`. With no override, the first ranked available
   operation is used. A caller may instead require an exact transformation name
   or authority code, such as `WGS_1984_(ITRF00)_To_NAD_1983` or
   `ESRI:108190`. Missing grids, an unavailable requested operation, invalid
   extents, and non-finite output fail closed; AutoGIS never downloads grids.
5. Elevations use either an exact unit ratio or one positive finite custom
   multiplier. `source_z_unit` selects exact automatic conversion into the
   inferred target unit. For geographic input, declared LandXML units are the
   default Z unit, not a horizontal-degree unit. `z_scale` replaces the entire
   automatic conversion (so values such as `3.28` or `0.03` are deliberately
   accepted) and is mutually exclusive with `source_z_unit`.
6. Exact automatic factors include meter to international foot
   `3.280839895013123`, meter to US survey foot `3.280833333333333`,
   international foot to meter `0.3048`, and US survey foot to meter
   `0.3048006096012192`. A custom factor is reported as custom rather than
   described as a unit conversion.
7. Declared source CRS/unit metadata is checked against the explicit source and
   inferred projected-axis unit. Both `CoordinateSystem@epsgCode` and
   authority-qualified `CoordinateSystem@name` are recognized. A contradiction
   blocks conversion unless the caller deliberately enables the source-metadata
   override. Input and output paths must differ, and an existing output requires
   the overwrite option.
8. Malformed points and faces fail closed: duplicate point IDs, non-finite or
   non-3D coordinates, non-triangular/degenerate faces, and unknown face
   references are rejected instead of silently dropping geometry.
9. `pyproj>=3.4` is a lazy optional dependency in the `landxml` extra. Core
   remains arcpy-free. The result and CLI/Pro messages report the source/target
   CRS and units, selected operation name/code/accuracy, and effective Z factor.
   This slice performs horizontal CRS transformations and linear Z scaling
   only; it does not claim a vertical datum/geoid
   transformation.

## Consequences

### Positive consequences

- CAD surface triangulation survives the coordinate conversion instead of
  being regenerated from points.
- The same pure implementation serves CLI, GUI, and Pro-toolbox users.
- CRS-derived units make a wrong-foot or metadata-only conversion fail before
  output is written.
- Mixed horizontal/vertical input units can be corrected without ArcGIS
  extensions.
- Geographic inputs and named datum transformations now match the useful
  semantics of ArcGIS Project without introducing an arcpy dependency.

### Negative consequences

- The output is a normalized single-surface LandXML file, not a lossless rewrite
  of every object and vendor extension in the source document.
- Users must know the source CRS and the elevation unit when geographic input
  omits or misstates metadata, and overriding declared metadata is
  intentionally explicit.
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

- [Issue #385: ArcGIS-style LandXML transformations and inferred CRS units](https://github.com/0bnoxide/AutoGIS/issues/385)
- [ADR-0002: arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0006: `.pyt` toolbox as primary UI](0006-pyt-toolbox-as-primary-ui.md)
- [ADR-0089: CAD layer properties and Civil 3D TIN LandXML](0089-cad-layer-properties-and-civil3d-tin-landxml.md)
- [Agent decisions — 2026-07-27](logs/2026-07-27-agent-decisions.md)
- [pyproj Transformer API](https://pyproj4.github.io/pyproj/stable/api/transformer.html)
- [pyproj CRS API](https://pyproj4.github.io/pyproj/stable/api/crs/crs.html)
- [Autodesk: supported Civil 3D LandXML data](https://help.autodesk.com/cloudhelp/2025/ENG/Civil3D-UserGuide/files/GUID-4D10ABA5-5EA0-41A8-BB61-C3F446CE7C6B.htm)
- [Autodesk: full versus quick surface import](https://help.autodesk.com/cloudhelp/2024/ENG/Civil3D-UserGuide/files/GUID-FB6846E6-9E14-4C2D-B06A-E96FBD1399DB.htm)
- [ArcGIS Pro: defining Python toolbox parameters](https://pro.arcgis.com/en/pro-app/3.6/arcpy/geoprocessing_and_python/defining-parameters-in-a-python-toolbox.htm)
- [ArcGIS Pro: Project](https://pro.arcgis.com/en/pro-app/3.6/tool-reference/data-management/project.htm)
- [ArcGIS Pro: geographic transformation tables](https://pro.arcgis.com/en/pro-app/latest/help/mapping/properties/pdf/geographic_transformations.pdf)
- [Agent decisions — 2026-07-28](logs/2026-07-28-agent-decisions.md)
