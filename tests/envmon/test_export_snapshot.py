import json
import dataclasses
import zipfile
import pytest
from autogis.core.envmon.export_snapshot import (
    SnapshotManifest, format_manifest, build_where, validate_snapshot_id,
    compress_snapshot_gdb,
)
from autogis.core.envmon.gdb_schema import TABLE_SCHEMAS
from click.testing import CliRunner
from autogis.adapters.cli import autogis

_MANIFEST = SnapshotManifest(
    site_id="H281",
    event_id="2026Q2",
    exported_at="2026-06-27T14:32:00",
    schema_version="2.0",
    source_gdb="C:/GIS/H281/H281.gdb",
    output_path="C:/snapshots/H281_2026Q2.gdb",
    tables_copied=["Env_Samples", "Env_AnalyticalResults"],
    tables_skipped=["BoringLocations"],
    feature_classes_copied=["MonitoringWells"],
    row_counts={"Env_Samples": 42, "Env_AnalyticalResults": 204},
)


def test_format_manifest_contains_site_id():
    out = format_manifest(_MANIFEST)
    assert "H281" in out


def test_format_manifest_contains_event_id():
    out = format_manifest(_MANIFEST)
    assert "2026Q2" in out


def test_format_manifest_shows_table_counts():
    out = format_manifest(_MANIFEST)
    assert "2" in out


def test_format_manifest_shows_skipped():
    out = format_manifest(_MANIFEST)
    assert "BoringLocations" in out
    assert "SKIPPED" in out.upper()


def test_manifest_json_roundtrip():
    d = dataclasses.asdict(_MANIFEST)
    s = json.dumps(d)
    loaded = json.loads(s)
    assert loaded["site_id"] == "H281"


def test_build_where_both():
    w = build_where("H281", "2026Q2", has_site=True, has_event=True)
    assert "SiteID" in w and "EventID" in w


def test_build_where_site_only():
    w = build_where("H281", "2026Q2", has_site=True, has_event=False)
    assert "SiteID" in w
    assert "EventID" not in w


def test_build_where_neither():
    w = build_where("H281", "2026Q2", has_site=False, has_event=False)
    assert w is None


def test_build_where_no_sql_injection():
    """A site_id containing a single quote must not break out of the SQL
    string literal -- the embedded quote must be escaped (doubled), not
    passed through raw (issue #366; this test used to only assert `w is
    not None`, which passes even on a fully-injected payload)."""
    w = build_where("H281'; DROP TABLE--", "2026Q2", has_site=True, has_event=False)
    assert w == "SiteID = 'H281''; DROP TABLE--'"
    # exactly one string literal in the clause: no unescaped quote broke out
    assert w.count("'") % 2 == 0


def test_build_where_escapes_event_id_quote():
    w = build_where("H281", "2026'Q2", has_site=False, has_event=True)
    assert w == "EventID = '2026''Q2'"


def test_compress_snapshot_gdb_zips_the_directory(tmp_path):
    """Issue #342: --compress was accepted and documented but silently did
    nothing -- no zipfile reference anywhere in the implementation."""
    gdb_dir = tmp_path / "H281_2026Q2_snapshot_20260726.gdb"
    gdb_dir.mkdir()
    (gdb_dir / "a00000001.gdbtable").write_bytes(b"fake gdb table data")
    (gdb_dir / "timestamps").mkdir()
    (gdb_dir / "timestamps" / "timestamps.bin").write_bytes(b"x")

    archive_path = compress_snapshot_gdb(str(gdb_dir))

    assert archive_path == str(gdb_dir) + ".zip"
    assert zipfile.is_zipfile(archive_path)
    with zipfile.ZipFile(archive_path) as zf:
        names = set(zf.namelist())
    assert f"{gdb_dir.name}/a00000001.gdbtable" in names
    assert f"{gdb_dir.name}/timestamps/timestamps.bin" in names


def test_format_manifest_shows_compressed_path_when_present():
    m = dataclasses.replace(_MANIFEST, compressed_path="C:/snapshots/x.gdb.zip")
    out = format_manifest(m)
    assert "Compressed: C:/snapshots/x.gdb.zip" in out


def test_format_manifest_omits_compressed_line_when_absent():
    out = format_manifest(_MANIFEST)
    assert "Compressed:" not in out


def test_export_snapshot_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "export-snapshot" in result.output


def test_validate_snapshot_id_accepts_normal_value():
    validate_snapshot_id("H281", "site_id")  # must not raise


def test_validate_snapshot_id_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        validate_snapshot_id("", "site_id")


def test_validate_snapshot_id_rejects_whitespace_only():
    with pytest.raises(ValueError, match="empty"):
        validate_snapshot_id("   ", "site_id")


def test_validate_snapshot_id_rejects_leading_trailing_whitespace():
    with pytest.raises(ValueError, match="whitespace"):
        validate_snapshot_id(" H281", "site_id")


@pytest.mark.parametrize("bad_char", list('<>:"/\\|?*'))
def test_validate_snapshot_id_rejects_illegal_chars(bad_char):
    with pytest.raises(ValueError, match="not allowed"):
        validate_snapshot_id(f"H281{bad_char}", "event_id")


def test_validate_snapshot_id_error_names_the_field_and_value():
    with pytest.raises(ValueError, match="event_id"):
        validate_snapshot_id("<bad>", "event_id")
