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
