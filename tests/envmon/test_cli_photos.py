import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as cli


def _harvest(tmp_path, make_photo_jpeg, geometry=None):
    p = make_photo_jpeg(name="spring.jpg", directory=tmp_path / "Obs" / "S")
    row = {"objectid": 2, "attachment_id": 7, "original_name": "Photo 1.jpg",
           "saved_path": str(p), "size": 5, "status": "downloaded",
           "error": None, "disposition": "downloaded", "checksum": None,
           "algorithm": None, "geometry": geometry,
           "source_table": "Obs", "relationship_id": None,
           "feature_edited_at": None}
    (tmp_path / "manifest.json").write_text(json.dumps([row]),
                                            encoding="utf-8")
    return tmp_path


def test_photos_points(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_csv = tmp_path / "pts.csv"
    out_gj = tmp_path / "pts.geojson"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h),
        "--out-csv", str(out_csv), "--out-geojson", str(out_gj)])
    assert res.exit_code == 0, res.output
    assert out_csv.exists() and out_gj.exists()
    assert "1 point(s)" in res.output


def test_photos_points_requires_an_output(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h)])
    assert res.exit_code != 0
    assert "--out-csv" in res.output


def test_photos_qa_geometryless_manifest(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h)])
    assert res.exit_code == 0, res.output
    assert "geometry_checks_skipped" in res.output


def test_photos_qa_offset_flag(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg,
                 geometry={"lat": 45.9, "lon": -103.487})  # ~2.9 km away
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h),
        "--fail-on", "warning"])
    assert res.exit_code != 0
    assert "photo_far_from_feature" in res.output


def test_photos_log_and_kmz(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_log = tmp_path / "log.html"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "log", "--harvest-dir", str(h),
        "--out", str(out_log), "--format", "html"])
    assert res.exit_code == 0, res.output
    assert out_log.exists()
    out_kmz = tmp_path / "p.kmz"
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "kmz", "--harvest-dir", str(h),
        "--out", str(out_kmz)])
    assert res.exit_code == 0, res.output
    with zipfile.ZipFile(out_kmz) as zf:
        assert "doc.kml" in zf.namelist()


def test_photos_missing_manifest_is_clean_error(tmp_path):
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(tmp_path)])
    assert res.exit_code != 0
    assert "manifest" in res.output
