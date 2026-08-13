# ADR-XXXX: Harvest photo-metadata suite — EXIF core, four headless emitters, harvester column fill

**Status:** Proposed

**Date:** 2026-08-13

> **Number assigned at merge.** Filed as an `XXXX-` placeholder per
> `docs/adr/README.md` § File naming, because this branch may land alongside
> other open ADR-bearing PRs — confirmed live: PR #494 is open right now with
> its own `XXXX-open-issue-fix-batch-2026-08-13.md`, and `coord reserve-adr`
> independently handed out a stale, already-merged number (0129) while
> writing this ADR (issue #495), which is exactly the #492 collision this
> convention exists to prevent. At merge: take the next free number after
> checking both `docs/adr/` and the files of every other open PR, rename the
> file, fix the H1, and replace the `XXXX` row in the index.

## Context

The attachment harvester's output (example: the RILEY_PASS seeps/springs
harvest) carries two layers of metadata nothing in AutoGIS reads today:

1. **EXIF inside each photo** — GPS lat/lon, compass heading
   (`GPSImgDirection` + true/magnetic ref), `DateTimeOriginal`, camera
   make/model. Field tablets (e.g. Samsung SM-X308U) embed a full,
   independent georecord in every shot.
2. **Reserved manifest columns** — `geometry`, `checksum`, `algorithm` exist
   on `AttachmentResult` (ADR-0012, "reserved provenance columns for future
   use") but were always null: the harvester queried with
   `return_geometry=False` and never hashed downloaded files.

Tool 7.4 (`GenerateWellInspectionPhotoReport`, ADR-0046) works around this
today by requiring a hand-built GPS CSV and uses EXIF only for orientation
flipping — every other report/export tool ignores photo metadata entirely.

Design: [`docs/superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md`](../superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md),
owner-approved 2026-08-12. Implemented across seven tasks on this branch:
Tasks 1-3 the EXIF core and QA evaluation, Tasks 4-6 the four emitters, Task
7 (this ADR) the CLI subgroup and README.

## Decision

**Core.** One new arcpy/arcgis-free module, `core/envmon/photo_metadata.py`:
a `PhotoRecord` dataclass (manifest identity + EXIF, one row per usable
photo) and `load_photo_records(harvest_dir, qa)`, which joins the harvest
manifest (via the existing `index_field_attachments.load_manifest`) with
per-file EXIF. Pillow is lazy-imported inside the extraction path (same
lazy-import shape as Tool 7.4; installs via the existing `report` extra).
Only `downloaded`/`skipped` dispositions with a file that still exists are
read; unreadable images, missing GPS, and missing EXIF datetime are QA
WARNINGs, never crashes. `evaluate_photo_qa(records, qa, *,
max_offset_m=100.0)` cross-checks EXIF against the manifest's feature-side
geometry/edit-date: a haversine-distance WARNING past the threshold, a
day-granularity date-mismatch WARNING, and one INFO
(`geometry_checks_skipped`) — not a wall of failures — when every record's
feature geometry is null, which is the common case for any harvest made
before this suite (RILEY_PASS included).

**Four thin emitters**, all consuming the same `list[PhotoRecord]` (the
spec's chosen design over four independent EXIF readers, which would
duplicate the fiddly extraction path four times):

- `core/envmon/photo_points.py` — `write_points_csv` / `write_points_geojson`
  (stdlib `csv`/`json`; one row/feature per GPS-bearing photo) and
  `write_kmz` (stdlib `zipfile` + hand-written KML; one placemark per photo,
  heading on the icon style, thumbnail reused via the existing
  `well_inspection_photo_report.prepare_image_bytes`).
- `core/envmon/photo_log.py` — `write_log(records, out_path, *, fmt, title)`:
  a photographic-log appendix (photo #, thumbnail, group/feature, taken-at,
  direction, coordinates, blank description column, source path) in
  `xlsx` (openpyxl, mirrors Tool 7.4's embedding path), `html` (reuses
  `core/common/report_html.py`, ADR-0083), or `docx` (`python-docx`, new
  lazy-imported `report-docx` extra — a separate, opt-in dependency path;
  ADR-0083 deferred DOCX for the HTML/Markdown *report template system*
  specifically, not this tool).

**Harvester fill** (`core/harvest/harvester.py::_harvest_layer`): the query
gains `return_geometry=True`. `_rep_point_wgs84` reduces a feature's
geometry to one representative point (the point itself, or the vertex
centroid for lines/polygons) and converts it to WGS84 lat/lon with a
closed-form conversion covering WGS84 (4326) and Web Mercator
(3857/102100) — the two spatial references AGOL layers actually use here —
written into the reserved `geometry` column as `{"lat": ..., "lon": ...}`.
Any other spatial reference leaves `geometry` null and logs one warning per
layer (not per feature). Every downloaded **and** skip-existing file is
sha256'd into `checksum`/`algorithm` (hashing skip-existing files too is
what makes future dedup possible). A new optional column,
`feature_edited_at` (ISO8601 UTC), is read from the layer's
`editFieldsInfo.editDateField` when editor tracking is enabled, else null,
and is appended after every existing `AttachmentResult` field.

