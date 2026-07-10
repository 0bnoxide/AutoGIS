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
