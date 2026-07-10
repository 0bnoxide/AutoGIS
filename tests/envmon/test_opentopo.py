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
