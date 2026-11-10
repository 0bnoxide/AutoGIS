# MSL HFDEM QA record

Date: 2026-11-10. Branch: feat/msl-hfdem-download. Base: abdc219350184a93e1ff940930b3f0fecda02567.

## Completed evidence
- Offline inventory, archives, metadata, raster, CLI and existing OpenTopography regression tests: 113 passed before native adapter addition. Includes real rasterio synthetic fixtures with gaps, holes, aligned multiple tiles, overlap differences, unknown/mixed metadata and conversion.
- Additional native adapter seam tests: selected feature layer passed directly to SearchCursor, hole geometry retained, no-active-map/empty-layer errors, bounded polygon mask and toolbox registration. Native call execution is not implied by these tests.
- Live real boundary pipeline: bbox centered on EPSG6514 (797088,86270), WGS84 +/-0.00005 degrees. Downloaded official 44106h8.zip (110551805 bytes) and 44107h1.zip (609485 bytes). Output EPSG6514, 14 rows x 10 columns, resolution (0.9144000000087544,0.9143999999942025). 97/97 AOI pixel centers covered; 12 overlap cells had maximum difference 0.0. Elevations 1195.4988 to 1196.9557. Native Z units remained unknown, scale factors 1.0, not inferred from original delivery feet metadata.
- Live partial coverage: bbox (-107.001,44.99,-106.9998,44.9984), same cached archives. 34,935 of 105,643 AOI pixel centers valid (33.0689%); 70,708 remain NoData. 349 overlap cells have zero difference. Explicit scale factors 1.0 preserve source values.
- Final complete suite at bf0ed240517fa5ba77a52f401bfecd6be91b5dd8: **4053 passed, 27 skipped**, 62.69 seconds. Base-dependency installed-wheel smoke: PASS.
- Independent exact-code-head review: **PASS**; 65 focused tests passed. BOUNDARY_SHAPE, CONTRACT_REACHABILITY, IDENTITY_PROVENANCE, SIDE_EFFECT_SAFETY and ENVIRONMENT_SEAM all PASS. Six initial findings were corrected and re-probed, including unrelated-directory protection and interrupted ZIP/receipt publication. No remaining code blockers were reported.
- ADR allocation was reserved locally with strict scan (0137). The required hosted ADR policy subsequently passed on [PR #612](https://github.com/0bnoxide/AutoGIS/pull/612).

## Publication follow-up
- PR #612 was published ready for review on owner authorization, without merging.
- Initial hosted CI found one test that assumed optional rasterio availability. The test-only correction separately exercises real CRS validation and missing-backend imports. Both dependency configurations passed locally; hosted commit 5ad9364 subsequently passed 3,914 tests with 32 skipped, plus wheel smoke, ADR policy and repository self-check.
- Sonar measured 66.3% new-code coverage against the unchanged 80% gate. This follow-up enables the MSL extra in the existing CI job and adds focused CLI/native adapter/toolbox execution tests. ArcPy I/O doubles are explicit and do not claim to implement Esri raster algorithms or prove interactive UI acceptance.
- Base-configuration follow-up without optional rasterio: **4,104 passed, 28 skipped**, with one upstream pytest-plugin deprecation warning.
- Integrated follow-up suite with optional MSL dependencies: **4,111 passed, 27 skipped** (45 dependency/resource warnings). Local changed-line coverage is **933/1,050 = 88.86%**: CLI/toolbox execution 100%, native adapter 96.65%, archive core 84.02%, raster processor 90.82%. These are local measurements; hosted Sonar results remain authoritative.
- In-memory mutation checks rejected removed NoData double-reading, vertical reprojection, reversed conversion factor, omitted license check-in, omitted polygon union, wrong-map zooming and bypassed license preflight. Production logic and coverage exclusions were not changed.

## Native Pro validation
Initial sandboxed imports reported an uninitialized product license. Normal authorized desktop execution of the same cloned Python initializes existing Pro 3.6.1 correctly; no sign-in, license or settings changes were required.

- Independent real ArcPy full synthetic-archive workflow published TIFF/JSON and cleaned staging. Source values [[1,0],[3,4]], NoData 0, AOI wider than source: 3/6 AOI cells valid; missing coverage preserved.
- Real cached MSL boundary workflow passed native ArcPy: 98/98 AOI cells valid at 0.9144 m, Z units unknown. ArcPy selected WGS_1984_(ITRF08)_To_NAD_1983_2011 for AOI projection. Its 98-versus-headless-97 count reflects the recorded transformation/grid boundary choices, not a source elevation difference.
- Native donut fixture: 12/12 expected cells valid, 4 hole cells NoData, source value 10 m unchanged. Unit conversion produced 32.80833435058594 US survey feet, preserved hole/NoData and NAVD88 sidecar. Explicit EPSG:3857 / 1000 m reprojection passed with values 10 and NoData intact.
- Real toolbox qualification passed all 24 checks, including import and all 16 DownloadMSLDEM parameters.
- Interactive active-map, selected-feature and map-insertion acceptance is **unverified**. Pro launched successfully, but the desktop-control window-binding operation hung for approximately 11 minutes and was interrupted. No interactive acceptance actions, project edits or scratch project creation occurred. This is a UI-control limitation, not a Pro startup/license failure. Do not infer UI acceptance from native script tests.

## Acceptance procedure for interactive Pro
Run with PYTHONPATH pointing to the feature worktree (do not replace the installed package without authorization). In ArcGIS Pro >=3.5:
1. Load this branch's toolbox using its matching package, select one of two polygon features including a hole. Preview and confirm actual selected geometry/project/quad URLs and size.
2. Run a small known MSL AOI with native settings; verify raster cells, CRS, spacing, true polygon clip, NoData and sidecar against the downloaded HFDEM.
3. Cross a quad boundary; verify seam values and a partial-coverage case. Confirm native metadata does not silently become assumed Z units.
4. Try overlapping projects without selection: it must stop. Explicitly selected incompatible references must still stop.
5. Test verified-unit conversion and horizontal reprojection with explicit cell size, checking values/NoData/datum unchanged by unit conversion. Verify output map insertion and zoom.
6. Verify existing output refusal, explicit replacement, unavailable conversion license and invalid CRS errors. Retain exact command/output evidence.

## ArcPy contract references verified this session
All are official Esri references; latest URLs redirect to doc.esri.com. Compliance floor 3.5.
- [Parameter](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/parameter.htm), [Filter](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/filter.htm): constructor multiValue; polygon filter.
- [SearchCursor](https://pro.arcgis.com/en/pro-app/latest/arcpy/data-access/searchcursor-class.htm), [cursor selection semantics](https://pro.arcgis.com/en/pro-app/latest/arcpy/get-started/data-access-using-cursors.htm): layer selection and definition query.
- [Geometry](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/geometry.htm), [AsShape](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/asshape.htm): JSON, union, projectAs, WGS84 GeoJSON Polygon with holes.
- [SpatialReference3.5](https://pro.arcgis.com/en/pro-app/3.5/arcpy/classes/spatialreference.htm), [ListTransformations3.5](https://pro.arcgis.com/en/pro-app/3.5/arcpy/functions/listtransformations.htm): WKT load/export, horizontal/vertical distinction, extent-ranked horizontal transform.
- [Raster dataset](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/raster-dataset-properties.htm), [raster band](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/raster-band-properties.htm), [Raster](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/raster-object.htm): metadata and NoData.
- [CopyFeatures](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/copy-features.htm): geometry list to polygon feature class.
- [MosaicToNewRaster](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/mosaic-to-new-raster.htm): explicit float pixel type, one band, FIRST method; no 8-bit default.
- [Clip](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/clip.htm): ClippingGeometry and NO_MAINTAIN_EXTENT.
- [ProjectRaster3.5](https://pro.arcgis.com/en/pro-app/3.5/tool-reference/data-management/project-raster.htm): BILINEAR, explicit cell_size, NO_VERTICAL.
- [Times](https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/times.htm): conversion license requirement; [EnvManager](https://pro.arcgis.com/en/pro-app/latest/arcpy/classes/envmanager.htm).
- [RasterToNumPyArray](https://pro.arcgis.com/en/pro-app/latest/arcpy/functions/rastertonumpyarray-function.htm): bounded block reads, outside extent NoData, double-read zero/one replacement detects genuine NoData without sentinel collision.
- [DefineProjection](https://pro.arcgis.com/en/pro-app/latest/tool-reference/data-management/define-projection.htm): horizontal metadata only, not coordinate transformation.
- [Map](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/map-class.htm), [MapView](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/mapview-class.htm), [Camera](https://pro.arcgis.com/en/pro-app/latest/arcpy/mapping/camera-class.htm): addDataFromPath/getLayerExtent/setExtent.
