# OpenTopography DEM Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hybrid OpenTopography DEM downloader — an arcpy-free core
(`opentopo.py`), a fully headless CLI command (`autogis envmon download-dem`),
and a `.pyt` tool ("Download OpenTopography DEM") that resolves Pro-only AOI
sources and adds the result to the active map — per the approved design at
`docs/superpowers/specs/2026-07-09-opentopography-dem-download-design.md`.

**Architecture:** One new arcpy-free module `autogis/core/envmon/opentopo.py`
(stdlib `urllib` only) owning the dataset registry with `/globaldem` vs
`/usgsdem` auto-routing, AOI→WGS84-bbox resolution, API-key resolution, and a
`download_dem` orchestrator whose HTTP fetch sits behind an injectable
`http_get` seam. A thin headless CLI command wraps it. All `arcpy` lives in one
new tool class inside the existing `toolbox.pyt` (the file the test suite never
imports — that file *is* the seam for the untestable Pro surface, matching
every existing LOCAL tool).

**Tech Stack:** Python stdlib (`urllib.request`, `struct`, `json`, `difflib`,
`pathlib`, `os`), existing `QACollector`, Click (already a dependency), and a
new *optional* `pyproj` extra (`opentopo`) lazy-imported only to reproject a
non-WGS84 shapefile AOI headlessly.

## Global Constraints

- **ponytail (full) applies:** reuse `QACollector` / `_render_qa` /
  `qa_report_options` / `_param` / `_msg` as-is; stdlib before deps; no new
  abstractions beyond what the spec names.
- **Zero new required dependencies.** Core DEM download is stdlib-only
  (spec: Dependency scope). `pyproj` is optional: `opentopo = ["pyproj"]` in
  `pyproject.toml`, imported lazily *inside* the reprojection helper, never at
  module level — `opentopo.py` must import with pyproj absent (mirrors the
  `ocr` extra precedent, CLAUDE.md arcpy-free discipline).
- **arcpy-free core and adapters:** `opentopo.py` and `cli.py` never import
  `arcpy`. All arcpy code goes in `toolbox.pyt` only (spec: Approach).
- **Offline, arcpy-free tests:** every `download_dem` test injects a fake
  `http_get`; no test touches the network. pyproj-path tests are gated with
  `pytest.importorskip("pyproj")` (spec: Test strategy).
- **Endpoints (spec: Scope):** `https://portal.opentopography.org/API/globaldem`
  (param `demtype`) and `.../API/usgsdem` (param `datasetName`); both take
  `south`/`north`/`west`/`east` (WGS84), `outputFormat`
  (`GTiff` default | `AAIGrid` | `HFA`), and `API_Key`.
- **`DEFAULT_DATASET = "USGS10m"`**, no fallback logic (spec: Approach).
- **API key:** explicit arg, else `$OPENTOPOGRAPHY_API_KEY`, else `ValueError`
  with guidance. No QSettings/registry secret storage (spec: Dependency scope).
- **Area pre-flight is a heuristic soft WARN, never a hard block** — the API's
  own 400 stays authoritative. No hardcoded per-dataset area caps
  (spec: Error handling).
- **Data-loss guards:** existing `--out` without `--overwrite` refuses *before*
  fetching; downloads stream to a `.part` temp file renamed only on success;
  the provenance `<out>.json` sidecar is written only after the rename
  (spec: Error handling).
- **Out of scope — do not build:** point cloud/LAZ, `otCatalog`,
  `/v1/elevation`, batch/tiled downloads, `--buffer`, caching, retry/backoff,
  QSettings key storage, hillshade symbology (spec: Out of scope).
- **Branch policy:** all work on branch `opentopo-dem-download` in the worktree
  `.claude/worktrees/opentopo-dem-download`. `main` is read-only.
- Run the suite from the worktree root: `python -m pytest -q` (all green before
  each commit; new tests via the per-file commands in each task).

---

## File Structure

```
autogis/
  core/envmon/
    opentopo.py                       ← NEW (Tasks 1-3 build it incrementally)
  adapters/
    cli.py                            ← MODIFY: add download-dem command (Task 4)
    toolbox.pyt                       ← MODIFY: add DownloadOpenTopoDEM tool (Task 5)
  runtime/
    capabilities.py                   ← MODIFY: TOOLS entry + _REGISTRY_SEED row (Task 4)
pyproject.toml                        ← MODIFY: opentopo extra + pyproj in dev (Task 2)
tests/envmon/
  test_opentopo.py                    ← NEW: core module tests (Tasks 1-3)
  test_cli_download_dem.py            ← NEW: CLI wiring tests (Task 4)
docs/adr/
  0076-opentopography-dem-download.md ← NEW (Task 6 — number PROVISIONAL, re-verify)
  README.md                           ← MODIFY: ADR index row (Task 6)
README.md                             ← MODIFY: two tool-table rows + command example (Task 6)
```

The core/CLI test split (`test_opentopo.py` vs `test_cli_download_dem.py`)
mirrors the existing `test_draft_lithology_from_scan.py` /
`test_cli_*` convention in `tests/envmon/`.

**Two deliberate deviations from the spec's illustrative API (flag in the PR):**

1. `DemDataset` gains a numeric `res_m: float` field. The spec's `--dry-run`
   and area pre-flight both require *pixel* estimates, which need a numeric
   resolution; parsing it out of the human `resolution` label would be worse.
2. The `.pyt` AOI-source dropdown collapses the spec's "Selected features" and
   "Feature layer" options into one — "Feature layer (selection if any)" —
   because an `arcpy.da.SearchCursor` over a layer honors its selection
   automatically, so the two options are one code path with identical results.

---

### Task 1: Core module — dataset registry, routing, API key, URL builder, estimators

**Files:**
- Create: `autogis/core/envmon/opentopo.py`
- Test: `tests/envmon/test_opentopo.py`

**Interfaces:**
- Consumes: `QACollector`, `SEV_*` from `autogis.core.common.qa` (existing).
- Produces (Tasks 2-5 import these from this module):
  `DemDataset(code, endpoint, param, resolution, res_m, coverage)`;
  `DEM_DATASETS: dict[str, DemDataset]`; `DEFAULT_DATASET = "USGS10m"`;
  `BASE_URL`; `get_dataset(code: str) -> DemDataset` (raises `ValueError` with
  difflib suggestion); `list_datasets() -> list[DemDataset]`;
  `resolve_api_key(explicit: str | None = None) -> str`;
  `build_url(dataset: DemDataset, bbox, api_key, output_format="GTiff") -> str`;
  `derive_out_name(dataset: DemDataset, bbox, output_format="GTiff") -> str`;
  `estimate_area_km2(bbox) -> float`;
  `estimate_pixels(dataset: DemDataset, bbox) -> int`;
  `PIXEL_WARN_THRESHOLD: int`. All bboxes are `(W, S, E, N)` WGS84 tuples.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_opentopo.py`:

```python
"""Tests for opentopo.py — arcpy-free, offline (no network).

Tasks 2-3 extend this file (resolve_bbox, download_dem). pyproj-gated tests
use pytest.importorskip; everything else runs on stdlib alone.
"""
from urllib.parse import urlsplit, parse_qs

import pytest

from autogis.core.envmon.opentopo import (
    DEM_DATASETS, DEFAULT_DATASET, PIXEL_WARN_THRESHOLD,
    build_url, derive_out_name, estimate_area_km2, estimate_pixels,
    get_dataset, list_datasets, resolve_api_key,
)

BBOX = (-106.30, 39.60, -106.20, 39.70)  # (W, S, E, N), ~0.1 x 0.1 deg


# ---------------------------------------------------------------- registry
def test_default_dataset_registered():
    assert DEFAULT_DATASET == "USGS10m"
    assert DEFAULT_DATASET in DEM_DATASETS


def test_usgs_datasets_route_to_usgsdem():
    ds = get_dataset("USGS10m")
    assert ds.endpoint == "usgsdem"
    assert ds.param == "datasetName"


def test_global_datasets_route_to_globaldem():
    ds = get_dataset("COP30")
    assert ds.endpoint == "globaldem"
    assert ds.param == "demtype"


def test_lookup_is_case_insensitive():
    assert get_dataset("usgs10M").code == "USGS10m"
    assert get_dataset("cop30").code == "COP30"


def test_unknown_dataset_suggests_nearest():
    with pytest.raises(ValueError, match="did you mean"):
        get_dataset("usgs10")
    with pytest.raises(ValueError) as excinfo:
        get_dataset("usgs10")
    assert "USGS10m" in str(excinfo.value)


def test_list_datasets_covers_registry():
    codes = {ds.code for ds in list_datasets()}
    assert codes == set(DEM_DATASETS)


