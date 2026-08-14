import csv
import json
from pathlib import Path

from autogis.core.envmon.photo_metadata import PhotoRecord
from autogis.core.envmon.photo_points import (
    POINT_FIELDS, write_points_csv, write_points_geojson)


def _rec(**kw):
    base = dict(objectid=2, attachment_id=7, source_table="Obs", group="G",
                saved_path="C:/h/G/p.jpg", exif_lat=45.874, exif_lon=-103.487,
                heading_deg=231.5, heading_ref="T",
                taken_at="2026-05-05T08:17:36", camera="samsung SM-X308U",
                feature_lat=45.875, feature_lon=-103.487, offset_m=111.2)
    base.update(kw)
    return PhotoRecord(**base)


def test_points_csv(tmp_path):
    out = tmp_path / "points.csv"
    n = write_points_csv([_rec(), _rec(exif_lat=None, exif_lon=None)], out)
    assert n == 1
    rows = list(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert len(rows) == 1
    assert list(rows[0]) == POINT_FIELDS
    assert rows[0]["lat"] == "45.874" and rows[0]["heading_deg"] == "231.5"
    assert rows[0]["objectid"] == "2"


def test_points_csv_empty_still_has_header(tmp_path):
    out = tmp_path / "points.csv"
    assert write_points_csv([], out) == 0
    rows = out.read_text(encoding="utf-8").strip().splitlines()
    assert rows == [",".join(POINT_FIELDS)]


def test_points_geojson(tmp_path):
    out = tmp_path / "points.geojson"
    n = write_points_geojson([_rec()], out)
    assert n == 1
    fc = json.loads(out.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    f = fc["features"][0]
    assert f["geometry"] == {"type": "Point",
                             "coordinates": [-103.487, 45.874]}
    assert f["properties"]["heading_deg"] == 231.5
    assert f["properties"]["photo_path"] == "C:/h/G/p.jpg"


def test_points_geojson_empty(tmp_path):
    out = tmp_path / "points.geojson"
    assert write_points_geojson([], out) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["features"] == []


import xml.etree.ElementTree as ET
import zipfile

import pytest

from autogis.core.envmon.photo_points import write_kmz

_KMLNS = "{http://www.opengis.net/kml/2.2}"


def test_kmz_placemarks_and_thumbnails(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(name="spring.jpg", directory=tmp_path / "G")
    out = tmp_path / "photos.kmz"
    n = write_kmz([_rec(saved_path=str(p), exif_lat=45.8741234, exif_lon=-103.4871234),
                   _rec(exif_lat=None, exif_lon=None)], out)
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "doc.kml" in names and "files/thumb_0.jpg" in names
        root = ET.fromstring(zf.read("doc.kml"))
    pms = root.findall(f".//{_KMLNS}Placemark")
    assert len(pms) == 1
    coords = pms[0].find(f".//{_KMLNS}coordinates").text.strip()
    lon_str, lat_str, _ = coords.split(",")
    assert float(lon_str) == pytest.approx(-103.4871234, abs=1e-7)
    assert float(lat_str) == pytest.approx(45.8741234, abs=1e-7)
    assert pms[0].find(f".//{_KMLNS}heading").text == "231.5"
    assert "files/thumb_0.jpg" in pms[0].find(f".//{_KMLNS}description").text


def test_kmz_missing_photo_file_placemark_without_image(tmp_path):
    out = tmp_path / "photos.kmz"
    n = write_kmz([_rec(saved_path=str(tmp_path / "gone.jpg"))], out)
    assert n == 1
    with zipfile.ZipFile(out) as zf:
        assert [n2 for n2 in zf.namelist() if n2.startswith("files/")] == []


def test_kmz_empty(tmp_path):
    out = tmp_path / "photos.kmz"
    assert write_kmz([], out) == 0
    with zipfile.ZipFile(out) as zf:
        ET.fromstring(zf.read("doc.kml"))  # valid, just no placemarks
