# Montana State Library HFDEM downloads

`autogis envmon download-msl-dem` is an archive-first provider independent of OpenTopography. No API key is required. The ArcGIS Pro toolbox entry is **Download Montana State Library DEM** (`DownloadMSLDEM`). Native ArcPy processing has live QA evidence; interactive map acceptance status is recorded in [QA](qa/msl-dem.md).

## Headless CLI

Install optional processing dependencies with `pip install "autogis[msl]"`. Discovery, planning and archive download remain stdlib-only; polygon shapefiles need the optional pyshp/pyproj dependencies. GeoJSON uses WGS84. Shapefiles must have a `.prj`.

```powershell
autogis envmon download-msl-dem --bbox -107.001 44.9973 -106.9998 44.9984 --out Montana_DEM.tif --dry-run
autogis envmon download-msl-dem --aoi site.geojson --project BIGHORN_2019_BHcntyQL2 --out Montana_DEM.tif --cache-dir C:\GIS\msl-cache
```

Use real project names printed by discovery. If more than one downloadable HFDEM project intersects, specify `--project` explicitly, repeating it in overlap priority order. This is deliberately more conservative than guessing whether a small overlap is consequential. The first selected project/source with a valid value wins, never a blended elevation. Raster compatibility checks still apply.

Key options:
- `--dry-run`: actual polygon inventory queries, field/domain decoding, URL HEAD validation and sizes. No archives or local files are written, including `--report`.
- `--download-only`: validated ZIP archives only. Does **not** create a DEM or pretend to fulfill clipping.
- `--cache-dir`: retained archives plus SHA256/URL/server-validator receipts. Default `.msl-cache` beside output. Corrupt or unrecognized cache files are preserved and rejected; choose a clean directory rather than silently overwriting.
- `--allow-large-download`: explicitly authorize total uncached bytes over `--large-download-gib` (default 1 GiB), or unknown-size downloads. Disk space and ZIP-expanded-size checks also apply.
- `--source projects`: explicit alternative to default `quads`, using official selected-project `Mosaics/HFDEM.zip`. Large projects are not chosen automatically. Availability/size must validate first.
- `--output-crs EPSG:6514 --resolution 1`: explicitly reproject/resample. Cell size is in target CRS units; it is mandatory with output CRS. `--resolution` alone explicitly changes the native grid. Default preserves native resolution/alignment.
- `--z-units m|int-ft|us-ft`: multiply verified artifact elevation values. Native is the default. Unknown units block conversion. This is **not a vertical datum transformation**.
- `--overwrite`: authorize replacing the GeoTIFF and provenance pair. Existing files otherwise remain unchanged.
- `--report qa.csv`: standard AutoGIS QA report. Coverage/metadata warnings are not hidden.

Only HFDEM is supported. The existing `download-dem` command is unchanged.

## ArcGIS Pro

Use the active map extent, manual bbox, or a polygon feature layer. A layer's selected features and definition query are honored; no selection means all eligible features. Holes and multipart shapes are retained. True-curve polygons must currently be densified to linear polygons explicitly. Preview before downloading. Enter exact project names separated by semicolons when prompted by multiple projects.

Horizontal output defaults to native; map CRS or explicit CRS requires an explicit output cell size. Z conversion requires verified artifact units and Spatial Analyst or Image Analyst. Adding to the current map and zooming is optional. Overwrite is an explicit parameter, independent of global Pro overwrite settings.

## Resolution, accuracy and confidence

The `.tif.json` sidecar distinguishes:
1. Measured source/output pixel spacing and its horizontal units. Smaller cells do not imply higher vertical accuracy.
2. Original inventory fields, decoded domains, collection dates, quality level, vendor, report/metadata links, NVA/VVA/RMSE and pulse information when present. These are **project-level publisher claims**, not site-specific measurements or guarantees. Missing units/confidence levels remain null; no USGS confidence level is inferred just from an NVA/VVA field name.
3. Artifact-specific vertical CRS, companion XML and accuracy prose, with archive URL/member evidence. Reported statistics, requirements and tested results must be interpreted in their source context. The program does not automatically fetch/interpret PDF accuracy reports or convert a quality level into an accuracy estimate.
4. Measured output raster-cell coverage and overlaps. Coverage is not an elevation confidence score, and a fully covered AOI is not proof of accurate heights.

Inventory `Native*` fields describe original deliveries; they can disagree with distributed quadrangle rasters. The workflow never substitutes those fields as proof of artifact units. Unknown reference metadata permits only unchanged native values from one project, with warnings. Mixed/unknown cross-project vertical references and conflicting artifact metadata stop processing.

The headless backend quantifies overlap counts and maximum differences. The native adapter currently records overlap priority but marks overlap counts/differences unknown. Neither backend performs vertical/geoid transformations. Output carries horizontal CRS, while datum/units and conversion evidence are recorded in the sidecar to avoid a stale VCS tag after unit scaling.

## Data and operational limits

- Inventory coverage and raster coverage differ. Small valid raster slivers can lie outside project polygons and cannot be discovered from that tiny AOI alone; enlarge the real AOI only when appropriate, not to fabricate coverage.
- Some downloadable inventory quads return 404. The workflow stops with the URL; it does not quietly omit those tiles.
- Archives mix projects/products. Only exactly attributed selected HFDEM rasters and their own companion metadata are extracted. Ambiguous `Quads/HFDEM` roots are rejected; use an explicitly identified project mosaic.
- ArcGIS ImageServer raw pixels were evaluated but have different NoData coverage than archives. It is not a silent fallback. MapServer rendering is never treated as elevation data.
- Downloads retry network interruptions at most three attempts. Valid cached archives are rechecked by hash, size, validators and CRC. Publication uses an exclusive lock and transactional rollback for ordinary errors; abrupt machine failure can still interrupt a two-file publication. Keep backups for valuable preexisting outputs.
- Sources are informational, not certified engineering/survey deliverables. Consult the project report and applicable standards before relying on values for design.
