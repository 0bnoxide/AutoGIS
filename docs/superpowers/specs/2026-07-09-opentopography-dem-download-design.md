# OpenTopography DEM Download Design

Status: approved (brainstorm 2026-07-09)
Author: agent (session 35413108)
Optional extra: `opentopo` (only for non-WGS84 AOI reprojection)

## Problem

Analysts need site DEMs (bare-earth / surface elevation rasters) pulled from
OpenTopography — the user has a paid OpenTopography subscription (API key). Today
that means the OpenTopography web portal: pan to the AOI, pick a dataset,
submit a job, wait, download the GeoTIFF, then manually add it to ArcGIS Pro.
This is a repetitive, out-of-band step for a workflow that is otherwise
automated in AutoGIS.

Goal: a **hybrid, ease-of-use-first** downloader — one CLI command and one
ArcGIS Pro `.pyt` tool — that turns an AOI plus a dataset choice into a GeoTIFF
on disk (and, in Pro, added to the active map) with a single action.

## Scope

**In scope (v1): DEM rasters only.** OpenTopography exposes two single-GET
raster endpoints that return a GeoTIFF directly:

- `/API/globaldem` — global DEMs by `demtype` (SRTMGL1/GL3, AW3D30, NASADEM,
  COP30/COP90, EU_DTM, SRTM15Plus, GEDTM30, GEBCO*, CA_MRDEM*, ANADEM …).
- `/API/usgsdem` — USGS 3DEP by `datasetName` (`USGS1m`, `USGS10m`, `USGS30m`).

Both take a WGS84 bounding box (`south`/`north`/`west`/`east`), an optional
`outputFormat` (`GTiff` default, `AAIGrid`, `HFA`), and a required `API_Key`.

**Out of scope (deliberate phase 2): point cloud (LAZ).** OpenTopography has no
"bbox → LAZ" endpoint. Raw point clouds are served as per-dataset **tile
indexes** (a shapefile of per-tile download URLs); acquiring one means
discovering the dataset via `/API/otCatalog`, fetching its tile index,
intersecting the AOI, and downloading N individual tile files. That is a
separate subsystem with per-dataset variability. It is explicitly *not* built
here so the high-value DEM path ships small and clean. `otCatalog`/`v1/elevation`
wrappers are likewise deferred.

## Approach

Three layers with clean seams, following the project's established pattern
(arcpy-free core, thin CLI, `.pyt` for the Pro-only surface):

1. **`autogis/core/envmon/opentopo.py`** — arcpy-free, **stdlib `urllib` only**
   (the repo has no `requests` dependency; the DEM download needs zero new
   required deps). Owns the dataset registry, AOI→WGS84-bbox resolution, the
   HTTP GET + stream-to-file, API-key resolution, and QA-mapped error handling.
   The HTTP fetch is behind an injectable seam so tests never touch the network.
2. **CLI** `autogis envmon download-dem` — **fully functional headless** (unlike
   the arcpy-only LOCAL tools that guard-and-redirect, this genuinely works from
   a terminal). Thin wrapper over the core.
3. **`.pyt` tool** "Download OpenTopography DEM" — the only layer that imports
   `arcpy`. Resolves Pro-only AOI sources (active map extent, selected features,
   feature layer) to a WGS84 bbox, calls the same core `download_dem`, then adds
   the raster to the active map.

Ease of use is the driving constraint, expressed concretely as:

- **One `--dataset` param auto-routes** to `/globaldem` vs `/usgsdem`; the user
  never needs to know which endpoint a dataset lives on.
- **Default dataset `USGS10m`** (USGS 3DEP ~10m, seamless US coverage) when
  unspecified — no fallback logic (YAGNI).
- **`--list-datasets`** prints codes + resolution + coverage.
- **Auto-derived output filename** when `--out` is omitted.
- **Actionable errors** for every failure mode.
- **In Pro:** defaults AOI to the current map extent and auto-adds the result.

## Architecture