# ---------------------------------------------------------------- build_url
def test_build_url_query_assembly():
    ds = get_dataset("USGS10m")
    url = build_url(ds, BBOX, "SECRETKEY")
    parts = urlsplit(url)
    assert parts.path.endswith("/API/usgsdem")
    query = parse_qs(parts.query)
    assert query["datasetName"] == ["USGS10m"]
    assert query["west"] == ["-106.3"]
    assert query["south"] == ["39.6"]
    assert query["east"] == ["-106.2"]
    assert query["north"] == ["39.7"]
    assert query["outputFormat"] == ["GTiff"]
    assert query["API_Key"] == ["SECRETKEY"]


def test_build_url_globaldem_uses_demtype():
    url = build_url(get_dataset("COP30"), BBOX, "K", output_format="AAIGrid")
    query = parse_qs(urlsplit(url).query)
    assert query["demtype"] == ["COP30"]
    assert query["outputFormat"] == ["AAIGrid"]
    assert urlsplit(url).path.endswith("/API/globaldem")


def test_build_url_with_redacted_key_omits_secret():
    # The redaction pattern the CLI/download log uses: rebuild with "REDACTED".
    url = build_url(get_dataset("USGS10m"), BBOX, "REDACTED")
    assert "SECRETKEY" not in url
    assert "REDACTED" in url


# ---------------------------------------------------------------- api key
def test_resolve_api_key_explicit_wins(monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "from-env")
    assert resolve_api_key("explicit") == "explicit"


def test_resolve_api_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "from-env")
    assert resolve_api_key(None) == "from-env"


