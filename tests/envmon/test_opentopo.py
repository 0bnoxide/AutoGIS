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


def test_download_appends_format_extension_when_output_has_none(
        tmp_path, api_key_env):
    result = download_dem(
        "USGS10m", bbox=BBOX, out_path=tmp_path / "dem",
        http_get=fake_get(200, b"GEOTIFF"))

    assert result.out_path == tmp_path / "dem.tif"
    assert result.out_path.read_bytes() == b"GEOTIFF"
    assert (tmp_path / "dem.tif.json").exists()


def test_download_rejects_extension_that_mismatches_format(
        tmp_path, api_key_env):
    with pytest.raises(ValueError, match=r"must end in \.tif"):
        download_dem(
            "USGS10m", bbox=BBOX, out_path=tmp_path / "dem.img",
            http_get=lambda _url: pytest.fail("invalid path must fail before fetch"))


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


# --------------------------------------------------- download_dem hardening
def test_download_truncated_content_length_mismatch(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"

    def truncated(url):
        return 200, {"Content-Length": "9999"}, iter([b"too short"])

    result = download_dem("USGS10m", bbox=BBOX, out_path=out,
                          http_get=truncated)
    assert result.bytes_written == 0
    assert not out.exists(), "truncated download must never leave a final .tif"
    assert not list(tmp_path.glob("*.part"))
    assert not (tmp_path / "dem.tif.json").exists(), "no sidecar on failure"
    errors = [r for r in result.qa.records if r.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "truncated"


def test_download_success_without_content_length_is_noop(tmp_path, api_key_env):
    out = tmp_path / "dem.tif"

    def no_content_length(url):
        return 200, {}, iter([b"bytes-with-no-length-header"])

    result = download_dem("USGS10m", bbox=BBOX, out_path=out,
                          http_get=no_content_length)
    assert result.bytes_written == len(b"bytes-with-no-length-header")
    assert out.exists()
    assert not [r for r in result.qa.records if r.severity == "ERROR"]


def test_download_rename_failure_cleans_up_part(tmp_path, api_key_env,
                                                 monkeypatch):
    out = tmp_path / "dem.tif"

    def boom(*_args, **_kwargs):
        raise PermissionError("file in use")

    monkeypatch.setattr("autogis.core.envmon.opentopo.os.replace", boom)
    result = download_dem("USGS10m", bbox=BBOX, out_path=out,
                          http_get=fake_get(200, b"some bytes"))
    assert result.bytes_written == 0
    assert not out.exists()
    assert not list(tmp_path.glob("*.part")), "rename failure must not orphan .part"
    assert not (tmp_path / "dem.tif.json").exists(), "no sidecar on failure"
    errors = [r for r in result.qa.records if r.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "write_failed"


def test_download_204_drains_and_closes_response(tmp_path, api_key_env):
    closed = {"flag": False}

    def gen():
        try:
            return
            yield  # pragma: no cover - makes this a generator
        finally:
            closed["flag"] = True

    def no_data(url):
        return 204, {}, gen()

    download_dem("USGS10m", bbox=BBOX, out_path=tmp_path / "d.tif",
                 http_get=no_data)
    assert closed["flag"], "204 response generator must be drained/closed"


def test_download_rename_failure_preserves_preexisting_file(tmp_path,
                                                             api_key_env,
                                                             monkeypatch):
    out = tmp_path / "dem.tif"
    out.write_bytes(b"original data")

    def boom(*_args, **_kwargs):
        raise PermissionError("file in use")

    monkeypatch.setattr("autogis.core.envmon.opentopo.os.replace", boom)
    result = download_dem("USGS10m", bbox=BBOX, out_path=out, overwrite=True,
                          http_get=fake_get(200, b"new bytes"))
    assert result.bytes_written == 0
    assert out.read_bytes() == b"original data", \
        "rename failure must never delete/corrupt a pre-existing out file"
    assert not list(tmp_path.glob("*.part"))