```
CLI (cli.py: download-dem)          .pyt tool (arcpy: extent/selection AOI + add-to-map)
            \                              /
             \                            /
        autogis/core/envmon/opentopo.py  (arcpy-free, stdlib urllib)
          DEM_DATASETS registry
          resolve_bbox()  ─ bbox | geojson | shapefile(+pyproj)
          resolve_api_key()
          download_dem()  ─ build_url → _http_get (seam) → stream file → QA
```

The Pro-only AOI sources live in the `.pyt` layer, not the core, precisely
because they require `arcpy`. The core's universal interface is a WGS84 bbox;
every caller reduces its AOI to that before calling `download_dem`.

## Public API (`opentopo.py`)

```python
@dataclass(frozen=True)
class DemDataset:
    code: str          # e.g. "USGS10m", "COP30"
    endpoint: str      # "usgsdem" | "globaldem"
    param: str         # "datasetName" | "demtype"
    resolution: str    # human label, e.g. "~10 m (1/3 arc-sec)"
    coverage: str      # "United States" | "Global" | ...

DEM_DATASETS: dict[str, DemDataset]      # code -> dataset (registry)
DEFAULT_DATASET = "USGS10m"

@dataclass
class DownloadResult:
    out_path: Path
    dataset: str
    bbox: tuple[float, float, float, float]  # W, S, E, N (WGS84)
    bytes_written: int
    qa: QACollector

def list_datasets() -> list[DemDataset]: ...

def resolve_api_key(explicit: str | None = None) -> str:
    """explicit arg, else $OPENTOPOGRAPHY_API_KEY, else ValueError with guidance."""

def resolve_bbox(
    bbox: tuple[float, float, float, float] | None = None,
    aoi_path: str | Path | None = None,
) -> tuple[float, float, float, float]:
    """Return a WGS84 (W, S, E, N) bbox from an explicit bbox or an AOI file
    (GeoJSON = WGS84 by spec; shapefile = .shp-header bbox, reprojected from
    .prj via pyproj only when the native CRS is not WGS84)."""

def build_url(dataset: DemDataset, bbox, api_key, output_format="GTiff") -> str: ...

def download_dem(
    dataset: str = DEFAULT_DATASET,
    *,
    bbox=None, aoi_path=None, out_path=None,
    api_key=None, output_format="GTiff",
    http_get=None,          # injectable seam; defaults to urllib-based fetch
) -> DownloadResult: ...
```

## Dataset registry

A single in-module `dict` (code, not user config — no YAML file). Codes and
endpoint/param mapping taken from the live OpenTopography OpenAPI spec
(`/apidocs/openapi.json`, retrieved 2026-07-09). `/usgsdem` uses `datasetName`;
`/globaldem` uses `demtype`. The registry is the auto-routing source of truth
and the backing data for `--list-datasets`. Unknown `--dataset` → error listing
valid codes.

## AOI resolution

| Source | Layer | How → WGS84 bbox |
|---|---|---|
| Explicit `--bbox W S E N` | core | passthrough (documented WGS84) |
| GeoJSON file | core | parse coords; GeoJSON is WGS84 (CRS84) by spec |
| Shapefile | core | read bbox from `.shp` header (stdlib `struct`, offset 36); reproject from `.prj` via **pyproj** only if native CRS ≠ WGS84 |
| Active map extent | `.pyt` | `arcpy` map view extent → project to WGS84 |
| Selected features | `.pyt` | `arcpy` selection extent → project to WGS84 |
| Feature layer | `.pyt` | `arcpy` layer extent → project to WGS84 |

Reading the `.shp` header bbox directly (no fiona/geopandas) keeps the core
dependency-free for the common case. `pyproj` is pulled in **only** for the
non-WGS84 shapefile case in headless mode; when a non-WGS84 AOI is supplied and
pyproj is absent, the error tells the user to install `autogis[opentopo]` or
pass `--bbox` in WGS84.

## CLI command

`autogis envmon download-dem`