def test_resolve_api_key_missing_raises_with_guidance(monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENTOPOGRAPHY_API_KEY"):
        resolve_api_key(None)


# ---------------------------------------------------------------- out name
def test_derive_out_name_encodes_dataset_bbox_and_format():
    name = derive_out_name(get_dataset("USGS10m"), BBOX)
    assert name == "USGS10m_W-106.3000_S39.6000_E-106.2000_N39.7000.tif"
    assert derive_out_name(get_dataset("USGS10m"), BBOX, "AAIGrid").endswith(".asc")
    assert derive_out_name(get_dataset("USGS10m"), BBOX, "HFA").endswith(".img")


# ---------------------------------------------------------------- estimators
def test_estimate_area_km2_matches_geometry():
    # 0.1 x 0.1 deg at ~39.65N: ~11.06 km N-S x ~8.58 km E-W ~= 95 km2.
    area = estimate_area_km2(BBOX)
    assert 80 < area < 110


def test_estimate_pixels_scales_with_resolution():
    px_10m = estimate_pixels(get_dataset("USGS10m"), BBOX)
    px_30m = estimate_pixels(get_dataset("USGS30m"), BBOX)
    assert px_10m == pytest.approx(9 * px_30m, rel=0.01)


def test_pixel_warn_threshold_separates_small_from_huge():
    # A 0.1-deg USGS10m box is fine; a 10-deg USGS1m box must trip the warn.
    assert estimate_pixels(get_dataset("USGS10m"), BBOX) < PIXEL_WARN_THRESHOLD
    huge = (-110.0, 35.0, -100.0, 45.0)
    assert estimate_pixels(get_dataset("USGS1m"), huge) > PIXEL_WARN_THRESHOLD
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'autogis.core.envmon.opentopo'`

- [ ] **Step 3: Write the module**

Create `autogis/core/envmon/opentopo.py`:

```python
"""opentopo.py — OpenTopography DEM downloader (DEM rasters only, v1).

Turns an AOI plus a dataset code into a GeoTIFF on disk via OpenTopography's
two single-GET raster endpoints (/API/globaldem, /API/usgsdem). One dataset
registry auto-routes each code to the right endpoint/param; every AOI form is
reduced to a WGS84 (W, S, E, N) bbox before the request.

Requires an OpenTopography API key: $OPENTOPOGRAPHY_API_KEY or an explicit
argument (the user has a paid subscription; the key is never stored by this
module). Design: docs/superpowers/specs/2026-07-09-opentopography-dem-download-design.md.

Out of scope (phase 2, deliberate): point cloud (LAZ) / otCatalog tile-index
acquisition, /v1/elevation lookups, batch/tiled downloads, caching, retry.

arcpy usage: NONE. This module is arcpy-free and stdlib-only.

Dependency note: `pyproj` is imported lazily inside the shapefile-reprojection
helper, never at module level, so this module stays importable with the
`opentopo` extra absent — it is needed only for a non-WGS84 shapefile AOI
(`pip install autogis[opentopo]`).
"""
from __future__ import annotations

import json
import math
import os
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_INFO, SEV_WARNING

BASE_URL = "https://portal.opentopography.org/API"

# Refuse-nothing heuristic: warn (never block) when the estimated raster
# exceeds ~250M pixels (~1 GB of float32) — big enough that the request is
# probably a mis-drawn AOI or will trip the API's own per-dataset area limit.
# ponytail: single global threshold, not per-dataset caps — the API 400 is
# the authoritative limit and stays the backstop.
PIXEL_WARN_THRESHOLD = 250_000_000

_FORMAT_EXT = {"GTiff": ".tif", "AAIGrid": ".asc", "HFA": ".img"}

# Progress callback: (bytes_written_so_far, total_bytes_or_None) -> None
ProgressFn = Callable[[int, Optional[int]], None]
# http_get seam: url -> (status_code, headers, byte-chunk iterator)
HttpGetFn = Callable[[str], "tuple[int, Mapping[str, str], Iterator[bytes]]"]


@dataclass(frozen=True)
class DemDataset:
    code: str          # e.g. "USGS10m", "COP30"
    endpoint: str      # "usgsdem" | "globaldem"
    param: str         # "datasetName" | "demtype"
    resolution: str    # human label, e.g. "~10 m (1/3 arc-sec)"
    res_m: float       # nominal resolution in meters (pixel estimator)
    coverage: str      # "United States" | "Global" | ...


# Codes + endpoint/param mapping from the live OpenTopography OpenAPI spec
# (/apidocs/openapi.json, retrieved 2026-07-09). /usgsdem takes datasetName;
# /globaldem takes demtype. This registry is the auto-routing source of truth
# and the backing data for --list-datasets.
_DATASETS = [
    DemDataset("USGS1m",  "usgsdem", "datasetName", "~1 m (3DEP lidar)", 1.0,
               "United States (partial 3DEP coverage)"),
    DemDataset("USGS10m", "usgsdem", "datasetName", "~10 m (1/3 arc-sec)", 10.0,
               "United States"),
    DemDataset("USGS30m", "usgsdem", "datasetName", "~30 m (1 arc-sec)", 30.0,
               "United States"),
    DemDataset("SRTMGL1", "globaldem", "demtype", "~30 m (1 arc-sec)", 30.0,
               "Global (60N-56S)"),
    DemDataset("SRTMGL3", "globaldem", "demtype", "~90 m (3 arc-sec)", 90.0,
               "Global (60N-56S)"),
    DemDataset("AW3D30", "globaldem", "demtype", "~30 m (ALOS World 3D)", 30.0,
               "Global"),
    DemDataset("NASADEM", "globaldem", "demtype", "~30 m (SRTM reprocess)", 30.0,
               "Global (60N-56S)"),
    DemDataset("COP30", "globaldem", "demtype", "~30 m (Copernicus GLO-30)", 30.0,
               "Global"),
    DemDataset("COP90", "globaldem", "demtype", "~90 m (Copernicus GLO-90)", 90.0,
               "Global"),
    DemDataset("EU_DTM", "globaldem", "demtype", "~30 m (DTM)", 30.0, "Europe"),
    DemDataset("GEDTM30", "globaldem", "demtype", "~30 m (global DTM)", 30.0,
               "Global"),
    DemDataset("SRTM15Plus", "globaldem", "demtype",
               "~450 m (15 arc-sec, topobathy)", 450.0, "Global"),
    DemDataset("GEBCOIceTopo", "globaldem", "demtype",
               "~450 m (topobathy, ice surface)", 450.0, "Global"),
    DemDataset("GEBCOSubIceTopo", "globaldem", "demtype",
               "~450 m (topobathy, sub-ice)", 450.0, "Global"),
    DemDataset("CA_MRDEM_DSM", "globaldem", "demtype", "~30 m (DSM)", 30.0,
               "Canada"),
    DemDataset("CA_MRDEM_DTM", "globaldem", "demtype", "~30 m (DTM)", 30.0,
               "Canada"),
    DemDataset("ANADEM", "globaldem", "demtype", "~30 m (DTM)", 30.0,
               "South America"),
]

DEM_DATASETS: dict[str, DemDataset] = {ds.code: ds for ds in _DATASETS}
_BY_CASEFOLD: dict[str, DemDataset] = {ds.code.casefold(): ds for ds in _DATASETS}
DEFAULT_DATASET = "USGS10m"

# OpenTopography's terms require citing the dataset used. The dataset-specific
# citation/DOI lives on each dataset's OpenTopography page; the sidecar points
# there and names the dataset so the analyst can cite precisely.
CITATION = (
    "DEM downloaded via OpenTopography (https://opentopography.org). "
    "OpenTopography's terms of use require citing the source dataset; see "
    "https://portal.opentopography.org/datasets for this dataset's "
    "citation/DOI."
)


@dataclass
class DownloadResult:
    out_path: Path
    dataset: str
    bbox: tuple[float, float, float, float]  # (W, S, E, N) WGS84
    bytes_written: int
    qa: QACollector


def list_datasets() -> list[DemDataset]:
    """Registry entries in declaration order (US datasets first)."""
    return list(_DATASETS)


def get_dataset(code: str) -> DemDataset:
    """Case-insensitive registry lookup; unknown codes get a difflib
    "did you mean" suggestion plus the full valid list."""
    key = (code or "").strip()
    hit = _BY_CASEFOLD.get(key.casefold())
    if hit is not None:
        return hit
    import difflib
    close = difflib.get_close_matches(key.casefold(), list(_BY_CASEFOLD),
                                      n=1, cutoff=0.6)
    hint = (f"; did you mean {_BY_CASEFOLD[close[0]].code!r}?" if close else "")
    raise ValueError(
        f"unknown dataset {code!r}{hint} "
        f"(valid: {', '.join(sorted(DEM_DATASETS))})")


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """Explicit arg, else $OPENTOPOGRAPHY_API_KEY, else ValueError."""
    key = (explicit or "").strip() or \
        os.environ.get("OPENTOPOGRAPHY_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "no OpenTopography API key: set $OPENTOPOGRAPHY_API_KEY "
            "or pass --api-key")
    return key


def build_url(dataset: DemDataset,
              bbox: tuple[float, float, float, float],
              api_key: str,
              output_format: str = "GTiff") -> str:
    """Assemble the endpoint URL. Pass api_key="REDACTED" for loggable URLs."""
    from urllib.parse import urlencode
    west, south, east, north = bbox
    params = {
        dataset.param: dataset.code,
        "south": south, "north": north, "west": west, "east": east,
        "outputFormat": output_format,
        "API_Key": api_key,
    }
    return f"{BASE_URL}/{dataset.endpoint}?{urlencode(params)}"


def derive_out_name(dataset: DemDataset,
                    bbox: tuple[float, float, float, float],
                    output_format: str = "GTiff") -> str:
    west, south, east, north = bbox
    ext = _FORMAT_EXT[output_format]
    return (f"{dataset.code}_W{west:.4f}_S{south:.4f}"
            f"_E{east:.4f}_N{north:.4f}{ext}")


def estimate_area_km2(bbox: tuple[float, float, float, float]) -> float:
    """Spherical-degree approximation — feeds --dry-run and the pre-flight
    warn only; never used as a hard gate."""
    west, south, east, north = bbox
    mid_lat = math.radians((south + north) / 2.0)
    width_km = abs(east - west) * 111.32 * math.cos(mid_lat)
    height_km = abs(north - south) * 110.57
    return width_km * height_km


def estimate_pixels(dataset: DemDataset,
                    bbox: tuple[float, float, float, float]) -> int:
    area_m2 = estimate_area_km2(bbox) * 1_000_000.0
    return int(area_m2 / (dataset.res_m ** 2))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: all PASS. Then confirm the module imports clean without pyproj/arcpy:
`python -c "from autogis.core.envmon import opentopo; print(len(opentopo.DEM_DATASETS), 'datasets')"`
Expected: `17 datasets`.

- [ ] **Step 5: Implementation-time verification of registry codes**

Fetch `https://portal.opentopography.org/apidocs/openapi.json` (one manual
check, e.g. `curl -s https://portal.opentopography.org/apidocs/openapi.json`)
and confirm every `demtype`/`datasetName` enum value in `_DATASETS` matches the
live spec exactly (case included — the API values are case-sensitive server-side
even though *our lookup* is forgiving). Fix any drifted code before committing.
If the endpoint is unreachable from this environment, keep the registry as
written (it was read from the same spec on 2026-07-09) and note that in the
commit body.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/opentopo.py tests/envmon/test_opentopo.py
git commit -m "feat(envmon): OpenTopography dataset registry + URL builder (opentopo core, part 1)"
```

---

### Task 2: AOI resolution (`resolve_bbox`) + `opentopo` optional extra

**Files:**
- Modify: `autogis/core/envmon/opentopo.py` (append after `estimate_pixels`)
- Modify: `pyproject.toml` (`[project.optional-dependencies]`)
- Test: `tests/envmon/test_opentopo.py` (append)

**Interfaces:**
- Consumes: nothing new from Task 1 (independent functions in the same module).
- Produces: `resolve_bbox(bbox=None, aoi_path=None) -> tuple[float, float, float, float]`
  — WGS84 `(W, S, E, N)`; raises `ValueError` on bad/missing/ambiguous input,
  `RuntimeError` (with `autogis[opentopo]` guidance) when a non-WGS84 shapefile
  needs pyproj and it is absent. Task 3's `download_dem` and Task 4's CLI call it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_opentopo.py`:

```python
# ---------------------------------------------------------------- resolve_bbox
import json as _json
import struct as _struct
import sys

from autogis.core.envmon.opentopo import resolve_bbox

WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",'
    '6378137.0,298.257223563]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)
UTM13N_PRJ = (
    'PROJCS["NAD_1983_UTM_Zone_13N",GEOGCS["GCS_North_American_1983",'
    'DATUM["D_North_American_1983",SPHEROID["GRS_1980",6378137.0,'
    '298.257222101]],PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],'
    'PARAMETER["False_Easting",500000.0],'
    'PARAMETER["False_Northing",0.0],'
    'PARAMETER["Central_Meridian",-105.0],'
    'PARAMETER["Scale_Factor",0.9996],'
    'PARAMETER["Latitude_Of_Origin",0.0],UNIT["Meter",1.0]]'
)


def _write_shp(shp_path, bbox, prj_text=None):
    """Minimal valid 100-byte .shp header (ESRI spec): big-endian file code
    9994 at byte 0, little-endian version/shape-type at 28/32, bbox doubles
    at 36. No records needed — resolve_bbox reads the header only."""
    west, south, east, north = bbox
    header = _struct.pack(">i", 9994) + b"\x00" * 20 + _struct.pack(">i", 50)
    header += _struct.pack("<ii", 1000, 5)                    # version, polygon
    header += _struct.pack("<4d", west, south, east, north)   # bbox at offset 36
    header += _struct.pack("<4d", 0.0, 0.0, 0.0, 0.0)         # zmin/zmax/mmin/mmax
    shp_path.write_bytes(header)
    if prj_text is not None:
        shp_path.with_suffix(".prj").write_text(prj_text, encoding="utf-8")


def test_resolve_bbox_explicit_passthrough():
    assert resolve_bbox(bbox=BBOX) == BBOX


def test_resolve_bbox_rejects_both_and_neither(tmp_path):
    geojson = tmp_path / "aoi.geojson"
    geojson.write_text('{"type":"Point","coordinates":[-106.25,39.65]}')
    with pytest.raises(ValueError, match="not both"):
        resolve_bbox(bbox=BBOX, aoi_path=geojson)
    with pytest.raises(ValueError, match="bbox or an AOI"):
        resolve_bbox()


def test_resolve_bbox_rejects_invalid_wgs84_box():
    with pytest.raises(ValueError, match="not a valid WGS84"):
        resolve_bbox(bbox=(-106.20, 39.60, -106.30, 39.70))   # W > E
    with pytest.raises(ValueError, match="not a valid WGS84"):
        resolve_bbox(bbox=(400000.0, 4400000.0, 410000.0, 4410000.0))  # meters


def test_resolve_bbox_geojson_feature_collection(tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(_json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-106.30, 39.60], [-106.20, 39.60], [-106.20, 39.70],
                [-106.30, 39.70], [-106.30, 39.60]]]},
        }],
    }))
    assert resolve_bbox(aoi_path=aoi) == pytest.approx(BBOX)


def test_resolve_bbox_geojson_without_coordinates_raises(tmp_path):
    aoi = tmp_path / "empty.geojson"
    aoi.write_text('{"type": "FeatureCollection", "features": []}')
    with pytest.raises(ValueError, match="no coordinates"):
        resolve_bbox(aoi_path=aoi)


def test_resolve_bbox_shapefile_header_wgs84(tmp_path):
    shp = tmp_path / "aoi.shp"
    _write_shp(shp, BBOX, prj_text=WGS84_PRJ)
    assert resolve_bbox(aoi_path=shp) == pytest.approx(BBOX)


def test_resolve_bbox_shapefile_missing_prj_assumed_wgs84(tmp_path):
    shp = tmp_path / "noprj.shp"
    _write_shp(shp, BBOX, prj_text=None)
    assert resolve_bbox(aoi_path=shp) == pytest.approx(BBOX)


def test_resolve_bbox_rejects_non_shapefile(tmp_path):
    bogus = tmp_path / "bogus.shp"
    bogus.write_bytes(b"not a shapefile at all, way too short")
    with pytest.raises(ValueError, match="not a shapefile"):
        resolve_bbox(aoi_path=bogus)


def test_resolve_bbox_rejects_unknown_extension(tmp_path):
    other = tmp_path / "aoi.gpkg"
    other.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="shapefile or GeoJSON"):
        resolve_bbox(aoi_path=other)


def test_resolve_bbox_non_wgs84_without_pyproj_raises_guidance(tmp_path, monkeypatch):
    shp = tmp_path / "utm.shp"
    _write_shp(shp, (400000.0, 4400000.0, 410000.0, 4410000.0),
               prj_text=UTM13N_PRJ)
    monkeypatch.setitem(sys.modules, "pyproj", None)  # force ImportError
    with pytest.raises(RuntimeError, match=r"autogis\[opentopo\]"):
        resolve_bbox(aoi_path=shp)


def test_resolve_bbox_reprojects_utm_shapefile(tmp_path):
    pytest.importorskip("pyproj")
    shp = tmp_path / "utm.shp"
    _write_shp(shp, (400000.0, 4400000.0, 410000.0, 4410000.0),
               prj_text=UTM13N_PRJ)
    west, south, east, north = resolve_bbox(aoi_path=shp)
    assert -107.0 < west < east < -105.0
    assert 39.0 < south < north < 40.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: the new tests FAIL with `ImportError: cannot import name 'resolve_bbox'`; Task 1 tests still PASS.

- [ ] **Step 3: Implement `resolve_bbox`**

Append to `autogis/core/envmon/opentopo.py`:

```python
# ---------------------------------------------------------------- AOI -> bbox
def _validate_wgs84_bbox(bbox: tuple[float, float, float, float],
                         source: str) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    if not (-180.0 <= west < east <= 180.0 and -90.0 <= south < north <= 90.0):
        raise ValueError(
            f"{source}: (W={west}, S={south}, E={east}, N={north}) is not a "
            f"valid WGS84 bbox — expected W < E in [-180, 180] and S < N in "
            f"[-90, 90] decimal degrees; check coordinate order and CRS "
            f"(an empty/degenerate AOI also fails this check)")
    return (float(west), float(south), float(east), float(north))


def _geojson_bounds(obj) -> tuple[float, float, float, float]:
    """Bounds of any GeoJSON object (GeoJSON is WGS84/CRS84 by spec)."""
    lons: list[float] = []
    lats: list[float] = []

    def collect(coords) -> None:
        if isinstance(coords, (list, tuple)):
            if (len(coords) >= 2
                    and isinstance(coords[0], (int, float))
                    and isinstance(coords[1], (int, float))):
                lons.append(float(coords[0]))
                lats.append(float(coords[1]))
            else:
                for item in coords:
                    collect(item)

    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        if node.get("coordinates") is not None:
            collect(node["coordinates"])
        if isinstance(node.get("geometry"), dict):
            walk(node["geometry"])
        for key in ("features", "geometries"):
            for child in node.get(key) or []:
                walk(child)

    walk(obj)
    if not lons:
        raise ValueError("AOI GeoJSON contains no coordinates (empty AOI)")
    return (min(lons), min(lats), max(lons), max(lats))


def _read_shp_header_bbox(path: Path) -> tuple[float, float, float, float]:
    """Native-CRS bbox straight from the 100-byte .shp header (ESRI spec:
    file code 9994 big-endian at byte 0; xmin/ymin/xmax/ymax little-endian
    doubles at byte 36). No fiona/geopandas needed."""
    header = path.read_bytes()[:100]
    if len(header) < 68 or struct.unpack(">i", header[:4])[0] != 9994:
        raise ValueError(f"{path} is not a shapefile (bad .shp header)")
    xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
    return (xmin, ymin, xmax, ymax)


def _prj_is_wgs84(prj_text: str) -> bool:
    head = prj_text.strip().upper()
    return (head.startswith(("GEOGCS", "GEOGCRS"))
            and ("WGS_1984" in head or "WGS 84" in head or "WGS84" in head))


def _reproject_bbox_to_wgs84(
        native_bbox: tuple[float, float, float, float],
        prj_text: str,
        source: str) -> tuple[float, float, float, float]:
    try:
        from pyproj import CRS, Transformer
    except ImportError:
        raise RuntimeError(
            f"{source}: AOI shapefile is not WGS84 and reprojection needs "
            f"pyproj — install it with `pip install autogis[opentopo]`, or "
            f"pass --bbox W S E N in WGS84 instead") from None
    crs = CRS.from_wkt(prj_text)
    if crs.to_epsg() == 4326:
        return native_bbox
    transformer = Transformer.from_crs(crs, CRS.from_epsg(4326),
                                       always_xy=True)
    xmin, ymin, xmax, ymax = native_bbox
    xs = (xmin, (xmin + xmax) / 2.0, xmax)
    ys = (ymin, (ymin + ymax) / 2.0, ymax)
    # ponytail: 9-point (corners + edge midpoints) envelope, not true edge
    # densification — fine at AOI scale; densify if a polar/oblique CRS shows up.
    points = [transformer.transform(x, y) for x in xs for y in ys]
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons), min(lats), max(lons), max(lats))


