# ADR-0078: OpenTopography DEM download tool + `opentopo` optional extra

**Status:** Accepted

**Date:** 2026-07-10

## Context

Analysts pull site DEMs from OpenTopography by hand (portal, job wait, manual
download, manual add-to-map) — an out-of-band step in an otherwise automated
workflow. The user holds a paid OpenTopography API key. OpenTopography exposes
two single-GET raster endpoints (`/API/globaldem` via `demtype`,
`/API/usgsdem` via `datasetName`) that return a GeoTIFF directly for a WGS84
bbox. Design: `docs/superpowers/specs/2026-07-09-opentopography-dem-download-design.md`;
plan: `docs/superpowers/plans/2026-07-09-opentopography-dem-download-plan.md`.

## Decision

- **Hybrid tool, DEM-rasters-only scope (v1).** One arcpy-free core module
  `autogis/core/envmon/opentopo.py` (stdlib `urllib` only — zero new required
  dependencies), a fully headless CLI command `autogis envmon download-dem`,
  and a `.pyt` tool "Download OpenTopography DEM" that resolves Pro-only AOI
  sources (active map extent / feature layer honoring selection / manual bbox)
  and adds the result to the active map.
- **One dataset registry auto-routes** each code to its endpoint/param; lookup
  is case-insensitive with a difflib "did you mean" suggestion. Default
  dataset `USGS10m`.
- **The core's universal AOI interface is a WGS84 (W, S, E, N) bbox.**
  Headless AOI files: GeoJSON (WGS84 by spec) and shapefile (bbox read from
  the 100-byte `.shp` header via stdlib `struct`; `.prj` reprojected via
  pyproj only when non-WGS84).
- **New optional extra `opentopo = ["pyproj"]`**, lazy-imported inside the
  reprojection helper only (mirrors the `ocr` extra precedent, ADR-0074). The
  module imports and the DEM download works with the extra absent.
- **HTTP fetch behind an injectable `http_get` seam**; all tests are offline.
  HTTP 401/204/400/5xx map to actionable QA errors; downloads stream to a
  `.part` temp file renamed only on success; a provenance/citation `.json`
  sidecar is written after the rename (OpenTopography's terms require dataset
  citation).
- **Area pre-flight is a soft heuristic warn** (single global pixel-count
  threshold), never a hard block — the API's own 400 stays authoritative. No
  per-dataset caps are hardcoded.
- **API key = `$OPENTOPOGRAPHY_API_KEY`** (or a per-run override). No
  QSettings/registry secret storage.

## Consequences

### Positive

- First network-fetching envmon tool; the injectable `http_get` seam keeps
  the suite fully offline (`_default_http_get` is the only network call site).
- Ease-of-use surface ships in v1: dataset auto-routing + difflib suggestion,
  a sane `USGS10m` default, `--dry-run`, `--list-datasets`, an area pre-flight
  warn, an overwrite guard, and a provenance/citation sidecar written next to
  every download.
- Zero new *required* dependencies — `pyproj` is opt-in via `opentopo` and
  only touched for non-WGS84 AOI reprojection, so `core`/`adapters` keep
  importing with the extra absent (arcpy-free invariant, ADR-0002).

### Negative / accepted trade-offs

- Point cloud (LAZ) / `otCatalog` tile-index acquisition, the `/API/v1/elevation`
  service, `--buffer`, response caching, retry/backoff, and batch/tiled
  oversize downloads are explicitly **deferred to a phase 2** (spec: Out of
  scope) — a deliberate future decision reopens them, per CLAUDE.md's
  phase-gate convention for deferred tool groups.
- The `.pyt` tool's AOI-resolution / add-to-map / zoom-to-layer path is
  untestable headless — the same standing exception as every LOCAL/Pro-only
  surface (issues #173, #178). It needs a functional Pro QA pass before it's
  trusted end-to-end.
- The `.pyt` reproject option calls `arcpy.management.ProjectRaster` without
  an explicit `resampling_type`, which defaults to `NEAREST`. For a
  continuous-value DEM `BILINEAR` (or `CUBIC`) is the recommended resampling —
  `NEAREST` is appropriate for categorical rasters, not elevation. This is a
  Pro-QA follow-up, not fixed in this ADR's scope.
- The dataset registry is code, not config; adding a new OpenTopography
  dataset means a one-line registry edit, not a config change.

## Alternatives considered

1. **Point-cloud-first (LAZ via `otCatalog`) scope.** Rejected for v1: the
   two raster GET endpoints are a single HTTP round-trip each and cover the
   analyst's actual DEM-in-a-hurry need; point cloud requires a tile-index
   workflow that is a materially bigger, separable piece of work.
2. **Hard-block large-area requests client-side with per-dataset pixel caps.**
   Rejected: OpenTopography's own limits vary by dataset/tier and change over
   time; hardcoding caps risks blocking valid requests or silently allowing
   invalid ones. A soft warn plus the API's authoritative 400 response is
   simpler and stays correct as limits change.
3. **Store the API key via GUI QSettings, mirroring the `local_python`
   picker (ADR-0062).** Rejected: an API key is a secret, not a path
   preference; `$OPENTOPOGRAPHY_API_KEY` (plus a per-run `--api-key`
   override) avoids persisting a credential to disk.

## Related decisions

- [ADR-0002](0002-arcpy-free-core-invariant.md) — the arcpy-free `core`/
  `adapters` invariant this tool holds even with `pyproj` present.
- [ADR-0074](0074-draft-lithology-from-scan-tool.md) — the lazy-import,
  optional-extra pattern for an opt-in dependency this ADR follows for
  `pyproj`.
- [ADR-0061](0061-drone-geotech-graphics-tool-batch.md) — `matplotlib` as a
  `profile` optional extra; same lazy-import discipline.

## Issues/PRs

- New: `autogis/core/envmon/opentopo.py`, CLI command
  `autogis envmon download-dem` (`autogis/adapters/cli.py`), `.pyt` tool
  `DownloadOpenTopoDEM` (`autogis/adapters/toolbox.pyt`).
- Modified: `pyproject.toml` (new `opentopo` extra),
  `autogis/runtime/capabilities.py` (tool registration).
- Follow-up (not in this branch): Pro-side functional QA of the `.pyt` AOI /
  add-to-map / reproject path; switch `ProjectRaster` to `BILINEAR`
  resampling for the reproject option; phase-2 point-cloud/`otCatalog`
  acquisition.