| Flag | Meaning |
|---|---|
| `--dataset CODE` | default `USGS10m`; validated against registry |
| `--bbox W S E N` | WGS84 bounding box (mutually exclusive with `--aoi`) |
| `--aoi PATH` | shapefile or GeoJSON AOI |
| `--out PATH` | output GeoTIFF; auto-derived if omitted |
| `--format` | `GTiff` (default) / `AAIGrid` / `HFA` |
| `--api-key` | overrides `$OPENTOPOGRAPHY_API_KEY` |
| `--list-datasets` | print registry and exit |

Emits the standard QA summary. Exit non-zero on error (missing key, empty AOI,
oversized bbox, etc.).

## .pyt tool

Toolbox tool "Download OpenTopography DEM" (in the existing `.pyt`). Parameters:
dataset (dropdown from registry), **AOI source** (Active map extent [default] /
Selected features / Feature layer / Manual bbox), output raster path, "Add to
map" checkbox (default on). Resolves AOI via `arcpy`, calls core `download_dem`,
and on success adds the raster to the active map. The `arcpy` add-to-map step is
isolated behind a small seam so the testable logic stays arcpy-free.

## Dependency scope

- Core DEM download: **stdlib only** (`urllib.request`, `struct`, `json`,
  `pathlib`). No new required dependency.
- `pyproj`: new **optional** extra `opentopo = ["pyproj"]` in `pyproject.toml`,
  soft-imported inside `resolve_bbox`, needed only to reproject a non-WGS84 AOI
  file in headless mode. Mirrors the `ocr` extra precedent (lazy import; module
  stays importable with the extra absent).

## Error handling

`download_dem` maps HTTP status to QA severities with actionable messages:

| Condition | Handling |
|---|---|
| No API key | `ValueError` before any request: "set $OPENTOPOGRAPHY_API_KEY or pass --api-key" |
| 401 Unauthorized | QA error: "OpenTopography rejected the API key" |
| 204 No Content | QA error: "no data for AOI in dataset `<code>` (try a global dataset or check the bbox)" |
| 400 Bad Request | QA error surfacing the API message (commonly bbox too large / invalid); note per-dataset area limits |
| 500 / other | QA error: server-side failure, retry later |
| Non-WGS84 AOI, no pyproj | `RuntimeError` with install guidance |
| Empty/oversized bbox pre-check | optional soft warn before the request |

Partial downloads are written to a temp path and renamed on success so a failed
request never leaves a truncated `.tif`.

## Test strategy (arcpy-free, no network)

- Dataset routing: `USGS10m`→`usgsdem`/`datasetName`; `COP30`→`globaldem`/`demtype`.
- `build_url` query assembly (bbox order, format, key redaction in logs).
- `resolve_api_key`: explicit vs env vs missing (`ValueError`).
- `resolve_bbox`: explicit passthrough; GeoJSON parse; shapefile `.shp`-header
  parse (tiny fixture); pyproj reproject path via `pytest.importorskip("pyproj")`.
- `download_dem` HTTP error mapping via an **injected fake `http_get`**
  returning 200-bytes / 401 / 204 / 400 — asserts QA severities and that a
  truncated file is never left behind.
- Output-filename derivation.
- The `.pyt`/`arcpy` extent-resolution and add-to-map path is untestable
  headless; isolated behind a seam and excluded like other LOCAL-tool surfaces.

## Documentation

- ADR for the tool + the `opentopo` optional extra (next free number — verify
  against open PRs first, per the project's ADR-collision history).
- README tool row and `autogis envmon list-tools` registration.
- CLI `--help` text doubles as usage docs.

## Out of scope / future (phase 2)

- Point cloud (LAZ) acquisition via `otCatalog` + tile-index intersection.
- `/API/otCatalog` dataset discovery and `/v1/elevation` point lookups.
- Batch/tiled downloads for AOIs exceeding a single dataset's area limit.
- Symbology/hillshade styling of the added raster in Pro.
