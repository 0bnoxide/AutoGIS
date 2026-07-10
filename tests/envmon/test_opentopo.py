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
