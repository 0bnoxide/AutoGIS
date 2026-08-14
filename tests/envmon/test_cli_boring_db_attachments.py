"""CLI tests for envmon create-boring-log-db (8.0a) and
index-field-attachments (6.5)."""
import sqlite3

from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.harvest.manifest import Manifest
from autogis.core.harvest.models import AttachmentResult


def test_both_commands_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "create-boring-log-db" in result.output
    assert "index-field-attachments" in result.output


# ---- create-boring-log-db -------------------------------------------------

def test_create_boring_log_db(tmp_path):
    db = tmp_path / "boring.sqlite"
    result = CliRunner().invoke(
        autogis, ["envmon", "create-boring-log-db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Created boring-log database" in result.output
    assert db.exists()


def test_create_boring_log_db_existing_fails_without_overwrite(tmp_path):
    db = tmp_path / "boring.sqlite"
    runner = CliRunner()
    assert runner.invoke(
        autogis, ["envmon", "create-boring-log-db", str(db)]).exit_code == 0
    result = runner.invoke(
        autogis, ["envmon", "create-boring-log-db", str(db)])
    assert result.exit_code == 1
    assert "file_exists" in result.output
    # and --overwrite succeeds
    result = runner.invoke(
        autogis, ["envmon", "create-boring-log-db", str(db), "--overwrite"])
    assert result.exit_code == 0, result.output


def test_create_boring_log_db_validate_mode(tmp_path):
    db = tmp_path / "boring.sqlite"
    runner = CliRunner()
    runner.invoke(autogis, ["envmon", "create-boring-log-db", str(db)])
    result = runner.invoke(
        autogis, ["envmon", "create-boring-log-db", str(db), "--validate"])
    assert result.exit_code == 0, result.output
    assert "Status: PASS" in result.output

    conn = sqlite3.connect(str(db))
    conn.execute('DROP TABLE "BoringComments"')
    conn.commit()
    conn.close()
    result = runner.invoke(
        autogis, ["envmon", "create-boring-log-db", str(db), "--validate"])
    assert result.exit_code == 1
    assert "missing_table" in result.output


# ---- index-field-attachments ----------------------------------------------

def _write_manifest(tmp_path, saved_path="C:/att/photo.jpg"):
    m = Manifest()
    m.add(AttachmentResult(
        objectid=1, attachment_id=10, original_name="photo.jpg",
        saved_path=saved_path, size=512, status="downloaded",
        disposition="downloaded", source_table="MonitoringWells"))
    csv_path, json_path = m.write(str(tmp_path))
    return csv_path, json_path


def test_index_field_attachments_end_to_end(tmp_path):
    csv_path, _ = _write_manifest(tmp_path)
    db = tmp_path / "envmon.sqlite"
    result = CliRunner().invoke(autogis, [
        "envmon", "index-field-attachments", csv_path, "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Indexed 1 attachment(s)" in result.output
    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute(
            'SELECT COUNT(*) FROM "AttachmentIndex"').fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_index_field_attachments_malformed_manifest_clean_error(tmp_path):
    """A truncated manifest.json surfaces a clean error naming the file,
    not a json.JSONDecodeError traceback (#496)."""
    bad = tmp_path / "manifest.json"
    bad.write_text('{"not json', encoding="utf-8")
    db = tmp_path / "envmon.sqlite"
    result = CliRunner().invoke(autogis, [
        "envmon", "index-field-attachments", str(bad), "--db", str(db)])
    assert result.exit_code != 0
    assert "Malformed manifest" in result.output
    assert "manifest.json" in result.output
    assert "Traceback" not in result.output


def test_index_field_attachments_json_manifest(tmp_path):
    _, json_path = _write_manifest(tmp_path)
    db = tmp_path / "envmon.sqlite"
    result = CliRunner().invoke(autogis, [
        "envmon", "index-field-attachments", json_path, "--db", str(db)])
    assert result.exit_code == 0, result.output


def test_index_field_attachments_blocking_error_skips_write(tmp_path):
    csv_path, _ = _write_manifest(tmp_path, saved_path=None)
    db = tmp_path / "envmon.sqlite"
    result = CliRunner().invoke(autogis, [
        "envmon", "index-field-attachments", csv_path, "--db", str(db)])
    assert result.exit_code == 1
    assert "downloaded_missing_path" in result.output
    assert not db.exists()
