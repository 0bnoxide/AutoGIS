import json
import os
import stat
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis as cli


def _harvest(tmp_path, make_photo_jpeg, geometry=None,
             dto="2026:05:05 08:17:36", lat=45.874, lon=-103.487):
    p = make_photo_jpeg(name="spring.jpg", directory=tmp_path / "Obs" / "S",
                        dto=dto, lat=lat, lon=lon)
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


@pytest.mark.parametrize("limit", ["-1", "nan", "inf"])
def test_photos_qa_rejects_invalid_offset_limit(
        tmp_path, make_photo_jpeg, limit):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h),
        "--max-offset-m", limit])
    assert res.exit_code == 2
    assert "Invalid value" in res.output


def test_photos_qa_reports_missing_datetime_count(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg, dto=None)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(h)])
    assert res.exit_code == 0, res.output
    assert "1 missing datetime" in res.output


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


def test_photos_malformed_manifest_is_clean_error(tmp_path):
    (tmp_path / "manifest.json").write_text("[{truncated", encoding="utf-8")
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(tmp_path)])
    assert res.exit_code != 0
    # CliRunner never puts a raw traceback in .output either way (it just
    # captures the exception object) -- "Error:" is what actually
    # discriminates Click's clean-exception path from an uncaught exception.
    assert "Error:" in res.output
    assert "manifest" in res.output or "Expecting" in res.output


@pytest.mark.parametrize("payload", [
    {}, [42], [{}], [{"foo": "bar"}],
    [{"status": ["downloaded"], "saved_path": "x.jpg"}],
    [{"status": "downloaded", "saved_path": ["x.jpg"]}],
])
def test_photos_invalid_manifest_shape_is_clean_error(tmp_path, payload):
    (tmp_path / "manifest.json").write_text(
        json.dumps(payload), encoding="utf-8")

    res = CliRunner().invoke(cli, [
        "envmon", "photos", "qa", "--harvest-dir", str(tmp_path)])

    assert res.exit_code != 0
    assert "Error:" in res.output
    assert "manifest" in res.output


def test_photos_points_rejects_manifest_overwrite(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h),
        "--out-csv", str(h / "manifest.csv")])
    assert res.exit_code != 0
    assert "overwrite" in res.output


@pytest.mark.parametrize("tail", [
    ["points", "--out-csv", "{photo}"],
    ["qa", "--report", "{photo}"],
    ["log", "--out", "{photo}", "--format", "html"],
    ["kmz", "--out", "{photo}"],
])
def test_photos_commands_reject_harvested_photo_overwrite(
        tmp_path, make_photo_jpeg, tail):
    h = _harvest(tmp_path, make_photo_jpeg)
    photo = h / "Obs" / "S" / "spring.jpg"
    before = photo.read_bytes()
    args = [str(photo) if value == "{photo}" else value for value in tail]

    res = CliRunner().invoke(cli, [
        "envmon", "photos", *args, "--harvest-dir", str(h)])

    assert res.exit_code != 0
    assert "overwrite" in res.output
    assert photo.read_bytes() == before


@pytest.mark.parametrize("tail", [
    ["points", "--out-csv", "{sidecar}"],
    ["qa", "--report", "{sidecar}"],
    ["log", "--out", "{sidecar}", "--format", "html"],
    ["kmz", "--out", "{sidecar}"],
])
def test_photos_commands_reject_non_image_harvest_input_overwrite(
        tmp_path, make_photo_jpeg, tail):
    h = _harvest(tmp_path, make_photo_jpeg)
    sidecar = h / "Obs" / "S" / "evidence.pdf"
    sidecar.write_bytes(b"preserve this evidence")
    manifest = h / "manifest.json"
    rows = json.loads(manifest.read_text(encoding="utf-8"))
    rows.append({**rows[0], "attachment_id": 8,
                 "original_name": sidecar.name,
                 "saved_path": str(sidecar)})
    manifest.write_text(json.dumps(rows), encoding="utf-8")
    before = sidecar.read_bytes()
    args = [str(sidecar) if value == "{sidecar}" else value for value in tail]

    res = CliRunner().invoke(cli, [
        "envmon", "photos", *args, "--harvest-dir", str(h)])

    assert res.exit_code != 0
    assert "overwrite" in res.output
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize("tail", [
    ["points", "--out-csv", "{alias}"],
    ["qa", "--report", "{alias}"],
    ["log", "--out", "{alias}", "--format", "html"],
    ["kmz", "--out", "{alias}"],
])
def test_photos_commands_reject_hard_link_to_harvest_input(
        tmp_path, make_photo_jpeg, tail):
    h = _harvest(tmp_path, make_photo_jpeg)
    photo = h / "Obs" / "S" / "spring.jpg"
    alias = tmp_path / "hard-link-output"
    os.link(photo, alias)
    before = photo.read_bytes()
    args = [str(alias) if value == "{alias}" else value for value in tail]

    res = CliRunner().invoke(cli, [
        "envmon", "photos", *args, "--harvest-dir", str(h)])

    assert res.exit_code != 0
    assert "overwrite" in res.output
    assert os.path.samefile(photo, alias)
    assert photo.read_bytes() == before


