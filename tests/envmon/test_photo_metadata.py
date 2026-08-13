import json
from pathlib import Path

import pytest

from autogis.core.common.qa import QACollector
from autogis.core.envmon.photo_metadata import (
    PhotoRecord, evaluate_photo_qa, extract_exif, haversine_m,
    load_photo_records)


def _manifest(tmp_path, rows):
    (tmp_path / "manifest.json").write_text(
        json.dumps(rows), encoding="utf-8")


def _row(saved_path, **kw):
    base = {"objectid": 2, "attachment_id": 7, "original_name": "Photo 1.jpg",
            "saved_path": None if saved_path is None else str(saved_path),
            "size": 5, "status": "downloaded",
            "error": None, "disposition": "downloaded", "checksum": None,
            "algorithm": None, "geometry": None,
            "source_table": "Observation_Point", "relationship_id": None,
            "feature_edited_at": None}
    base.update(kw)
    return base


def test_extract_exif_round_trip(make_photo_jpeg):
    p = make_photo_jpeg(lat=45.874, lon=-103.487, heading=231.5)
    got = extract_exif(p)
    assert got["exif_lat"] == pytest.approx(45.874, abs=1e-4)
    assert got["exif_lon"] == pytest.approx(-103.487, abs=1e-4)
    assert got["heading_deg"] == pytest.approx(231.5)
    assert got["heading_ref"] == "T"
    assert got["taken_at"] == "2026-05-05T08:17:36"
    assert got["camera"] == "samsung SM-X308U"


def test_extract_exif_no_gps(make_photo_jpeg):
    p = make_photo_jpeg(lat=None, lon=None, heading=None)
    got = extract_exif(p)
    assert got.get("exif_lat") is None and got.get("exif_lon") is None
    assert got["taken_at"] == "2026-05-05T08:17:36"


def test_extract_exif_unreadable(tmp_path):
    pytest.importorskip("PIL")
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not a jpeg at all")
    got = extract_exif(p)
    assert "exif_error" in got


def test_haversine_known_distance():
    # 0.01 deg latitude ~ 1111.9 m
    assert haversine_m(45.0, -103.0, 45.01, -103.0) == pytest.approx(
        1111.95, rel=0.01)


def test_load_photo_records_joins_manifest_and_exif(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(name="Picnic_3_Photo_1.jpg",
                        directory=tmp_path / "Obs_1" / "SeepSpring")
    _manifest(tmp_path, [_row(
        p, geometry={"lat": 45.875, "lon": -103.487},
        feature_edited_at="2026-05-05T14:20:00+00:00")])
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert len(recs) == 1
    r = recs[0]
    assert r.objectid == 2 and r.source_table == "Observation_Point"
    assert r.group == "Obs_1/SeepSpring"
    assert r.exif_lat == pytest.approx(45.874, abs=1e-4)
    assert r.feature_lat == pytest.approx(45.875)
    assert r.feature_edited_at == "2026-05-05T14:20:00+00:00"
    assert r.offset_m == pytest.approx(
        haversine_m(r.exif_lat, r.exif_lon, 45.875, -103.487), rel=1e-6)


def test_load_photo_records_csv_manifest_with_string_nulls(
        tmp_path, make_photo_jpeg):
    # CSV DictReader yields "" for nulls and strings for numbers.
    p = make_photo_jpeg(directory=tmp_path / "G")
    import csv
    row = _row(p, geometry="", feature_edited_at="")
    row = {k: ("" if v is None else v) for k, v in row.items()}
    with (tmp_path / "manifest.csv").open("w", newline="",
                                          encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert len(recs) == 1
    assert recs[0].objectid == 2
    assert recs[0].feature_lat is None


def test_load_photo_records_skips_failed_and_missing(tmp_path, make_photo_jpeg):
    p = make_photo_jpeg(directory=tmp_path / "G")
    rows = [
        _row(p),
        _row(tmp_path / "G" / "gone.jpg"),           # file missing on disk
        _row(None, status="failed", disposition="failed"),
        _row(tmp_path / "G" / "doc.pdf"),            # non-image suffix
    ]
    (tmp_path / "G" / "doc.pdf").write_bytes(b"%PDF-1.4")
    _manifest(tmp_path, rows)
    qa = QACollector()
    recs = load_photo_records(tmp_path, qa)
    assert [Path(r.saved_path).name for r in recs] == ["p.jpg"]
    cats = {r.category for r in qa.records}
    assert "photo_missing" in cats and "non_image_attachment" in cats


def test_load_photo_records_no_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_photo_records(tmp_path, QACollector())


def _rec(**kw):
    base = dict(objectid=1, attachment_id=1, source_table="T", group="G",
                saved_path="G/p.jpg")
    base.update(kw)
    return PhotoRecord(**base)


def test_qa_flags_offset_over_threshold():
    recs = [_rec(exif_lat=45.0, exif_lon=-103.0, feature_lat=45.0,
                 feature_lon=-103.0, offset_m=250.0),
            _rec(exif_lat=45.0, exif_lon=-103.0, feature_lat=45.0,
                 feature_lon=-103.0, offset_m=20.0)]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa, max_offset_m=100.0)
    assert s["checked_offset"] == 2 and s["flagged_offset"] == 1
    assert any(r.category == "photo_far_from_feature" for r in qa.records)


def test_qa_flags_date_mismatch_day_level():
    recs = [_rec(taken_at="2026-05-05T08:17:36",
                 feature_edited_at="2026-05-09T14:00:00+00:00"),   # 4 days
            _rec(taken_at="2026-05-05T23:59:00",
                 feature_edited_at="2026-05-06T00:10:00+00:00")]   # ±1 ok
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["checked_date"] == 2 and s["flagged_date"] == 1
    assert any(r.category == "photo_date_mismatch" for r in qa.records)


def test_qa_missing_gps_and_unreadable_inventory():
    recs = [_rec(), _rec(exif_error="unreadable image: nope")]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["missing_gps"] == 1 and s["unreadable"] == 1
    cats = {r.category for r in qa.records}
    assert {"photo_missing_gps", "photo_unreadable"} <= cats


def test_qa_geometryless_manifest_skips_with_info():
    recs = [_rec(exif_lat=45.0, exif_lon=-103.0)]
    qa = QACollector()
    s = evaluate_photo_qa(recs, qa)
    assert s["checked_offset"] == 0
    assert any(r.severity == "INFO" and r.category == "geometry_checks_skipped"
               for r in qa.records)
