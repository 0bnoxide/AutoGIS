# Harvest photo-metadata suite — design

- **Date:** 2026-08-12
- **Status:** Approved by owner (this session); implementation not started
- **Owner decisions:** all four emitters selected; geometry source = fill at
  harvest with geometry-less fallback for old manifests; photographic log in
  XLSX + HTML + DOCX (default xlsx)

## Problem

The attachment harvester's output (example: the RILEY_PASS seeps/springs
harvest) contains two layers of metadata that nothing in AutoGIS reads today:

1. **EXIF inside each photo** — GPS lat/lon, compass heading
   (`GPSImgDirection` + true/magnetic ref), `DateTimeOriginal`, camera
   make/model. Field tablets (e.g. Samsung SM-X308U) embed a full,
   independent georecord in every shot.
2. **Reserved manifest columns** — `geometry`, `checksum`, `algorithm` exist
   in `AttachmentResult` / `manifest.csv` but are always null; the harvester
   queries with `return_geometry=False`.

Tool 7.4 (`well_inspection_photo_report.py`) works around this by requiring a
hand-built GPS CSV, and uses EXIF only for orientation flipping.

## Goal

One shared, headless EXIF-extraction core plus four thin emitters, and a
small harvester change that finally fills the reserved manifest columns.
Everything arcpy-free and arcgis-free at read time (harvest itself already
requires arcgis, unchanged).

## Architecture

```
manifest.csv/.json ──┐
                     ├─ core/envmon/photo_metadata.py
photo files (EXIF) ──┘      load_photo_records() → list[PhotoRecord]
                                   │
        ┌──────────────┬───────────┼──────────────┐
     points          qa          log            kmz
  (CSV+GeoJSON)  (QACollector) (xlsx/html/docx) (zip+KML)
```

Rejected alternative: four independent tools each reading EXIF — duplicates
the fiddly part four times.

### PhotoRecord (core/envmon/photo_metadata.py)

Manifest identity + EXIF, per photo:

| Field | Source | Notes |
|---|---|---|
| `objectid, attachment_id, source_table, group, saved_path` | manifest | group = folder segment, as in Tool 7.4 |
| `exif_lat, exif_lon` | EXIF GPSInfo | WGS84 decimal degrees; None if absent |
| `heading_deg, heading_ref` | EXIF `GPSImgDirection(Ref)` | ref `T` (true) or `M` (magnetic); no declination correction |
| `taken_at` | EXIF `DateTimeOriginal` | naive local ISO8601 (device rarely writes an offset) |
| `camera` | EXIF Make + Model | single string |
| `feature_lat, feature_lon` | manifest `geometry` | None on pre-change manifests |
| `feature_edited_at` | manifest (new column) | None on pre-change manifests |

`load_photo_records(harvest_dir)` reads the manifest via the existing
`index_field_attachments.load_manifest`, then extracts EXIF per
`saved_path`. Pillow is lazy-imported inside the extraction path (same
pattern as Tool 7.4; installs via the existing `[report]` extra). Only
`downloaded`/`skipped` dispositions with an existing file are read.
Unreadable/non-image files and missing-GPS photos produce QA WARNINGs, never
crashes; they are excluded from spatial outputs but still appear in the log.

## Harvester change (fills the reserved columns)

In `_harvest_layer` (`core/harvest/harvester.py`):

- Query with `return_geometry=True`. Store a **representative point** in the
  reserved `geometry` column as `{"lat": <dd>, "lon": <dd>}` (WGS84):
  points as-is; lines/polygons use the vertex centroid. Web Mercator
  (102100/3857) → WGS84 is the closed-form few-liner — no pyproj. Other
  spatial references: leave geometry null and record a manifest-level
  warning (ceiling; extend when a non-mercator service shows up).
- New optional manifest column `feature_edited_at` (ISO8601 UTC from
  editor-tracking `EditDate` when the layer has it; else null). Appended
  after existing columns; readers must tolerate its absence.
- `sha256` each downloaded file into `checksum`/`algorithm`. Skipped
  (already-present) files are hashed too — same one-liner, enables
  dedup later.

Back-compat: old manifests simply have nulls; every consumer treats
geometry/checksum/feature_edited_at as optional.

## Emitters (CLI: `autogis envmon photos <cmd>`, all headless)

### `points` — CSV + GeoJSON
One point per GPS-bearing photo. Fields: `photo_path`, `source_table`,
`objectid`, `attachment_id`, `group`, `lat`, `lon`, `heading_deg`,
`heading_ref`, `taken_at`, `camera`, `feature_lat`, `feature_lon`,
`offset_m` (haversine photo→feature, null when feature geometry missing).
GeoJSON via stdlib `json`; the same records feed both outputs.

### `qa` — photo↔feature cross-check (QACollector idiom)
- **Distance:** WARNING when `offset_m` > threshold (`--max-offset-m`,
  default 100).
- **Date:** WARNING when EXIF date differs from `feature_edited_at` by more
  than ±1 day (day-level comparison dodges timezone noise). Skipped when
  either side is null.
- **Inventory:** WARNINGs for missing GPS, missing EXIF datetime,
  unreadable files.
- Geometry/date checks auto-skip (INFO, not failure) on geometry-less
  manifests such as RILEY_PASS; re-harvest to enable them.

### `log` — photographic log appendix
Columns: photo #, thumbnail, group/feature, taken_at, direction (degrees +
cardinal), coordinates, blank description column (for hand-editing), source
path. Formats via `--format {xlsx|html|docx}`, default `xlsx`:
- **xlsx** — openpyxl + Pillow thumbnails, mirrors Tool 7.4's embedding path.
- **html** — existing `core/common/report_html.py` styling.
- **docx** — `python-docx`, new optional extra `report-docx` (lazy import).

### `kmz` — Google Earth
Stdlib `zipfile` + hand-written KML. One placemark per GPS-bearing photo:
name, heading on the icon style, description HTML with an `<img>` pointing
at a zipped thumbnail (Pillow-downsized, max edge ~800 px, so the KMZ stays
small).

## Error handling

- No manifest in the target dir → clear error naming the expected files.
- Zero GPS-bearing photos → `points`/`kmz` still write valid empty outputs
  and say so; `log` works regardless (coords blank).
- Corrupt EXIF → treat as absent, WARNING.

## Testing

- Synthetic JPEGs with crafted EXIF (GPS, heading, datetime) built in-test
  via Pillow, `importorskip`-gated like existing image tests.
- Manifest fixtures (with and without geometry/feature_edited_at) for the
  join, QA thresholds, and back-compat null handling.
- Harvester fill logic tested against the existing fake-layer test doubles;
  mercator→WGS84 conversion unit-tested against known coordinates.
- KMZ/GeoJSON outputs schema-checked (parse the KML/JSON back).

## Process requirements

- ADR for the tool batch + harvester-column decision (number vs origin/main
  and all open PRs at write time).
- Five-probe PR table per `docs/pr-review-failure-mode-audit.md`;
  independent pr-reviewer before merge.
- The harvester edit touches the live AGOL query path (arcgis, not arcpy —
  ADR-0077 doc-verification n/a, but): one live smoke harvest against a real
  layer before merge to confirm `return_geometry=True` payloads and the
  geometry fill.

## Out of scope (deliberate)

- Duplicate-photo detection (checksums land now; the report can come later).
- Live AGOL re-query to backfill geometry for old harvests (re-harvest
  instead).
- Magnetic-declination correction of `M`-ref headings (ref is recorded).
- Non-Web-Mercator/WGS84 spatial reference conversion (nulled + warned).
