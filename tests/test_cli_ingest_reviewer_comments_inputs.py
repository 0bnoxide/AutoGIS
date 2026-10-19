"""ingest-reviewer-comments inputs that cannot be read, or are the wrong
shape, are a clean CLI error, not a traceback (#585)."""
import zipfile

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _invoke(*args):
    return CliRunner().invoke(autogis, ["envmon", "ingest-reviewer-comments",
                                        *map(str, args)])


def _clean_exit(result, code):
    assert result.exit_code == code, result.output
    assert result.exception is None or isinstance(result.exception,
                                                  SystemExit)


@pytest.mark.parametrize("name,content", [
    ("empty.geojson", b""),
    ("bad.json", b"not json"),
    ("empty.xlsx", b""),
    ("latin1 é.csv", b"comment\n\xff\xfe\n"),
    ("huge field.csv", b'comment\n"' + b"x" * 200_000 + b'"\n'),
])
def test_unreadable_input_is_a_clean_error(tmp_path, name, content):
    bad = tmp_path / name
    bad.write_bytes(content)
    result = _invoke(bad, "--out", tmp_path / "o.csv")
    _clean_exit(result, 1)
    assert "cannot read" in result.output and str(bad) in result.output


def test_zip_that_is_not_a_workbook_is_a_clean_error(tmp_path):
    bad = tmp_path / "z.xlsx"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("a.txt", "x")
    result = _invoke(bad, "--out", tmp_path / "o.csv")
    _clean_exit(result, 1)
    assert "cannot read" in result.output


def test_directory_input_is_a_clean_error(tmp_path):
    a_dir = tmp_path / "d.csv"
    a_dir.mkdir()
    result = _invoke(a_dir, "--out", tmp_path / "o.csv")
    _clean_exit(result, 1)
    assert "cannot read" in result.output


@pytest.mark.parametrize("doc", [
    "[1, 2]",
    '{"type": "FeatureCollection", "features": [1]}',
    '{"type": "FeatureCollection", "features": "abc"}',
    '{"type": "FeatureCollection", "features": {}}',
])
def test_wrong_shape_geojson_fails_qa(tmp_path, doc):
    src = tmp_path / "c.geojson"
    src.write_text(doc, encoding="utf-8")
    result = _invoke(src, "--out", tmp_path / "o.csv")
    _clean_exit(result, 1)
    assert "geojson_format" in result.output


def test_non_object_properties_and_geometry_ingest(tmp_path):
    src = tmp_path / "c.geojson"
    src.write_text('{"type": "FeatureCollection", "features": '
                   '[{"properties": [1], "geometry": "x"}, '
                   '{"geometry": {"type": "Point", "coordinates": 5}}]}',
                   encoding="utf-8")
    result = _invoke(src, "--out", tmp_path / "o.csv")
    _clean_exit(result, 0)
    assert "geojson_no_geometry" in result.output


def test_unreadable_tracker_is_a_clean_error(tmp_path):
    src = tmp_path / "c.csv"
    src.write_text("comment\nfix label\n", encoding="utf-8")
    tracker = tmp_path / "t.csv"
    tracker.write_bytes(b"comment_id\n\xff\n")
    result = _invoke(src, "--out", tmp_path / "o.csv", "--tracker", tracker)
    _clean_exit(result, 1)
    assert "cannot read" in result.output and str(tracker) in result.output


def test_huge_field_tracker_is_a_clean_error(tmp_path):
    src = tmp_path / "c.csv"
    src.write_text("comment\nfix label\n", encoding="utf-8")
    tracker = tmp_path / "t.csv"
    tracker.write_bytes(b'comment_id\n"' + b"x" * 200_000 + b'"\n')
    result = _invoke(src, "--out", tmp_path / "o.csv", "--tracker", tracker)
    _clean_exit(result, 1)
    assert "cannot read" in result.output


def test_out_under_a_file_is_a_clean_error(tmp_path):
    src = tmp_path / "c.csv"
    src.write_text("comment\nfix label\n", encoding="utf-8")
    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")
    result = _invoke(src, "--out", a_file / "o.csv")
    _clean_exit(result, 1)
    assert "cannot write" in result.output


def test_directory_out_is_a_usage_error(tmp_path):
    src = tmp_path / "c.csv"
    src.write_text("comment\nfix label\n", encoding="utf-8")
    result = _invoke(src, "--out", tmp_path)
    _clean_exit(result, 2)


def test_event_status_unreadable_tracker_is_a_clean_error(tmp_path):
    tracker = tmp_path / "t.csv"
    tracker.write_bytes(b"comment_id\n\xff\n")
    result = CliRunner().invoke(autogis, [
        "envmon", "event-status", "--site-id", "S", "--event-id", "E",
        "--run-history", str(tmp_path / "rh.csv"),
        "--source-registry", str(tmp_path / "reg.csv"),
        "--reviewer-tracker", str(tracker)])
    _clean_exit(result, 1)
    assert "cannot read" in result.output