@pytest.mark.parametrize("tail", [
    ["points", "--out-csv", "{out}", "--out-geojson", "{out}"],
    ["points", "--out-csv", "{out}", "--report", "{out}"],
    ["log", "--out", "{out}", "--format", "html", "--report", "{out}"],
    ["kmz", "--out", "{out}", "--report", "{out}"],
])
def test_photos_commands_reject_duplicate_output_paths(
        tmp_path, make_photo_jpeg, tail):
    h = _harvest(tmp_path, make_photo_jpeg)
    out = tmp_path / "same.out"
    args = [str(out) if value == "{out}" else value for value in tail]

    res = CliRunner().invoke(cli, [
        "envmon", "photos", *args, "--harvest-dir", str(h)])

    assert res.exit_code != 0
    assert "same output path" in res.output
    assert not out.exists()


def test_photos_points_rejects_hard_linked_outputs(
        tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_csv = tmp_path / "points.csv"
    out_csv.write_text("preserve", encoding="utf-8")
    out_geojson = tmp_path / "points.geojson"
    os.link(out_csv, out_geojson)

    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h),
        "--out-csv", str(out_csv), "--out-geojson", str(out_geojson)])

    assert res.exit_code != 0
    assert "same output file" in res.output
    assert out_csv.read_text(encoding="utf-8") == "preserve"
    assert os.path.samefile(out_csv, out_geojson)


def test_photos_points_preflights_all_outputs_before_writing(
        tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_csv = tmp_path / "created.csv"
    out_geojson = tmp_path / "existing-directory"
    out_geojson.mkdir()

    res = CliRunner().invoke(cli, [
        "envmon", "photos", "points", "--harvest-dir", str(h),
        "--out-csv", str(out_csv), "--out-geojson", str(out_geojson)])

    assert res.exit_code != 0
    assert "not a writable file target" in res.output
    assert not out_csv.exists()


def test_photos_points_preflights_read_only_output_before_writing(
        tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    out_csv = tmp_path / "created.csv"
    out_geojson = tmp_path / "locked.geojson"
    out_geojson.write_text("preserve", encoding="utf-8")
    out_geojson.chmod(stat.S_IREAD)
    try:
        res = CliRunner().invoke(cli, [
            "envmon", "photos", "points", "--harvest-dir", str(h),
            "--out-csv", str(out_csv), "--out-geojson", str(out_geojson)])
    finally:
        out_geojson.chmod(stat.S_IWRITE)

    assert res.exit_code != 0
    assert "not writable" in res.output
    assert not out_csv.exists()
    assert out_geojson.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("tail", [
    ["points", "--out-csv", "{out}"],
    ["log", "--out", "{out}", "--format", "html"],
])
def test_photos_inventory_warnings_reach_non_qa_commands(
        tmp_path, make_photo_jpeg, tail):
    h = _harvest(tmp_path, make_photo_jpeg, dto=None, lat=None, lon=None)
    out = tmp_path / "output"
    args = [str(out) if value == "{out}" else value for value in tail]

    res = CliRunner().invoke(cli, [
        "envmon", "photos", *args, "--harvest-dir", str(h),
        "--fail-on", "warning"])

    assert res.exit_code != 0
    assert "photo_missing_gps" in res.output
    assert "photo_missing_datetime" in res.output


def test_photos_kmz_thumb_px_zero_rejected(tmp_path, make_photo_jpeg):
    h = _harvest(tmp_path, make_photo_jpeg)
    res = CliRunner().invoke(cli, [
        "envmon", "photos", "kmz", "--harvest-dir", str(h),
        "--out", str(tmp_path / "p.kmz"), "--thumb-px", "0"])
    assert res.exit_code == 2
