"""CLI integration tests for envmon ingest-reviewer-comments (Tool 9.4)."""
import csv
import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from autogis.adapters.cli import autogis


def _write_csv(path: Path, rows: list):
    fieldnames = ["figure_ref", "comment_text", "reviewer", "status"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _read_tracker(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_ingest_reviewer_comments_appears_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "ingest-reviewer-comments" in result.output


def test_ingest_reviewer_comments_csv_creates_tracker(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [
        {"figure_ref": "Figure 3", "comment_text": "Fix north arrow",
         "reviewer": "Alice", "status": "OPEN"},
    ])
    out = tmp_path / "tracker.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    rows = _read_tracker(out)
    assert len(rows) == 1
    assert rows[0]["figure_ref"] == "Figure 3"
    assert rows[0]["reviewer"] == "Alice"
    assert rows[0]["status"] == "OPEN"


def test_ingest_reviewer_comments_output_printed_to_stdout(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [
        {"figure_ref": "Figure 1", "comment_text": "Bold title",
         "reviewer": "Bob", "status": "OPEN"},
    ])
    out = tmp_path / "tracker.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert "1 total" in result.output or "1 comment" in result.output
    assert "OPEN" in result.output


def test_ingest_reviewer_comments_merge_preserves_resolved_status(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [
        {"figure_ref": "Figure 3", "comment_text": "Fix north arrow",
         "reviewer": "Alice", "status": "OPEN"},
    ])
    tracker = tmp_path / "tracker.csv"
    runner = CliRunner()
    runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(tracker),
    ])
    rows = _read_tracker(tracker)
    rows[0]["status"] = "RESOLVED"
    rows[0]["resolution_note"] = "Fixed in v2"
    fieldnames = list(rows[0].keys())
    with tracker.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp),
        "--tracker", str(tracker), "--out", str(tracker),
    ])
    assert result.exit_code == 0, result.output
    merged = _read_tracker(tracker)
    assert len(merged) == 1
    assert merged[0]["status"] == "RESOLVED"
    assert merged[0]["resolution_note"] == "Fixed in v2"


def test_ingest_reviewer_comments_geojson_input(tmp_path):
    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-87.65, 41.85]},
            "properties": {"content": "Check contour interval",
                           "author": "Bob", "figure_ref": "Figure 5"},
        }],
    }
    inp = tmp_path / "review.geojson"
    inp.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "tracker.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    rows = _read_tracker(out)
    assert len(rows) == 1
    assert rows[0]["comment_text"] == "Check contour interval"
    assert float(rows[0]["x"]) == pytest.approx(-87.65)
    assert float(rows[0]["y"]) == pytest.approx(41.85)


def test_ingest_reviewer_comments_multiple_ingests_grow_tracker(tmp_path):
    inp1 = tmp_path / "review1.csv"
    _write_csv(inp1, [{"figure_ref": "F1", "comment_text": "First comment",
                       "reviewer": "Alice", "status": "OPEN"}])
    inp2 = tmp_path / "review2.csv"
    _write_csv(inp2, [{"figure_ref": "F2", "comment_text": "Second comment",
                       "reviewer": "Bob", "status": "OPEN"}])
    tracker = tmp_path / "tracker.csv"
    runner = CliRunner()
    runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp1), "--out", str(tracker),
    ])
    runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp2),
        "--tracker", str(tracker), "--out", str(tracker),
    ])
    rows = _read_tracker(tracker)
    assert len(rows) == 2
    assert {r["comment_text"] for r in rows} == {"First comment", "Second comment"}


def test_ingest_reviewer_comments_unsupported_format_exits_nonzero(tmp_path):
    inp = tmp_path / "review.pdf"
    inp.write_bytes(b"%PDF-fake")
    out = tmp_path / "tracker.csv"
    result = CliRunner().invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert result.exit_code != 0


def test_ingest_reviewer_comments_report_flag_writes_markdown(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [{"figure_ref": "F1", "comment_text": "Fix it",
                      "reviewer": "A", "status": "OPEN"}])
    out = tmp_path / "tracker.csv"
    rpt = tmp_path / "qa.md"
    result = CliRunner().invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp),
        "--out", str(out), "--report", str(rpt),
    ])
    assert result.exit_code == 0, result.output
    assert rpt.exists()
    assert "# " in rpt.read_text(encoding="utf-8")