**CLI.** One new subgroup, `autogis envmon photos` (`points` / `qa` / `log`
/ `kmz`), added to `autogis/adapters/cli.py` following the `envmon coc`
subgroup idiom (ADR-0107): a bare `@envmon.group("photos")` plus one
`@photos_group.command(...)` per emitter, each importing its core module
inside the function body (the `adapters/` arcpy/arcgis-free-import
invariant, ADR-0002) and reusing the shared `qa_report_options` /
`_render_qa(qa, report, fail_on)` contract instead of hand-rolling
`--report`/`--fail-on`. Registered once under the bare name `"photos"` in
both `capabilities.TOOLS` and `capabilities._REGISTRY_SEED` — the same
single-row-for-the-group shape `coc` uses — so `envmon list-tools` and the
registry-parity tests see it.

**Back-compat contract.** `geometry`, `checksum`, `algorithm`, and
`feature_edited_at` are all optional and appended after the manifest's
existing columns; no `SCHEMA_VERSION`-style bump, no migration. Every
reader (`load_photo_records`, `evaluate_photo_qa`, the four emitters) treats
their absence as the normal case, not an error — proven directly by the
Task 7 real-console smoke run against the pre-existing RILEY_PASS harvest
(predates this fill; `envmon photos qa` returns exit 0 with the
`geometry_checks_skipped` INFO instead of failing).

## Out of scope

Per the design spec, deliberately not built in this suite:

- **Duplicate-photo detection.** Checksums now exist to support it; the
  detector/report is future work.
- **Live AGOL re-query to backfill geometry on old harvests.** Re-harvest
  with current AutoGIS instead — it is already the supported path for any
  manifest-shape change.
- **Magnetic-declination correction** of `M`-ref (magnetic) compass
  headings. The reference (`T`/`M`) is recorded uncorrected; correcting it
  needs a geomagnetic model plus a capture date and is left to a future
  consumer.
- **Non-WGS84/Web-Mercator spatial-reference conversion** in the harvester
  fill. Any other SR leaves `geometry` null with a per-layer warning
  (`_rep_point_wgs84` carries a `ponytail:` comment marking this ceiling)
  rather than depending on pyproj for two projections this suite doesn't
  generically need.

## Consequences

### Positive consequences

- One shared EXIF-extraction seam feeds all four emitters instead of four
  duplicated readers.
- The reserved provenance columns from ADR-0012 are finally populated —
  every harvest run from here forward carries geometry and checksums, with
  zero new configuration.
- Photo-vs-feature QA and four spatial/reporting deliverables (CSV,
  GeoJSON, KMZ, log) become available purely from data every harvest
  already collects — no new field-collection burden.
- Every new manifest column is additive and optional, so the change is
  fully back-compatible with every manifest already on disk.

### Negative consequences

- Harvest queries now carry `return_geometry=True`, and every downloaded
  (and skip-existing) file is hashed — extra AGOL payload and local I/O per
  run. Accepted per the design spec; no size cap needed at current
  attachment volumes.
- Geometry conversion covers WGS84 and Web Mercator only (see *Out of
  scope*); a layer in another spatial reference gets a null `geometry`
  silently unless someone reads the per-layer warning.
- `--format docx` on `photos log` adds a new optional dependency surface
  (`report-docx`: `python-docx` + Pillow), though it is fully opt-in and the
  default (`xlsx`) needs nothing beyond the existing `report` extra.
- The harvester-fill leg (`return_geometry=True` payload shape, the
  `editFieldsInfo` EditDate fill) is proven here only against fakes/test
  doubles — a live smoke harvest against a real AGOL layer to confirm the
  wire format is an owner-gated residual, not yet run as of this ADR.

## Alternatives considered

- **Four independent EXIF readers, one per emitter.** Rejected by the
  spec: duplicates the fiddly EXIF-parsing path four times for no benefit.
- **pyproj-based reprojection for the harvester's feature-geometry fill.**
  Rejected: WGS84/Web-Mercator conversion is a closed-form few-liner; pulling
  in pyproj would drag the harvester (already `arcgis`-only, arcpy-free) into
  a heavier dependency for two spatial references it doesn't generically
  need, for a fill whose consumers already treat `geometry` as optional.
- **Declination-correcting `M`-ref compass headings before storage.**
  Rejected: needs a geomagnetic model plus capture date; the raw
  heading + reference is preserved so a future consumer can correct it
  without losing information now.
- **A persisted duplicate-photo report in this suite.** Rejected for now:
  checksums exist to support it, but the detector and its report format are
  undesigned; better as a follow-up once real duplicate data is seen.

## Related decisions

- [ADR-0001: Core-plus-adapters architecture](0001-core-adapters-separation.md)
- [ADR-0002: Arcpy-free core invariant](0002-arcpy-free-core-invariant.md)
- [ADR-0012: Reserved provenance columns for future use](0012-reserved-provenance-columns.md)
- [ADR-0046: GenerateWellInspectionPhotoReport — headless XLSX, Pillow `report` extra](0046-well-inspection-photo-report-headless-xlsx.md)
- [ADR-0083: Report template system](0083-report-template-system.md)
- [ADR-0107: Electronic chain-of-custody lifecycle — the `envmon coc` subgroup idiom this CLI reuses](0107-chain-of-custody-lifecycle.md)
- External: design spec
  [`docs/superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md`](../superpowers/specs/2026-08-12-harvest-photo-metadata-suite-design.md)
