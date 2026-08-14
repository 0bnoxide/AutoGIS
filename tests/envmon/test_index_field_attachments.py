"""Tests for autogis/core/envmon/index_field_attachments.py (tool 6.5).

Manifests are written by the REAL harvester Manifest class so the envmon-side
reader is exercised against the exact CSV/JSON shape the harvester produces.
"""
import sqlite3
from datetime import datetime

import pytest

from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING
from autogis.core.envmon.index_field_attachments import (
    build_attachment_index,
    classify_attachment,
    load_manifest,
    validate_attachment_index,
    write_attachment_index,
)
from autogis.core.harvest.manifest import Manifest
from autogis.core.harvest.models import AttachmentResult


def _manifest(tmp_path):
    m = Manifest()
    m.add(AttachmentResult(
        objectid=101, attachment_id=1, original_name="well_photo.JPG",
        saved_path="C:/attachments/well_photo.JPG", size=2048,
        status="downloaded", disposition="downloaded",
        checksum="abc123", source_table="MonitoringWells"))
    m.add(AttachmentResult(
        objectid=102, attachment_id=2, original_name="lab_report.pdf",
        saved_path=None, size=None, status="skipped", disposition="skipped"))
    return m.write(str(tmp_path))  # (csv_path, json_path)


def test_load_manifest_csv_and_json_agree(tmp_path):
    csv_path, json_path = _manifest(tmp_path)
    csv_rows = load_manifest(csv_path)
    json_rows = load_manifest(json_path)
    assert len(csv_rows) == len(json_rows) == 2
    assert str(csv_rows[0]["attachment_id"]) == "1"
    assert json_rows[0]["attachment_id"] == 1


def test_load_manifest_malformed_json_raises_valueerror(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text('{"not json', encoding="utf-8")
    with pytest.raises(ValueError, match=r"Malformed manifest .*manifest\.json"):
        load_manifest(p)


def test_load_manifest_broken_encoding_csv_raises_valueerror(tmp_path):
    p = tmp_path / "manifest.csv"
    p.write_bytes(b"objectid,original_name\n1,caf\xe9.jpg\n")  # cp1252, not UTF-8
    with pytest.raises(ValueError, match=r"Malformed manifest .*manifest\.csv"):
        load_manifest(p)


def test_classify_attachment():
    assert classify_attachment("a.JPG") == "photo"
    assert classify_attachment("b.pdf") == "document"
    assert classify_attachment("c.xlsx") == "spreadsheet"
    assert classify_attachment("d.zzz") == "other"
    assert classify_attachment("") == "other"


def test_build_index_maps_fields(tmp_path):
    _, json_path = _manifest(tmp_path)
    recs = build_attachment_index(load_manifest(json_path))
    assert len(recs) == 2
    r = recs[0]
    assert r.attachment_id == 1
    assert r.related_table == "MonitoringWells"
    assert r.related_id == "101"
    assert r.local_path == "C:/attachments/well_photo.JPG"
    assert r.attachment_type == "photo"
    assert r.size_bytes == 2048
    assert r.checksum == "abc123"
    assert r.status == "downloaded"
    assert isinstance(r.synced_date, datetime)
    # row without source_table falls back to the supplied related_table
    recs2 = build_attachment_index(load_manifest(json_path),
                                   related_table="FieldForms")
    assert recs2[1].related_table == "FieldForms"


def test_build_index_skips_bad_attachment_id_with_warning():
    qa = QACollector()
    recs = build_attachment_index(
        [{"attachment_id": "", "objectid": "1"},
         {"attachment_id": "7", "objectid": "2", "original_name": "x.png"}],
        qa=qa)
    assert [r.attachment_id for r in recs] == [7]
    assert any(r.severity == SEV_WARNING and
               r.category == "manifest_rows_skipped" for r in qa.records)


def test_build_index_warns_on_unjoinable_related_table():
    qa = QACollector()
    recs = build_attachment_index(
        [{"attachment_id": "9", "objectid": "3", "original_name": "y.png"}],
        qa=qa)
    assert recs[0].related_table == ""
    assert any(r.severity == SEV_WARNING and
               r.category == "attachment_related_table_missing"
               for r in qa.records)


def test_build_index_no_warning_when_related_table_supplied():
    qa = QACollector()
    recs = build_attachment_index(
        [{"attachment_id": "9", "objectid": "3", "original_name": "y.png"}],
        related_table="FieldForms", qa=qa)
    assert recs[0].related_table == "FieldForms"
    assert not any(r.category == "attachment_related_table_missing"
                   for r in qa.records)


def test_validate_flags_downloaded_without_path(tmp_path):
    _, json_path = _manifest(tmp_path)
    recs = build_attachment_index(load_manifest(json_path))
    recs[0].local_path = ""
    qa = QACollector()
    validate_attachment_index(recs, qa)
    assert any(r.severity == SEV_ERROR and
               r.category == "downloaded_missing_path" for r in qa.records)


def test_validate_clean_manifest_passes(tmp_path):
    _, json_path = _manifest(tmp_path)
    recs = build_attachment_index(load_manifest(json_path))
    qa = QACollector()
    validate_attachment_index(recs, qa)
    assert not any(r.severity == SEV_ERROR for r in qa.records)


def test_write_creates_table_and_rows(tmp_path):
    csv_path, _ = _manifest(tmp_path)
    recs = build_attachment_index(load_manifest(csv_path))
    db = tmp_path / "envmon.sqlite"
    n = write_attachment_index(db, recs)
    assert n == 2
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            'SELECT attachment_id, related_id, attachment_type, size_bytes '
            'FROM "AttachmentIndex" ORDER BY attachment_id').fetchall()
    finally:
        conn.close()
    assert rows[0] == (1, "101", "photo", 2048)
    assert rows[1] == (2, "102", "document", None)


def test_write_replace_clears_previous_rows(tmp_path):
    csv_path, _ = _manifest(tmp_path)
    recs = build_attachment_index(load_manifest(csv_path))
    db = tmp_path / "envmon.sqlite"
    write_attachment_index(db, recs)
    write_attachment_index(db, recs)          # append -> 4
    n = write_attachment_index(db, recs, replace=True)
    assert n == 2
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            'SELECT COUNT(*) FROM "AttachmentIndex"').fetchone()[0]
    finally:
        conn.close()
    assert count == 2
