# MSL HFDEM QA record

Date: 2026-11-10. Branch: feat/msl-hfdem-download. Base: abdc219350184a93e1ff940930b3f0fecda02567.

## Completed evidence
- Offline inventory, archives, metadata, raster, CLI and existing OpenTopography regression tests: 113 passed before native adapter addition. Includes real rasterio synthetic fixtures with gaps, holes, aligned multiple tiles, overlap differences, unknown/mixed metadata and conversion.
- Additional native adapter seam tests: selected feature layer passed directly to SearchCursor, hole geometry retained, no-active-map/empty-layer errors, bounded polygon mask and toolbox registration. Native call execution is not implied by these tests.
- Live real boundary pipeline: bbox centered on EPSG6514 (797088,86270), WGS84 +/-0.00005 degrees. Downloaded official 44106h8.zip (110551805 bytes) and 44107h1.zip (609485 bytes). Output EPSG6514, 14 rows x10 columns, resolution (0.9144000000087544,0.9143999999942025). 97/97 AOI pixel centers covered; 12 overlap cells had maximum difference 0.0. Elevations 1195.4988 to1196.9557. Native Z units remained unknown, scale factors1.0, not inferred from original delivery feet metadata.
- Live partial coverage: bbox (-107.001,44.99,-106.9998,44.9984), same cached archives. 34,935 of105,643 AOI pixel centers valid (33.0689%); 70,708 remain NoData. 349 overlap cells have zero difference. Explicit scale factors1.0 preserve source values.
- Full suite / independent review: pending record below.

## Native Pro validation
Initial sandboxed imports reported an uninitialized product license. Normal authorized desktop execution of the same cloned Python initializes existing Pro3.6.1 correctly; no sign-in, license or settings changes were required.

- Independent real ArcPy full synthetic-archive workflow published TIFF/JSON and cleaned staging. Source values [[1,0],[3,4]], NoData0, AOI wider than source: 3/6 AOI cells valid; missing coverage preserved.
- Real cached MSL boundary workflow passed native ArcPy: 98/98 AOI cells valid at0.9144m, Z units unknown. ArcPy selected WGS_1984_(ITRF08)_To_NAD_1983_2011 for AOI projection. Its98-vs-headless97 count reflects the recorded transformation/grid boundary choices, not a source elevation difference.
- Native donut fixture:12/12 expected cells valid,4 hole cells NoData, source value10m unchanged. Unit conversion produced32.80833435058594 US survey feet, preserved hole/NoData and NAVD88 sidecar. Explicit EPSG3857/1000m reprojection passed with values10 and NoData intact.
- Interactive active-map, selected-feature and map-insertion acceptance is being checked separately. Do not infer UI acceptance from native script tests.

## Acceptance procedure for interactive Pro
Run with PYTHONPATH pointing to the feature worktree (do not replace the installed package without authorization). In ArcGIS Pro >=3.5:
1. Load this branch's toolbox using its matching package, select one of two polygon features including a hole. Preview and confirm actual selected geometry/project/quad URLs and size.
2. Run a small known MSL AOI with native settings; verify raster cells, CRS, spacing, true polygon clip, NoData and sidecar against the downloaded HFDEM.
3. Cross a quad boundary; verify seam values and a partial-coverage case. Confirm native metadata does not silently become assumed Z units.
4. Try overlapping projects without selection: it must stop. Explicitly selected incompatible references must still stop.
5. Test verified-unit conversion and horizontal reprojection with explicit cell size, checking values/NoData/datum unchanged by unit conversion. Verify output map insertion and zoom.
6. Verify existing output refusal, explicit replacement, unavailable conversion license and invalid CRS errors. Retain exact command/output evidence.

## ArcPy contract references verified this session
All are official Esri references; latest URLs redirect to doc.esri.com. Compliance floor3.5.
- [Parameter](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/parameter.htm), [Filter](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/filter.htm): constructor multiValue; polygon filter.
- [SearchCursor](https://pro.arcgis.com/en/pro-app/latest/arcpy/data-access/searchcursor-class.htm), [cursor selection semantics](https://pro.arcgis.com/en/pro-app/latest/arcpy/get-started/data-access-using-cursors.htm): layer selection and definition query.
- [Geometry](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/geometry.htm), [AsShape](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/asshape.htm): JSON, union, projectAs, WGS84 GeoJSON Polygon with holes.
- [SpatialReference3.5](https://pro.arcgis.com/en/pro-app/3.5/arcpy/classes/spatialreference.htm), [ListTransformations3.5](https://pro.arcgis.com/en/pro-app/3.5/arcpy/functions/listtransformations.htm): WKT load/export, horizontal/vertical distinction, extent-ranked horizontal transform.
- [Raster dataset](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/raster-dataset-properties.htm), [raster band](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/raster-band-properties.htm), [Raster](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/raster-object.htm): metadata and NoData.
- [CopyFeatures](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/copy-features.htm): geometry list to polygon feature class.
- [MosaicToNewRaster](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/mosaic-to-new-raster.htm): explicit float pixel type, one band, FIRST method; no8-bit default.
- [Clip](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/clip.htm): ClippingGeometry and NO_MAINTAIN_EXTENT.
- [ProjectRaster3.5](https://pro.arcgis.com/en/pro-app/3.5/tool-reference/data-management/project-raster.htm): BILINEAR, explicit cell_size, NO_VERTICAL.
- [Times](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/times.htm): conversion license requirement; [EnvManager](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/envmanager.htm).
- [RasterToNumPyArray](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/rastertonumpyarray-function.htm): bounded block reads, outside extent NoData, double-read zero/one replacement detects genuine NoData without sentinel collision.
- [DefineProjection](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/define-projection.htm): horizontal metadata only, not coordinate transformation.
- [Map](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/map-class.htm), [MapView](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/mapview-class.htm), [Camera](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/camera-class.htm): addDataFromPath/getLayerExtent/setExtent.