def resolve_bbox(
    bbox: Optional[tuple[float, float, float, float]] = None,
    aoi_path: "str | Path | None" = None,
) -> tuple[float, float, float, float]:
    """Return a validated WGS84 (W, S, E, N) bbox from an explicit bbox or an
    AOI file (GeoJSON = WGS84 by spec; shapefile = .shp-header bbox,
    reprojected from .prj via pyproj only when the native CRS is not WGS84;
    a missing .prj is assumed WGS84)."""
    if bbox is not None and aoi_path is not None:
        raise ValueError("pass an explicit bbox or an AOI file, not both")
    if bbox is not None:
        return _validate_wgs84_bbox(tuple(bbox), "--bbox")
    if aoi_path is None:
        raise ValueError("an AOI is required: pass a bbox or an AOI file path")

    path = Path(aoi_path)
    suffix = path.suffix.lower()
    if suffix in (".geojson", ".json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        return _validate_wgs84_bbox(_geojson_bounds(obj), str(path))
    if suffix == ".shp":
        native = _read_shp_header_bbox(path)
        prj = path.with_suffix(".prj")
        if prj.exists():
            prj_text = prj.read_text(encoding="utf-8")
            if not _prj_is_wgs84(prj_text):
                native = _reproject_bbox_to_wgs84(native, prj_text, str(path))
        return _validate_wgs84_bbox(native, str(path))
    raise ValueError(
        f"unsupported AOI file {path.name!r}: expected a shapefile (.shp) "
        f"or GeoJSON (.geojson/.json)")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: all PASS (the UTM-reprojection test SKIPS if pyproj is absent).

- [ ] **Step 5: Add the `opentopo` extra (and pyproj to `dev` so the gated test runs)**

In `pyproject.toml`, `[project.optional-dependencies]`:

- Change the `dev` line to:
  `dev = ["pytest", "Pillow>=9.0", "matplotlib>=3.7", "pyproj"]   # Pillow/matplotlib/pyproj so the importorskip-gated tests actually run`
- Append after the `ocr` line:
  `opentopo = ["pyproj"]   # non-WGS84 AOI reprojection for envmon download-dem (lazy import; stdlib urllib covers the download itself)`

Verify: `python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); print(d['project']['optional-dependencies']['opentopo'])"`
Expected: `['pyproj']`

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/opentopo.py tests/envmon/test_opentopo.py pyproject.toml
git commit -m "feat(envmon): AOI-to-WGS84 bbox resolution + opentopo pyproj extra (opentopo core, part 2)"
```

---

### Task 3: `download_dem` — http_get seam, error mapping, temp-rename, provenance sidecar

**Files:**
- Modify: `autogis/core/envmon/opentopo.py` (append)
- Test: `tests/envmon/test_opentopo.py` (append)

**Interfaces:**
- Consumes (Task 1/2, same module): `get_dataset`, `resolve_bbox`,
  `resolve_api_key`, `build_url`, `derive_out_name`, `estimate_area_km2`,
  `estimate_pixels`, `PIXEL_WARN_THRESHOLD`, `DownloadResult`, `CITATION`.
- Produces (Task 4 CLI and Task 5 .pyt call this):
  `download_dem(dataset=DEFAULT_DATASET, *, bbox=None, aoi_path=None,
  out_path=None, api_key=None, output_format="GTiff", overwrite=False,
  http_get=None, on_progress=None) -> DownloadResult`. Raises
  `ValueError` (bad dataset/AOI/key), `FileExistsError` (overwrite guard);
  HTTP failures are QA `SEV_ERROR` records with `bytes_written == 0`, never
  exceptions. Also `_default_http_get(url)` (the seam's default, monkeypatch
  target for CLI tests).

- [ ] **Step 1: Write the failing tests**

Append to `tests/envmon/test_opentopo.py`:

```python
# ---------------------------------------------------------------- download_dem
from autogis.core.envmon.opentopo import download_dem


def fake_get(status, body=b"", headers=None, calls=None):
    """Injectable http_get: records calls, returns a canned response."""
    def _get(url):
        if calls is not None:
            calls.append(url)
        base = {"Content-Length": str(len(body))} if status == 200 else {}
        base.update(headers or {})
        return status, base, iter([body[:10], body[10:]] if len(body) > 10
                                  else [body])
    return _get


@pytest.fixture
def api_key_env(monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", "TESTKEY")


def test_download_success_writes_file_and_sidecar(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"
    body = b"GEOTIFFBYTES" * 4
    result = download_dem("USGS10m", bbox=BBOX, out_path=out,
                          http_get=fake_get(200, body))
    assert out.read_bytes() == body
    assert result.bytes_written == len(body)
    assert result.dataset == "USGS10m"
    assert not list(tmp_path.glob("*.part")), "temp file must not remain"
    sidecar = _json.loads((tmp_path / "dem.tif.json").read_text())
    assert sidecar["dataset"] == "USGS10m"
    assert sidecar["bbox_wgs84"] == {"west": BBOX[0], "south": BBOX[1],
                                     "east": BBOX[2], "north": BBOX[3]}
    assert "TESTKEY" not in sidecar["source_url"]
    assert "REDACTED" in sidecar["source_url"]
    assert "opentopography" in sidecar["citation"].lower()
    assert sidecar["downloaded_utc"]  # ISO timestamp present


def test_download_url_uses_key_and_routing(tmp_path, api_key_env):
    calls = []
    download_dem("COP30", bbox=BBOX, out_path=tmp_path / "d.tif",
                 http_get=fake_get(200, b"x", calls=calls))
    assert "/API/globaldem?" in calls[0]
    assert "demtype=COP30" in calls[0]
    assert "API_Key=TESTKEY" in calls[0]


@pytest.mark.parametrize("status,category,needle", [
    (401, "unauthorized", "rejected the API key"),
    (204, "no_data", "no data for this AOI"),
    (400, "bad_request", "area limit"),
    (500, "server_error", "retry later"),
])
def test_download_http_errors_map_to_qa(tmp_path, api_key_env,
                                        status, category, needle):
    out = tmp_path / "dem.tif"
    result = download_dem("USGS10m", bbox=BBOX, out_path=out,
                          http_get=fake_get(status, b"API detail message"))
    assert result.bytes_written == 0
    assert not out.exists()
    assert not list(tmp_path.glob("*.part"))
    errors = [r for r in result.qa.records if r.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == category
    assert needle in errors[0].message


def test_download_400_surfaces_api_body(tmp_path, api_key_env):
    result = download_dem("USGS10m", bbox=BBOX, out_path=tmp_path / "d.tif",
                          http_get=fake_get(400, b"bbox exceeds max area"))
    (error,) = [r for r in result.qa.records if r.severity == "ERROR"]
    assert "bbox exceeds max area" in error.message


def test_overwrite_guard_refuses_before_fetch(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"
    out.write_bytes(b"existing data")

    def must_not_fetch(url):
        raise AssertionError("http_get called despite overwrite guard")

    with pytest.raises(FileExistsError, match="--overwrite"):
        download_dem("USGS10m", bbox=BBOX, out_path=out,
                     http_get=must_not_fetch)
    assert out.read_bytes() == b"existing data"


def test_overwrite_flag_replaces_existing(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"
    out.write_bytes(b"old")
    result = download_dem("USGS10m", bbox=BBOX, out_path=out, overwrite=True,
                          http_get=fake_get(200, b"new bytes"))
    assert out.read_bytes() == b"new bytes"
    assert result.bytes_written == len(b"new bytes")


def test_auto_out_name_when_out_path_omitted(tmp_path, api_key_env, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = download_dem("USGS10m", bbox=BBOX, http_get=fake_get(200, b"x"))
    assert result.out_path.name == \
        "USGS10m_W-106.3000_S39.6000_E-106.2000_N39.7000.tif"
    assert result.out_path.exists()


def test_failed_stream_leaves_no_partial_file(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"

    def broken_stream(url):
        def chunks():
            yield b"first chunk"
            raise IOError("connection dropped")
        return 200, {"Content-Length": "9999"}, chunks()

    with pytest.raises(IOError):
        download_dem("USGS10m", bbox=BBOX, out_path=out,
                     http_get=broken_stream)
    assert not out.exists()
    assert not list(tmp_path.glob("*.part")), "truncated temp must be removed"
    assert not (tmp_path / "dem.tif.json").exists(), "no sidecar on failure"


def test_progress_callback_sees_bytes_and_total(tmp_path, api_key_env):
    seen = []
    body = b"0123456789ABCDEF"  # split into 2 chunks by fake_get
    download_dem("USGS10m", bbox=BBOX, out_path=tmp_path / "d.tif",
                 http_get=fake_get(200, body),
                 on_progress=lambda done, total: seen.append((done, total)))
    assert seen[-1] == (len(body), len(body))
    assert [done for done, _ in seen] == sorted(done for done, _ in seen)


def test_large_aoi_preflight_warns(tmp_path, api_key_env):
    huge = (-110.0, 35.0, -100.0, 45.0)
    result = download_dem("USGS1m", bbox=huge, out_path=tmp_path / "d.tif",
                          http_get=fake_get(200, b"x"))
    warns = [r for r in result.qa.records
             if r.severity == "WARNING" and r.category == "large_aoi"]
    assert len(warns) == 1, "heuristic warn must fire, but never block"
    assert result.bytes_written > 0, "warn is soft — download still ran"


def test_small_aoi_no_preflight_warn(tmp_path, api_key_env):
    result = download_dem("USGS10m", bbox=BBOX, out_path=tmp_path / "d.tif",
                          http_get=fake_get(200, b"x"))
    assert not [r for r in result.qa.records if r.category == "large_aoi"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: new tests FAIL with `ImportError: cannot import name 'download_dem'`.

- [ ] **Step 3: Implement `download_dem`**

Append to `autogis/core/envmon/opentopo.py`:

```python
# ---------------------------------------------------------------- download
def _default_http_get(url: str):
    """The real fetch behind the injectable seam.

    Returns (status_code, headers, chunk_iterator). urllib raises HTTPError
    for 4xx/5xx; normalize that to the same tuple shape so download_dem has
    one code path. OpenTopography DEM jobs can take a while server-side —
    generous timeout."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "autogis"})
    try:
        response = urllib.request.urlopen(request, timeout=600)
    except urllib.error.HTTPError as err:
        body = err.read() or b""
        return err.code, dict(err.headers or {}), iter([body])

    def chunks(resp=response):
        with resp:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    return
                yield chunk

    return response.status, dict(response.headers), chunks()


def _map_http_error(qa: QACollector, status: int, dataset: DemDataset,
                    chunks: Iterator[bytes]) -> None:
    if status == 401:
        qa.add(SEV_ERROR, "unauthorized",
               "OpenTopography rejected the API key (401) — check "
               "$OPENTOPOGRAPHY_API_KEY / --api-key")
    elif status == 204:
        qa.add(SEV_ERROR, "no_data",
               f"no data for this AOI in dataset {dataset.code!r} (204) — "
               f"try a global dataset or check the bbox")
    elif status == 400:
        detail = b"".join(chunks)[:500].decode("utf-8", "replace").strip()
        qa.add(SEV_ERROR, "bad_request",
               f"OpenTopography rejected the request (400): "
               f"{detail or 'no detail'} — commonly the bbox exceeds the "
               f"dataset's area limit; shrink the AOI or use a coarser dataset")
    else:
        qa.add(SEV_ERROR, "server_error",
               f"OpenTopography returned HTTP {status} — server-side "
               f"failure, retry later")


def _write_sidecar(out_path: Path, dataset: DemDataset,
                   bbox: tuple[float, float, float, float],
                   redacted_url: str) -> Path:
    """Provenance + citation sidecar (<out>.json). Written only after the
    downloaded raster has been renamed into place."""
    west, south, east, north = bbox
    sidecar = out_path.with_name(out_path.name + ".json")
    sidecar.write_text(json.dumps({
        "dataset": dataset.code,
        "endpoint": dataset.endpoint,
        "resolution": dataset.resolution,
        "bbox_wgs84": {"west": west, "south": south,
                       "east": east, "north": north},
        "downloaded_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": redacted_url,
        "citation": CITATION,
    }, indent=2), encoding="utf-8")
    return sidecar


def download_dem(
    dataset: str = DEFAULT_DATASET,
    *,
    bbox: Optional[tuple[float, float, float, float]] = None,
    aoi_path: "str | Path | None" = None,
    out_path: "str | Path | None" = None,
    api_key: Optional[str] = None,
    output_format: str = "GTiff",
    overwrite: bool = False,
    http_get: Optional[HttpGetFn] = None,
    on_progress: Optional[ProgressFn] = None,
) -> DownloadResult:
    """Resolve dataset/AOI/key, fetch the DEM, stream to a temp file, rename
    on success, write the provenance sidecar. HTTP failures become QA errors
    (bytes_written == 0); input problems raise before any request is made."""
    qa = QACollector()
    ds = get_dataset(dataset)
    box = resolve_bbox(bbox=bbox, aoi_path=aoi_path)
    key = resolve_api_key(api_key)
    out = Path(out_path) if out_path else Path(derive_out_name(
        ds, box, output_format))
    if out.exists() and not overwrite:
        raise FileExistsError(
            f"{out} already exists; pass --overwrite to replace it")

    estimated_px = estimate_pixels(ds, box)
    if estimated_px > PIXEL_WARN_THRESHOLD:
        qa.add(SEV_WARNING, "large_aoi",
               f"AOI is ~{estimate_area_km2(box):,.0f} km2 "
               f"(~{estimated_px:,} px at {ds.res_m:g} m) — this may exceed "
               f"the dataset's area limit; proceeding (the API will reject "
               f"with 400 if so)")

    url = build_url(ds, box, key, output_format)
    fetch = http_get or _default_http_get
    status, headers, chunks = fetch(url)
    if status != 200:
        _map_http_error(qa, status, ds, chunks)
        return DownloadResult(out_path=out, dataset=ds.code, bbox=box,
                              bytes_written=0, qa=qa)

    total = int(headers.get("Content-Length") or 0) or None
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    written = 0
    try:
        with part.open("wb") as fh:
            for chunk in chunks:
                fh.write(chunk)
                written += len(chunk)
                if on_progress is not None:
                    on_progress(written, total)
    except BaseException:
        part.unlink(missing_ok=True)   # never leave a truncated raster
        raise
    os.replace(part, out)
    sidecar = _write_sidecar(out, ds, box,
                             build_url(ds, box, "REDACTED", output_format))
    qa.add(SEV_INFO, "download_dem",
           f"wrote {out} ({written:,} bytes, dataset {ds.code}); "
           f"provenance sidecar {sidecar.name}")
    return DownloadResult(out_path=out, dataset=ds.code, bbox=box,
                          bytes_written=written, qa=qa)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/envmon/test_opentopo.py -q`
Expected: all PASS. Then run the full suite: `python -m pytest -q` — no regressions.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/opentopo.py tests/envmon/test_opentopo.py
git commit -m "feat(envmon): download_dem with injectable http_get, QA error mapping, provenance sidecar (opentopo core, part 3)"
```

---

### Task 4: CLI `autogis envmon download-dem` + tool-registry registration

**Files:**
- Modify: `autogis/adapters/cli.py` (insert the new command directly after
  `draft_lithology_from_scan_cmd`, before `survey_to_well_elevation_cmd`)
- Modify: `autogis/runtime/capabilities.py` (`TOOLS` dict + `_REGISTRY_SEED`)
- Test: `tests/envmon/test_cli_download_dem.py`

**Interfaces:**
- Consumes: `autogis.core.envmon.opentopo` (Tasks 1-3: `get_dataset`,
  `resolve_bbox`, `build_url`, `estimate_area_km2`, `estimate_pixels`,
  `list_datasets`, `download_dem`, `_default_http_get` as monkeypatch target);
  existing `qa_report_options` decorator and `_render_qa(qa, report, fail_on)`
  helper in `cli.py`; the `envmon` click group; `Runtime`/`ToolCapability` in
  `capabilities.py`.
- Produces: CLI command `download-dem` (headless — **no** `_guard()` call,
  same class as `validate-boring-logs`); registry entries so
  `autogis envmon list-tools` shows it.

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_cli_download_dem.py`:

```python
"""CLI wiring tests for `autogis envmon download-dem` — offline, arcpy-free.

The download path is exercised by monkeypatching the core module's
_default_http_get seam; no test touches the network.
"""
import json

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as cli_root


@pytest.fixture
def runner():
    return CliRunner()


def _invoke(runner, args, env=None):
    return runner.invoke(cli_root, ["envmon", "download-dem"] + args,
                         env=env, catch_exceptions=False)


def test_list_datasets_prints_registry_and_exits(runner):
    result = _invoke(runner, ["--list-datasets"])
    assert result.exit_code == 0
    assert "USGS10m" in result.output
    assert "usgsdem" in result.output
    assert "COP30" in result.output
    assert "globaldem" in result.output


def test_bbox_and_aoi_are_mutually_exclusive(runner, tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"Point","coordinates":[-106.25,39.65]}')
    result = runner.invoke(cli_root, [
        "envmon", "download-dem",
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--aoi", str(aoi)])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_missing_aoi_and_bbox_is_a_usage_error(runner):
    result = runner.invoke(cli_root, ["envmon", "download-dem"])
    assert result.exit_code != 0
    assert "--bbox" in result.output and "--aoi" in result.output


def test_unknown_dataset_suggests_nearest(runner):
    result = runner.invoke(cli_root, [
        "envmon", "download-dem", "--dataset", "usgs10",
        "--bbox", "-106.3", "39.6", "-106.2", "39.7"])
    assert result.exit_code != 0
    assert "did you mean" in result.output


def test_dry_run_needs_no_api_key_and_redacts(runner, monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--dry-run"])
    assert result.exit_code == 0
    assert "usgsdem" in result.output          # routing shown
    assert "REDACTED" in result.output         # redacted URL
    assert "km2" in result.output              # area estimate
    assert "dry run" in result.output.lower()


def test_download_writes_file_via_seam(runner, tmp_path, monkeypatch):
    from autogis.core.envmon import opentopo

    def fake_default_get(url):
        body = b"GEOTIFF"
        return 200, {"Content-Length": str(len(body))}, iter([body])

    monkeypatch.setattr(opentopo, "_default_http_get", fake_default_get)
    out = tmp_path / "site_dem.tif"
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--out", str(out)],
        env={"OPENTOPOGRAPHY_API_KEY": "TESTKEY"})
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == b"GEOTIFF"
    assert (tmp_path / "site_dem.tif.json").exists()
    assert "Wrote" in result.output


def test_existing_out_without_overwrite_fails_cleanly(runner, tmp_path):
    out = tmp_path / "dem.tif"
    out.write_bytes(b"precious")
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7", "--out", str(out)],
        env={"OPENTOPOGRAPHY_API_KEY": "TESTKEY"})
    assert result.exit_code != 0
    assert "--overwrite" in result.output
    assert out.read_bytes() == b"precious"


def test_http_error_exits_nonzero_with_qa(runner, tmp_path, monkeypatch):
    from autogis.core.envmon import opentopo

    monkeypatch.setattr(opentopo, "_default_http_get",
                        lambda url: (401, {}, iter([b""])))
    result = _invoke(runner, [
        "--bbox", "-106.3", "39.6", "-106.2", "39.7",
        "--out", str(tmp_path / "d.tif")],
        env={"OPENTOPOGRAPHY_API_KEY": "BADKEY"})
    assert result.exit_code != 0
    assert "rejected the API key" in result.output


def test_registered_in_list_tools(runner):
    result = runner.invoke(cli_root, ["envmon", "list-tools"])
    assert result.exit_code == 0
    assert "download-dem" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/envmon/test_cli_download_dem.py -q`
Expected: FAIL — `download-dem` is not a registered command
(click reports "No such command 'download-dem'").

- [ ] **Step 3: Implement the CLI command**

In `autogis/adapters/cli.py`, insert after `draft_lithology_from_scan_cmd`
(after its closing `_render_qa(...)` line, before the
`@envmon.command("survey-to-well-elevation")` decorator):

```python
@envmon.command("download-dem")
@click.option("--dataset", default="USGS10m", show_default=True,
              help="DEM dataset code (case-insensitive); see --list-datasets.")
@click.option("--bbox", nargs=4, type=float, default=None,
              metavar="W S E N",
              help="WGS84 bounding box (mutually exclusive with --aoi).")
@click.option("--aoi", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="AOI shapefile (.shp) or GeoJSON; non-WGS84 shapefiles "
                   "need the opentopo extra (pip install autogis[opentopo]).")
@click.option("--out", "out_path", default=None, type=click.Path(),
              help="Output raster path; auto-derived from dataset+bbox if omitted.")
@click.option("--overwrite", is_flag=True, default=False,
              help="Allow overwriting an existing --out (refused otherwise).")
@click.option("--format", "output_format", default="GTiff", show_default=True,
              type=click.Choice(["GTiff", "AAIGrid", "HFA"]),
              help="OpenTopography output format.")
@click.option("--api-key", default=None,
              help="Overrides $OPENTOPOGRAPHY_API_KEY for this run.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Resolve AOI/routing, print a redacted URL + area estimate, "
                   "and exit without downloading.")
@click.option("--list-datasets", "list_datasets_flag", is_flag=True,
              default=False, help="Print the dataset registry and exit.")
@qa_report_options
def download_dem_cmd(dataset, bbox, aoi, out_path, overwrite, output_format,
                     api_key, dry_run, list_datasets_flag, report, fail_on):
    """Download an OpenTopography DEM GeoTIFF for an AOI (headless).

    Auto-routes the dataset code to /API/globaldem or /API/usgsdem, resolves
    the AOI to a WGS84 bbox, streams the raster to disk, and writes a
    provenance/citation .json sidecar. Requires an OpenTopography API key
    ($OPENTOPOGRAPHY_API_KEY or --api-key) except for --dry-run and
    --list-datasets.
    """
    from autogis.core.envmon import opentopo

    if list_datasets_flag:
        for ds in opentopo.list_datasets():
            click.echo(f"{ds.code:<16} {ds.endpoint:<9} "
                       f"{ds.resolution:<32} {ds.coverage}")
        return
    if bbox and aoi:
        raise click.UsageError("--bbox and --aoi are mutually exclusive.")
    if not bbox and not aoi:
        raise click.UsageError(
            "an AOI is required: pass --bbox W S E N or --aoi PATH "
            "(or use --list-datasets).")

    try:
        if dry_run:
            ds = opentopo.get_dataset(dataset)
            box = opentopo.resolve_bbox(bbox=bbox or None, aoi_path=aoi)
            click.echo(f"dataset : {ds.code} -> /API/{ds.endpoint} "
                       f"({ds.param}) [{ds.resolution}, {ds.coverage}]")
            click.echo(f"bbox    : W={box[0]} S={box[1]} E={box[2]} N={box[3]} "
                       f"(WGS84)")
            click.echo(f"area    : ~{opentopo.estimate_area_km2(box):,.1f} km2 "
                       f"(~{opentopo.estimate_pixels(ds, box):,} px "
                       f"at {ds.res_m:g} m)")
            click.echo(f"url     : "
                       f"{opentopo.build_url(ds, box, 'REDACTED', output_format)}")
            click.echo("dry run: nothing downloaded.")
            return

        last_step = [0]

        def on_progress(done, total):
            step = done // (10 * 2 ** 20)      # one line per 10 MiB
            if step != last_step[0]:
                last_step[0] = step
                suffix = (f" / {total / 2 ** 20:,.0f} MiB" if total
                          else " MiB")
                click.echo(f"  downloaded {done / 2 ** 20:,.0f}{suffix}")

        result = opentopo.download_dem(
            dataset, bbox=bbox or None, aoi_path=aoi, out_path=out_path,
            api_key=api_key, output_format=output_format,
            overwrite=overwrite, on_progress=on_progress)
    except (ValueError, FileExistsError, RuntimeError, OSError) as err:
        raise click.ClickException(str(err))

    if result.bytes_written:
        click.echo(f"Wrote {result.out_path} ({result.bytes_written:,} bytes) "
                   f"+ provenance sidecar {result.out_path.name}.json")
    _render_qa(result.qa, report, fail_on)
```

Notes for the implementer:
- No `_guard()` — this is a genuinely headless (CLOUD) command like
  `validate-boring-logs`.
- `bbox or None`: click gives `None` when the 4-value option is omitted; the
  `or None` also normalizes a possible empty tuple across click versions.
- `_render_qa(qa, report, fail_on)` exits non-zero on any ERROR record
  (verified: `qa_report_options` defaults `--fail-on` to `"error"` and
  `_render_qa` raises `SystemExit(1)` when `qa.status(...)` is FAIL), which is
  exactly what makes the 401/204/400/500 QA errors exit non-zero. Do not
  change `qa_report_options` or `_render_qa`.

- [ ] **Step 4: Register the tool in `capabilities.py`**

In `autogis/runtime/capabilities.py`:

1. In the `TOOLS` dict, after the line
   `"draft-lithology-from-scan": Runtime.CLOUD,  # tool headless OCR draft`, add:

```python
    "download-dem": Runtime.CLOUD,  # OpenTopography DEM fetch — stdlib urllib, headless
```

2. In `_REGISTRY_SEED`, after the `("draft-lithology-from-scan", ...)` tuple, add:

```python
    ("download-dem", "DownloadOpenTopographyDEM", "", "CLOUD", "stable",
     "intake", "Download an OpenTopography DEM GeoTIFF for an AOI (headless)"),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/envmon/test_cli_download_dem.py tests/envmon/test_opentopo.py -q`
Expected: all PASS.

Smoke-test the real command surface (offline-safe invocations only):

```bash
python -m autogis.adapters.cli envmon download-dem --list-datasets
python -m autogis.adapters.cli envmon download-dem --bbox -106.3 39.6 -106.2 39.7 --dry-run
python -m autogis.adapters.cli envmon list-tools | grep download-dem
```

(If the installed entry point is available, `autogis envmon download-dem ...`
works identically.) Expected: registry table; dry-run block with a REDACTED
URL; one `download-dem ... CLOUD ... intake` row.

- [ ] **Step 6: Run the full suite, then commit**

Run: `python -m pytest -q` — no regressions.

```bash
git add autogis/adapters/cli.py autogis/runtime/capabilities.py tests/envmon/test_cli_download_dem.py
git commit -m "feat(envmon): download-dem CLI command + tool-registry entry"
```

---

### Task 5: `.pyt` tool "Download OpenTopography DEM"

**Files:**
- Modify: `autogis/adapters/toolbox.pyt` (new tool class appended after
  `CompareDroneSurfaces`; class name added to `Toolbox.tools`)

**Interfaces:**
- Consumes: `download_dem`, `DEM_DATASETS`, `DEFAULT_DATASET` from
  `autogis.core.envmon.opentopo` (Tasks 1-3); the existing `_param` and
  `_msg` helpers in `toolbox.pyt`.
- Produces: tool class `DownloadOpenTopoDEM` visible in the "AutoGIS Suite"
  toolbox in ArcGIS Pro.

**Seam note:** `toolbox.pyt` is never imported by the test suite (its top-level
`import arcpy` only resolves inside Pro) — that file is the project's seam for
untestable Pro-only surfaces, exactly like `ConditionDEM`/`CompareDroneSurfaces`.
All AOI-extent resolution, add-to-map, zoom, and reproject code lives here and
only here; everything testable already lives in `opentopo.py`.

- [ ] **Step 1: Add the tool class**

Append to `autogis/adapters/toolbox.pyt` (after `CompareDroneSurfaces`):

```python
class DownloadOpenTopoDEM(object):
    """Download OpenTopography DEM — resolve a Pro AOI to WGS84, fetch the
    DEM via the arcpy-free core (autogis.core.envmon.opentopo), then add the
    raster to the active map. arcpy is used only for AOI resolution and the
    map steps."""

    def __init__(self):
        self.label = "Download OpenTopography DEM"
        self.description = (
            "Download a DEM GeoTIFF from OpenTopography for an AOI (active "
            "map extent, a feature layer honoring any selection, or a manual "
            "WGS84 bbox) and optionally add it to the active map. Requires "
            "an OpenTopography API key ($OPENTOPOGRAPHY_API_KEY or the "
            "API-key parameter). Writes a provenance/citation .json sidecar.")
        self.canRunInBackground = False

    def getParameterInfo(self):
        from autogis.core.envmon.opentopo import DEFAULT_DATASET, DEM_DATASETS
        return [
            _param("dataset", "DEM dataset", "GPString",
                   default=DEFAULT_DATASET, domain=sorted(DEM_DATASETS)),
            _param("aoi_source", "AOI source", "GPString",
                   default="Active map extent",
                   domain=("Active map extent",
                           "Feature layer (selection if any)",
                           "Manual bbox")),
            _param("aoi_layer", "AOI feature layer", "GPFeatureLayer",
                   required=False),
            _param("manual_bbox", "Manual bbox (W S E N, WGS84)", "GPString",
                   required=False),
            _param("out_raster", "Output raster (.tif)", "DEFile",
                   direction="Output"),
            _param("api_key", "API key (blank = $OPENTOPOGRAPHY_API_KEY)",
                   "GPString", required=False),
            _param("add_to_map", "Add result to active map", "GPBoolean",
                   required=False, default=True),
            _param("reproject", "Reproject to map CRS (lossy resample)",
                   "GPBoolean", required=False, default=False),
        ]

    # ---- arcpy AOI resolution (Pro-only; untestable headless) ------------
    @staticmethod
    def _to_wgs84(extent):
        projected = extent.projectAs(arcpy.SpatialReference(4326))
        return (projected.XMin, projected.YMin,
                projected.XMax, projected.YMax)

    def _resolve_aoi_wgs84(self, source, p):
        if source == "Manual bbox":
            parts = (p["manual_bbox"].valueAsText or "").split()
            if len(parts) != 4:
                raise ValueError(
                    "Manual bbox must be 'W S E N' in WGS84 decimal degrees.")
            west, south, east, north = (float(v) for v in parts)
            return (west, south, east, north)

        if source.startswith("Feature layer"):
            layer = p["aoi_layer"].value
            if layer is None:
                raise ValueError(
                    "AOI source is 'Feature layer' but no layer was chosen.")
            xmin = ymin = float("inf")
            xmax = ymax = float("-inf")
            sr = None
            # SearchCursor honors the layer's selection automatically, which
            # is why 'Selected features' needs no separate option.
            with arcpy.da.SearchCursor(layer, ["SHAPE@"]) as cursor:
                for (shape,) in cursor:
                    if shape is None:
                        continue
                    e = shape.extent
                    sr = sr or e.spatialReference
                    xmin, ymin = min(xmin, e.XMin), min(ymin, e.YMin)
                    xmax, ymax = max(xmax, e.XMax), max(ymax, e.YMax)
            if sr is None:
                raise ValueError("AOI layer has no (selected) features.")
            return self._to_wgs84(arcpy.Extent(xmin, ymin, xmax, ymax,
                                               spatial_reference=sr))

        # Active map extent (default)
        view = arcpy.mp.ArcGISProject("CURRENT").activeView
        if view is None or not hasattr(view, "camera"):
            raise ValueError(
                "No active map view — open a map, or choose another AOI source.")
        return self._to_wgs84(view.camera.getExtent())

    def execute(self, parameters, messages):
        from autogis.core.envmon.opentopo import download_dem
        p = {q.name: q for q in parameters}
        try:
            bbox = self._resolve_aoi_wgs84(
                p["aoi_source"].valueAsText or "Active map extent", p)
        except ValueError as err:
            messages.addErrorMessage(str(err))
            return

        out = Path(p["out_raster"].valueAsText)
        try:
            # overwrite=True: Pro's own output-parameter overwrite handling
            # already fronts this tool; the CLI keeps the strict guard.
            result = download_dem(
                p["dataset"].valueAsText, bbox=bbox, out_path=out,
                api_key=p["api_key"].valueAsText or None, overwrite=True)
        except (ValueError, RuntimeError, OSError) as err:
            messages.addErrorMessage(str(err))
            return
        _msg(messages, result.qa)
        if not result.bytes_written:
            return
        messages.addMessage(
            f"Wrote {result.out_path} ({result.bytes_written:,} bytes) + "
            f"provenance sidecar {result.out_path.name}.json")

        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        add_path = result.out_path
        if bool(p["reproject"].value) and active_map is not None:
            map_sr = active_map.spatialReference
            projected = out.with_name(
                f"{out.stem}_epsg{map_sr.factoryCode or 'map'}{out.suffix}")
            arcpy.management.ProjectRaster(str(out), str(projected), map_sr)
            add_path = projected
            messages.addMessage(f"Reprojected to {map_sr.name}: {projected}")
        if bool(p["add_to_map"].value) and active_map is not None:
            layer = active_map.addDataFromPath(str(add_path))
            view = aprx.activeView
            if view is not None and hasattr(view, "camera"):
                view.camera.setExtent(view.getLayerExtent(layer))
            messages.addMessage(f"Added {add_path} to map "
                                f"'{active_map.name}' and zoomed to it.")
```

- [ ] **Step 2: Register the class in `Toolbox.tools`**

In the `Toolbox.__init__` tools list, after `CompareDroneSurfaces,` add:

```python
            DownloadOpenTopoDEM,     # OpenTopography DEM fetch + add-to-map
```

- [ ] **Step 3: Verify syntax (the only headless check possible)**

`toolbox.pyt` cannot be imported without Pro, but it must at least parse:

```bash
python -c "import ast, pathlib; ast.parse(pathlib.Path('autogis/adapters/toolbox.pyt').read_text(encoding='utf-8')); print('toolbox.pyt parses OK')"
```

Expected: `toolbox.pyt parses OK`. Then run the full suite
(`python -m pytest -q`) to confirm nothing imports the `.pyt` by accident.

Functional Pro QA (dataset dropdown, extent AOI, add-to-map, zoom, reproject)
cannot run in this environment — file it as a follow-up QA note in the PR body,
matching the issue-#173/#178 pattern for prior Pro-only surfaces.

- [ ] **Step 4: Commit**

```bash
git add autogis/adapters/toolbox.pyt
git commit -m "feat(pyt): Download OpenTopography DEM tool (AOI from map/layer/bbox, add-to-map)"
```

---

### Task 6: ADR (collision-checked number), README rows

**Files:**
- Create: `docs/adr/0076-opentopography-dem-download.md` (number PROVISIONAL —
  Step 1 decides the real one)
- Modify: `docs/adr/README.md` (index row)
- Modify: `README.md` (tool-table row, runtime-table row, command example)

**Interfaces:**
- Consumes: nothing from code tasks; documents them.
- Produces: the durable decision record CLAUDE.md requires for a shipped tool.

- [ ] **Step 1: ADR-number collision check (explicit — this repo has burned on it 4+ times)**

Do **all three** checks; the highest number seen anywhere +1 is the ADR number:

```bash
ls docs/adr/ | sort | tail -5                        # highest on this branch
gh pr list --state open --json number --jq ".[].number"
# For EVERY open PR from the previous command:
gh pr view <N> --json files --jq ".files[].path" | grep "docs/adr/" || true
```

As of plan-writing (2026-07-09): disk tops out at ADR-0074, open PR #212
claims ADR-0075, open PR #213 adds no ADR → next free is **0076**. Re-run the
check at execution time; if the answer changed, rename the file and every
reference below accordingly (do not trust this plan's number).

- [ ] **Step 2: Write the ADR**

Create `docs/adr/0076-opentopography-dem-download.md` (follow the format in
`docs/adr/TEMPLATE.md` / `docs/adr/README.md`; adjust heading style to match
ADR-0074 if the template drifted):

```markdown
# ADR-0076: OpenTopography DEM download tool + `opentopo` optional extra

Date: 2026-07-09
Status: accepted

## Context

Analysts pull site DEMs from OpenTopography by hand (portal, job wait, manual
download, manual add-to-map) — an out-of-band step in an otherwise automated
workflow. The user holds a paid OpenTopography API key. OpenTopography exposes
two single-GET raster endpoints (`/API/globaldem` via `demtype`,
`/API/usgsdem` via `datasetName`) that return a GeoTIFF directly for a WGS84
bbox. Design: docs/superpowers/specs/2026-07-09-opentopography-dem-download-design.md.

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

- First network-fetching envmon tool; the seam keeps the suite offline.
- Point cloud (LAZ)/`otCatalog` tile-index acquisition, `--buffer`, caching,
  retry/backoff, and batch/tiled oversize downloads are explicitly deferred
  (spec: Out of scope) — a phase-2 decision reopens them.
- The `.pyt` AOI/add-to-map surface is untestable headless (same standing
  exception as every LOCAL tool); functional Pro QA tracked as a follow-up.
- The dataset registry is code, not config; new OpenTopography datasets mean
  a one-line registry edit.
```

- [ ] **Step 3: Add the ADR index row**

In `docs/adr/README.md`, append to the index table (match the existing row
format exactly, e.g. the ADR-0074 row):

```markdown
| [0076](0076-opentopography-dem-download.md) | OpenTopography DEM download tool + `opentopo` optional extra | accepted |
```

(Adjust columns to whatever the table actually has — date/status column order
varies; copy the neighboring row's shape.)

- [ ] **Step 4: Add the README rows**

In `README.md`:

1. Tool table (the alphabetical `| [Name](path) | command | description |`
   table around line 112) — insert alphabetically:

```markdown
| [DownloadOpenTopographyDEM](autogis/core/envmon/opentopo.py) | `envmon download-dem` | Download an OpenTopography DEM GeoTIFF for an AOI (headless; stdlib urllib) |
```

2. Runtime table (the `| command | runtime | core path |` table around
   line 315) — insert alphabetically:

```markdown
| `autogis envmon download-dem` | CLOUD | `core/envmon/opentopo.py` |
```

3. Command examples block (around line 479), add one line:

```
autogis envmon download-dem --dataset USGS10m --bbox <W> <S> <E> <N> --out <dem.tif>
```

If the README states a total test count near the tables, update it to the new
`python -m pytest --collect-only -q` total; if not, add nothing.

- [ ] **Step 5: Verify and commit**

```bash
python -m pytest -q          # full suite still green
```

Expected: all tests pass. Then:

```bash
git add docs/adr/0076-opentopography-dem-download.md docs/adr/README.md README.md
git commit -m "docs(adr): ADR-0076 OpenTopography DEM download + README tool rows"
```

---

## Final verification (after all tasks)

1. `python -m pytest -q` — full suite green.
2. `python -c "import sys; sys.modules['pyproj']=None; from autogis.core.envmon import opentopo; print('imports clean without pyproj')"`
3. `python -m autogis.adapters.cli envmon download-dem --list-datasets` and
   `... --bbox -106.3 39.6 -106.2 39.7 --dry-run` — both exit 0 offline.
4. Optional (needs the real API key + network; only with user consent to spend
   a subscription fetch): a tiny real download,
   `autogis envmon download-dem --bbox -106.30 39.60 -106.28 39.62 --out /tmp/smoke.tif`,
   then confirm `smoke.tif` opens and `smoke.tif.json` carries the citation.
5. Run the `envmon-spec-checker` agent (arcpy-free invariant) and request a
   cold `pr-reviewer` pass before the PR, per house workflow.
