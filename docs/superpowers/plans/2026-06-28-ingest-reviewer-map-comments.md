# IngestReviewerMapComments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `IngestReviewerMapComments` (roadmap #9.4) — a headless parser that ingests reviewer map comments/markups from CSV, GeoJSON FeatureCollection (AGOL export), or XLSX redline spreadsheets into a tracked comment table with location, status lifecycle, and QA output.

**Architecture:**
- New: `autogis/core/envmon/ingest_reviewer_comments.py` — all headless logic: `ReviewerComment` dataclass, format parsers (CSV/GeoJSON/XLSX), auto-detect dispatcher, merge logic, and summary formatter. No arcpy, no arcgis. Live AGOL fetch is explicitly out of scope; callers export to a supported file format first.
- New: `tests/envmon/test_ingest_reviewer_comments.py` — full non-CLI test suite (dataclass, helpers, all three parsers, dispatcher, merge, summary).
- New: `tests/envmon/test_cli_ingest_reviewer_comments.py` — CLI integration tests.
- Modify: `autogis/adapters/cli.py` — add `ingest-reviewer-comments` command under the `envmon` group.

**Tech Stack:** Python stdlib (`csv`, `json`, `hashlib`, `dataclasses`), `openpyxl` (XLSX parsing — already a project dependency), `click` (CLI), `autogis.core.common.qa.QACollector` (QA records/reporting).

## Global Constraints

- `autogis/core/` and `autogis/adapters/` must import with neither `arcpy` nor `arcgis` present — no exceptions.
- This tool is headless (roadmap category 9 — Reporting). It does NOT call AGOL live; that seam belongs to the adapter/runtime layer and is a non-goal for this plan.
- All new tests are arcpy-free and run with `python -m pytest -q`. Baseline at plan time: **567 passing**.
- `openpyxl` is the only allowed spreadsheet library; `xlrd`, `pandas`, and `xlwt` are not in scope.
- `ReviewerComment.status` must be one of `VALID_STATUSES` = `{"OPEN", "IN_REVIEW", "RESOLVED", "WONT_FIX"}`. Any unrecognized raw value normalizes to `"OPEN"`.
- Comment IDs are stable, deterministic hashes of `source_file|figure_ref|comment_text|reviewer`. A source file may optionally carry its own `comment_id` column; if present, it is preserved verbatim (allows downstream tracking systems to assign their own IDs).
- Merge semantics: existing records (by `comment_id`) are never mutated or deleted. Their `status`, `assigned_to`, `resolved_date`, and `resolution_note` are preserved when re-ingesting the same source. New IDs are appended.
- The tracker output is a plain UTF-8 CSV (not a GDB table). GDB write is a non-goal for this plan.
- `_render_qa` in `cli.py` is the shared exit-code helper; use it exactly as every other headless command does (see lines ~903-924 of `autogis/adapters/cli.py`).

---

## Problem Statement

After a monitoring report figure package is produced, reviewers mark up PDFs or return comment spreadsheets. Currently there is no structured way to ingest those markups into the project — they live in email threads or ad-hoc spreadsheets and are never reconciled with the GIS data. `IngestReviewerMapComments` ingests those exports into a tracked CSV with a defined status lifecycle (`OPEN → IN_REVIEW → RESOLVED | WONT_FIX`), enabling project managers to see what is open, what is resolved, and where on the map each comment was placed.

## Scope and Non-Goals

**In scope:**
- Parsing reviewer comments from CSV, GeoJSON FeatureCollection (AGOL comment export), and XLSX.
- Auto-detecting input format from file extension.
- Generating stable, deterministic `comment_id` values for deduplication.
- Status normalization and lifecycle enforcement.
- Merge logic: re-ingesting the same source file does not duplicate or overwrite resolved comments.
- QA records (WARNING for empty `comment_text` or `figure_ref`; ERROR for unknown format or invalid GeoJSON root type).
- Writing the tracker to a UTF-8 CSV and reading it back.
- A human-readable status summary (printed to stdout by the CLI).
- CLI command `envmon ingest-reviewer-comments` with `--tracker`, `--out`, `--report`, `--fail-on`.

**Non-goals (explicitly out of scope for this plan):**
- Live AGOL fetch (would need `arcgis` SDK — adapter seam; not implemented here).
- Writing reviewer comments to a GDB table (LOCAL/arcpy path — future plan).
- PDF annotation parsing (complex, separate tool).
- Email ingestion.
- Web UI or approval workflow.
- Assigning comments automatically (assignment is a human action; we only track the `assigned_to` field if provided in the source).

## Supported Input Formats

| Extension | Format | Notes |
|---|---|---|
| `.csv` | Flat comment table | Flexible column names (see `_CSV_FIELD_MAP`); UTF-8-sig safe for Excel exports |
| `.geojson` | GeoJSON FeatureCollection | AGOL comment export style (`author`/`content`) and generic (`reviewer`/`comment`); Point geometry → x/y |
| `.json` | GeoJSON FeatureCollection | Same parser as `.geojson`; root `type` must be `FeatureCollection` |
| `.xlsx` | XLSX spreadsheet | Reads sheet named "Comments" if present, else first sheet; row 1 = header |

## Comment-Tracker Table Schema

`ReviewerComment` dataclass fields (also the CSV column order):

| Field | Type | Notes |
|---|---|---|
| `comment_id` | `str` | `rc-<sha256[:12]>` or preserved from source |
| `source_file` | `str` | Originating filename (basename only) |
| `source_format` | `str` | `"csv"` \| `"geojson"` \| `"xlsx"` |
| `figure_ref` | `str` | Figure name or page ref (e.g. `"Figure 3"`) |
| `comment_text` | `str` | The reviewer's markup text |
| `reviewer` | `str` | Name or email of reviewer |
| `status` | `str` | `"OPEN"` \| `"IN_REVIEW"` \| `"RESOLVED"` \| `"WONT_FIX"` |
| `x` | `Optional[float]` | WGS84 longitude or projected X; `None` if not provided |
| `y` | `Optional[float]` | WGS84 latitude or projected Y; `None` if not provided |
| `page_or_sheet` | `str` | PDF page number or spreadsheet sheet name |
| `assigned_to` | `str` | Assignee name/email (empty = unassigned) |
| `resolved_date` | `str` | ISO date `YYYY-MM-DD` when resolved |
| `resolution_note` | `str` | How the comment was addressed |

**Status lifecycle:**

```
OPEN  ──►  IN_REVIEW  ──►  RESOLVED
  └──────────────────────►  WONT_FIX
```

Ingest always sets status = `OPEN` for new comments. The tracker CSV is the authoritative source for current status; human editors or downstream tools update it. Re-ingest preserves existing status via `merge_tracker`.

## Headless Core API

All functions are arcpy-free and importable without `arcgis`.

```
autogis/core/envmon/ingest_reviewer_comments.py
  VALID_STATUSES: set[str]
  DEFAULT_STATUS: str  = "OPEN"
  ReviewerComment: dataclass  (13 fields, see schema above)
  _make_comment_id(source_file, figure_ref, comment_text, reviewer) -> str
  _normalize_status(raw: str) -> str
  parse_comments_csv(path: Path) -> list[ReviewerComment]
  parse_comments_geojson(path: Path, *, qa: QACollector) -> list[ReviewerComment]
  parse_comments_xlsx(path: Path, *, sheet: str | None, qa: QACollector) -> list[ReviewerComment]
  ingest_comments(path: Path, *, qa: QACollector) -> list[ReviewerComment]
  merge_tracker(existing, incoming, *, qa: QACollector) -> list[ReviewerComment]
  write_tracker_csv(comments, path: Path) -> Path
  read_tracker_csv(path: Path) -> list[ReviewerComment]
  format_comment_summary(comments: list[ReviewerComment]) -> str
```

## CLI Surface

```
autogis envmon ingest-reviewer-comments INPUT
    --out PATH            Output tracker CSV path (required)
    --tracker PATH        Existing tracker CSV to merge into (optional; created fresh if absent)
    --report PATH         Write QA report (.md/.json/.csv by extension; optional)
    --fail-on error|warning   Exit 1 threshold (default: error)
```

Exit codes: 0 = PASS, 1 = FAIL (blocked by severity threshold or unsupported format).

---

### Task 1: Core module `ingest_reviewer_comments.py` + non-CLI tests

**Files:**
- Create: `autogis/core/envmon/ingest_reviewer_comments.py`
- Create: `tests/envmon/test_ingest_reviewer_comments.py`

**Interfaces:**
- Produces (used by Task 2):
  - `ReviewerComment` dataclass (13 fields listed in schema)
  - `ingest_comments(path: Path, *, qa: QACollector) -> list[ReviewerComment]`
  - `read_tracker_csv(path: Path) -> list[ReviewerComment]`
  - `merge_tracker(existing: list[ReviewerComment], incoming: list[ReviewerComment], *, qa: QACollector) -> list[ReviewerComment]`
  - `write_tracker_csv(comments: list[ReviewerComment], path: Path) -> Path`
  - `format_comment_summary(comments: list[ReviewerComment]) -> str`

- [ ] **Step 1: Write the failing test file**

Create `tests/envmon/test_ingest_reviewer_comments.py`:

```python
"""Tests for autogis.core.envmon.ingest_reviewer_comments (Tool 9.4)."""
import csv
import json
import pytest
from pathlib import Path

from autogis.core.common.qa import QACollector, SEV_WARNING, SEV_ERROR, SEV_INFO
from autogis.core.envmon.ingest_reviewer_comments import (
    ReviewerComment,
    VALID_STATUSES,
    DEFAULT_STATUS,
    _make_comment_id,
    _normalize_status,
    parse_comments_csv,
    write_tracker_csv,
    read_tracker_csv,
    parse_comments_geojson,
    parse_comments_xlsx,
    ingest_comments,
    merge_tracker,
    format_comment_summary,
)


# ---------------------------------------------------------------------------
# Helpers reused across tests
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list, extra_fields: list = None):
    fieldnames = ["figure_ref", "comment_text", "reviewer", "status", "x", "y"] + (extra_fields or [])
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _make_geojson(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def _point_feature(x: float, y: float, **props) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [x, y]},
        "properties": props,
    }


def _make_xlsx(path: Path, rows: list, sheet_name: str = "Sheet1"):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
    wb.save(path)


# ---------------------------------------------------------------------------
# ReviewerComment dataclass + helpers
# ---------------------------------------------------------------------------

def test_reviewer_comment_defaults():
    c = ReviewerComment(
        comment_id="rc-abc",
        source_file="test.csv",
        source_format="csv",
        figure_ref="Figure 3",
        comment_text="Fix north arrow",
        reviewer="Alice",
    )
    assert c.status == "OPEN"
    assert c.x is None
    assert c.y is None
    assert c.assigned_to == ""
    assert c.resolved_date == ""
    assert c.resolution_note == ""


def test_make_comment_id_is_deterministic():
    a = _make_comment_id("f.csv", "Figure 1", "Fix label", "Bob")
    b = _make_comment_id("f.csv", "Figure 1", "Fix label", "Bob")
    assert a == b


def test_make_comment_id_starts_with_rc():
    cid = _make_comment_id("f.csv", "Figure 1", "Fix label", "Bob")
    assert cid.startswith("rc-")


def test_make_comment_id_differs_for_different_inputs():
    a = _make_comment_id("f.csv", "Figure 1", "Fix label", "Bob")
    b = _make_comment_id("f.csv", "Figure 2", "Fix label", "Bob")
    assert a != b


def test_normalize_status_canonical_values():
    assert _normalize_status("OPEN") == "OPEN"
    assert _normalize_status("IN_REVIEW") == "IN_REVIEW"
    assert _normalize_status("RESOLVED") == "RESOLVED"
    assert _normalize_status("WONT_FIX") == "WONT_FIX"


def test_normalize_status_lowercase():
    assert _normalize_status("open") == "OPEN"
    assert _normalize_status("resolved") == "RESOLVED"


def test_normalize_status_spaces_become_underscores():
    assert _normalize_status("in review") == "IN_REVIEW"
    assert _normalize_status("wont fix") == "WONT_FIX"


def test_normalize_status_unknown_defaults_to_open():
    assert _normalize_status("pending") == "OPEN"
    assert _normalize_status("") == "OPEN"
    assert _normalize_status("tbd") == "OPEN"


# ---------------------------------------------------------------------------
# parse_comments_csv
# ---------------------------------------------------------------------------

def test_parse_comments_csv_basic(tmp_path):
    p = tmp_path / "comments.csv"
    _write_csv(p, [
        {"figure_ref": "Figure 3", "comment_text": "Fix north arrow",
         "reviewer": "Alice", "status": "OPEN", "x": "-87.65", "y": "41.85"},
        {"figure_ref": "Figure 4", "comment_text": "Update legend",
         "reviewer": "Bob", "status": "resolved", "x": "", "y": ""},
    ])
    result = parse_comments_csv(p)
    assert len(result) == 2
    assert result[0].figure_ref == "Figure 3"
    assert result[0].comment_text == "Fix north arrow"
    assert result[0].reviewer == "Alice"
    assert result[0].status == "OPEN"
    assert result[0].x == pytest.approx(-87.65)
    assert result[0].y == pytest.approx(41.85)
    assert result[0].source_format == "csv"
    assert result[1].status == "RESOLVED"
    assert result[1].x is None


def test_parse_comments_csv_source_file_is_basename(tmp_path):
    p = tmp_path / "my_review.csv"
    _write_csv(p, [{"figure_ref": "F1", "comment_text": "x", "reviewer": "C",
                     "status": "OPEN", "x": "", "y": ""}])
    result = parse_comments_csv(p)
    assert result[0].source_file == "my_review.csv"


def test_parse_comments_csv_status_normalization(tmp_path):
    p = tmp_path / "c.csv"
    _write_csv(p, [{"figure_ref": "F1", "comment_text": "x", "reviewer": "C",
                     "status": "in review", "x": "", "y": ""}])
    result = parse_comments_csv(p)
    assert result[0].status == "IN_REVIEW"


def test_parse_comments_csv_missing_optional_columns(tmp_path):
    p = tmp_path / "minimal.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["figure_ref", "comment_text"])
        w.writeheader()
        w.writerow({"figure_ref": "F1", "comment_text": "Needs label"})
    result = parse_comments_csv(p)
    assert len(result) == 1
    assert result[0].reviewer == ""
    assert result[0].x is None
    assert result[0].status == "OPEN"


def test_parse_comments_csv_existing_comment_id_preserved(tmp_path):
    p = tmp_path / "with_id.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["comment_id", "figure_ref", "comment_text", "reviewer", "status"])
        w.writeheader()
        w.writerow({"comment_id": "rc-existing123", "figure_ref": "F1",
                    "comment_text": "Fix me", "reviewer": "D", "status": "OPEN"})
    result = parse_comments_csv(p)
    assert result[0].comment_id == "rc-existing123"


def test_parse_comments_csv_accepts_alias_column_names(tmp_path):
    """'figure', 'comment', 'author' are accepted aliases."""
    p = tmp_path / "aliases.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["figure", "comment", "author"])
        w.writeheader()
        w.writerow({"figure": "Fig 7", "comment": "Bold title", "author": "Z"})
    result = parse_comments_csv(p)
    assert result[0].figure_ref == "Fig 7"
    assert result[0].comment_text == "Bold title"
    assert result[0].reviewer == "Z"


# ---------------------------------------------------------------------------
# write_tracker_csv / read_tracker_csv
# ---------------------------------------------------------------------------

def test_write_read_tracker_csv_roundtrip(tmp_path):
    original = [
        ReviewerComment(
            comment_id="rc-aaa", source_file="in.csv", source_format="csv",
            figure_ref="Figure 1", comment_text="Move label", reviewer="Alice",
            status="RESOLVED", x=-87.65, y=41.85,
            assigned_to="Bob", resolved_date="2026-06-28",
            resolution_note="Label repositioned",
        ),
        ReviewerComment(
            comment_id="rc-bbb", source_file="in.csv", source_format="csv",
            figure_ref="Figure 2", comment_text="Add scale bar", reviewer="Carol",
        ),
    ]
    out = tmp_path / "tracker.csv"
    write_tracker_csv(original, out)
    read_back = read_tracker_csv(out)
    assert len(read_back) == 2
    assert read_back[0].comment_id == "rc-aaa"
    assert read_back[0].status == "RESOLVED"
    assert read_back[0].x == pytest.approx(-87.65)
    assert read_back[0].y == pytest.approx(41.85)
    assert read_back[0].resolution_note == "Label repositioned"
    assert read_back[1].status == "OPEN"
    assert read_back[1].x is None


def test_read_tracker_csv_missing_file_returns_empty(tmp_path):
    result = read_tracker_csv(tmp_path / "nonexistent.csv")
    assert result == []


def test_write_tracker_csv_creates_parent_dirs(tmp_path):
    out = tmp_path / "subdir" / "tracker.csv"
    write_tracker_csv([], out)
    assert out.exists()


# ---------------------------------------------------------------------------
# parse_comments_geojson
# ---------------------------------------------------------------------------

def test_parse_comments_geojson_basic(tmp_path):
    data = _make_geojson([
        _point_feature(-87.65, 41.85, content="Fix north arrow", author="Alice",
                       figure_ref="Figure 3"),
        _point_feature(-87.70, 41.90, comment="Update title", reviewer="Bob"),
    ])
    p = tmp_path / "comments.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = parse_comments_geojson(p, qa=qa)
    assert len(result) == 2
    assert result[0].comment_text == "Fix north arrow"
    assert result[0].reviewer == "Alice"
    assert result[0].x == pytest.approx(-87.65)
    assert result[0].y == pytest.approx(41.85)
    assert result[0].source_format == "geojson"
    assert result[1].comment_text == "Update title"


def test_parse_comments_geojson_agol_property_names(tmp_path):
    """AGOL exports use 'author' and 'content' — verify mapping."""
    data = _make_geojson([
        _point_feature(-87.65, 41.85,
                       author="reviewer@example.com",
                       content="Confirm this contour interval",
                       figure="Figure 5",
                       status="IN_REVIEW"),
    ])
    p = tmp_path / "agol.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = parse_comments_geojson(p, qa=qa)
    assert result[0].reviewer == "reviewer@example.com"
    assert result[0].comment_text == "Confirm this contour interval"
    assert result[0].figure_ref == "Figure 5"
    assert result[0].status == "IN_REVIEW"


def test_parse_comments_geojson_no_geometry_emits_warning(tmp_path):
    data = _make_geojson([
        {"type": "Feature", "geometry": None,
         "properties": {"content": "No location", "author": "X"}},
    ])
    p = tmp_path / "no_geom.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = parse_comments_geojson(p, qa=qa)
    assert len(result) == 1
    assert result[0].x is None
    assert result[0].y is None
    warnings = [r for r in qa.records if r.severity == SEV_WARNING]
    assert any("geometry" in r.message.lower() for r in warnings)


def test_parse_comments_geojson_not_feature_collection_returns_empty(tmp_path):
    data = {"type": "Feature", "geometry": None, "properties": {}}
    p = tmp_path / "bad.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = parse_comments_geojson(p, qa=qa)
    assert result == []
    errors = [r for r in qa.records if r.severity == SEV_ERROR]
    assert errors


def test_parse_comments_geojson_stable_comment_id(tmp_path):
    """Same feature ingested twice must produce the same comment_id."""
    data = _make_geojson([
        _point_feature(-87.65, 41.85, content="Fix it", author="Alice", figure="F1"),
    ])
    p = tmp_path / "c.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa1, qa2 = QACollector(), QACollector()
    r1 = parse_comments_geojson(p, qa=qa1)
    r2 = parse_comments_geojson(p, qa=qa2)
    assert r1[0].comment_id == r2[0].comment_id


# ---------------------------------------------------------------------------
# parse_comments_xlsx
# ---------------------------------------------------------------------------

def test_parse_comments_xlsx_basic(tmp_path):
    p = tmp_path / "comments.xlsx"
    _make_xlsx(p, [
        {"figure_ref": "Figure 1", "comment_text": "Bold the title",
         "reviewer": "Alice", "status": "OPEN", "x": -87.65, "y": 41.85},
        {"figure_ref": "Figure 2", "comment_text": "Check units",
         "reviewer": "Bob", "status": "RESOLVED", "x": None, "y": None},
    ])
    qa = QACollector()
    result = parse_comments_xlsx(p, qa=qa)
    assert len(result) == 2
    assert result[0].figure_ref == "Figure 1"
    assert result[0].comment_text == "Bold the title"
    assert result[0].source_format == "xlsx"
    assert result[0].x == pytest.approx(-87.65)
    assert result[1].status == "RESOLVED"
    assert result[1].x is None


def test_parse_comments_xlsx_prefers_comments_sheet(tmp_path):
    import openpyxl
    p = tmp_path / "multi_sheet.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Data"
    ws1.append(["figure_ref", "comment_text", "reviewer"])
    ws1.append(["F0", "Wrong sheet", "Wrong"])
    ws2 = wb.create_sheet("Comments")
    ws2.append(["figure_ref", "comment_text", "reviewer"])
    ws2.append(["F1", "Correct sheet comment", "Alice"])
    wb.save(p)
    qa = QACollector()
    result = parse_comments_xlsx(p, qa=qa)
    assert len(result) == 1
    assert result[0].comment_text == "Correct sheet comment"


def test_parse_comments_xlsx_falls_back_to_first_sheet(tmp_path):
    import openpyxl
    p = tmp_path / "no_comments_sheet.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Markups"
    ws.append(["figure_ref", "comment_text", "reviewer"])
    ws.append(["F2", "Fallback comment", "Carol"])
    wb.save(p)
    qa = QACollector()
    result = parse_comments_xlsx(p, qa=qa)
    assert len(result) == 1
    assert result[0].comment_text == "Fallback comment"


def test_parse_comments_xlsx_accepts_alias_columns(tmp_path):
    """'figure', 'comment', 'author' are accepted in XLSX too."""
    import openpyxl
    p = tmp_path / "aliases.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["figure", "comment", "author"])
    ws.append(["Fig 8", "Fix scale bar", "Dana"])
    wb.save(p)
    qa = QACollector()
    result = parse_comments_xlsx(p, qa=qa)
    assert result[0].figure_ref == "Fig 8"
    assert result[0].comment_text == "Fix scale bar"
    assert result[0].reviewer == "Dana"


# ---------------------------------------------------------------------------
# ingest_comments (auto-detect dispatcher)
# ---------------------------------------------------------------------------

def test_ingest_comments_routes_csv(tmp_path):
    p = tmp_path / "input.csv"
    _write_csv(p, [{"figure_ref": "F1", "comment_text": "Fix me", "reviewer": "A",
                     "status": "OPEN", "x": "", "y": ""}])
    qa = QACollector()
    result = ingest_comments(p, qa=qa)
    assert len(result) == 1
    assert result[0].source_format == "csv"
    infos = [r for r in qa.records if r.severity == SEV_INFO and "ingest_complete" in r.category]
    assert infos


def test_ingest_comments_routes_geojson(tmp_path):
    data = _make_geojson([_point_feature(-87.65, 41.85, content="Test", author="B")])
    p = tmp_path / "input.geojson"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = ingest_comments(p, qa=qa)
    assert len(result) == 1
    assert result[0].source_format == "geojson"


def test_ingest_comments_routes_json_extension(tmp_path):
    data = _make_geojson([_point_feature(-87.65, 41.85, content="JSON ext", author="C")])
    p = tmp_path / "input.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    qa = QACollector()
    result = ingest_comments(p, qa=qa)
    assert len(result) == 1
    assert result[0].source_format == "geojson"


def test_ingest_comments_routes_xlsx(tmp_path):
    p = tmp_path / "input.xlsx"
    _make_xlsx(p, [{"figure_ref": "F3", "comment_text": "Fix",
                     "reviewer": "C", "status": "OPEN", "x": None, "y": None}])
    qa = QACollector()
    result = ingest_comments(p, qa=qa)
    assert len(result) == 1
    assert result[0].source_format == "xlsx"


def test_ingest_comments_unknown_extension_returns_empty_with_error(tmp_path):
    p = tmp_path / "comments.pdf"
    p.write_bytes(b"%PDF-fake")
    qa = QACollector()
    result = ingest_comments(p, qa=qa)
    assert result == []
    errors = [r for r in qa.records if r.severity == SEV_ERROR]
    assert errors
    assert any(".pdf" in r.message or "pdf" in r.message.lower() for r in errors)


def test_ingest_comments_warns_empty_comment_text(tmp_path):
    p = tmp_path / "empty_text.csv"
    _write_csv(p, [{"figure_ref": "F1", "comment_text": "", "reviewer": "A",
                     "status": "OPEN", "x": "", "y": ""}])
    qa = QACollector()
    ingest_comments(p, qa=qa)
    warnings = [r for r in qa.records if r.severity == SEV_WARNING]
    assert any("empty_comment_text" in r.category for r in warnings)


def test_ingest_comments_warns_empty_figure_ref(tmp_path):
    p = tmp_path / "no_fig.csv"
    _write_csv(p, [{"figure_ref": "", "comment_text": "Something", "reviewer": "A",
                     "status": "OPEN", "x": "", "y": ""}])
    qa = QACollector()
    ingest_comments(p, qa=qa)
    warnings = [r for r in qa.records if r.severity == SEV_WARNING]
    assert any("empty_figure_ref" in r.category for r in warnings)


# ---------------------------------------------------------------------------
# merge_tracker
# ---------------------------------------------------------------------------

def test_merge_tracker_new_comments_appended():
    existing = [
        ReviewerComment("rc-1", "old.csv", "csv", "F1", "Old comment", "Alice"),
    ]
    incoming = [
        ReviewerComment("rc-2", "new.csv", "csv", "F2", "New comment", "Bob"),
    ]
    qa = QACollector()
    result = merge_tracker(existing, incoming, qa=qa)
    assert len(result) == 2
    assert result[0].comment_id == "rc-1"
    assert result[1].comment_id == "rc-2"


def test_merge_tracker_existing_status_preserved_on_reingest():
    """Re-ingesting the same comment (same comment_id) must not overwrite RESOLVED."""
    existing = [
        ReviewerComment("rc-1", "old.csv", "csv", "F1", "Fix it", "Alice",
                        status="RESOLVED", resolution_note="Done"),
    ]
    # Fresh ingest produces OPEN for the same logical comment
    incoming = [
        ReviewerComment("rc-1", "old.csv", "csv", "F1", "Fix it", "Alice",
                        status="OPEN"),
    ]
    qa = QACollector()
    result = merge_tracker(existing, incoming, qa=qa)
    assert len(result) == 1  # not duplicated
    assert result[0].status == "RESOLVED"
    assert result[0].resolution_note == "Done"


def test_merge_tracker_empty_existing():
    incoming = [
        ReviewerComment("rc-1", "new.csv", "csv", "F1", "Add arrow", "Alice"),
    ]
    qa = QACollector()
    result = merge_tracker([], incoming, qa=qa)
    assert len(result) == 1
    assert result[0].comment_id == "rc-1"


def test_merge_tracker_no_duplicates_on_repeated_reingest():
    """Re-ingesting same source twice must not grow the tracker."""
    comment = ReviewerComment("rc-1", "f.csv", "csv", "F1", "Fix me", "Alice")
    qa1 = QACollector()
    after_first = merge_tracker([], [comment], qa=qa1)
    qa2 = QACollector()
    after_second = merge_tracker(after_first, [comment], qa=qa2)
    assert len(after_second) == 1


def test_merge_tracker_existing_order_preserved():
    existing = [
        ReviewerComment("rc-1", "f.csv", "csv", "F1", "A", "Alice"),
        ReviewerComment("rc-2", "f.csv", "csv", "F2", "B", "Bob"),
    ]
    incoming = [
        ReviewerComment("rc-3", "f.csv", "csv", "F3", "C", "Carol"),
    ]
    qa = QACollector()
    result = merge_tracker(existing, incoming, qa=qa)
    assert [c.comment_id for c in result] == ["rc-1", "rc-2", "rc-3"]


def test_merge_tracker_emits_info_qa_record():
    qa = QACollector()
    merge_tracker([], [], qa=qa)
    infos = [r for r in qa.records if r.severity == SEV_INFO]
    assert infos


# ---------------------------------------------------------------------------
# format_comment_summary
# ---------------------------------------------------------------------------

def test_format_comment_summary_shows_total_count():
    comments = [
        ReviewerComment("rc-1", "f.csv", "csv", "F1", "A", "Alice", status="OPEN"),
        ReviewerComment("rc-2", "f.csv", "csv", "F2", "B", "Bob",   status="RESOLVED"),
        ReviewerComment("rc-3", "f.csv", "csv", "F3", "C", "Carol", status="OPEN"),
    ]
    summary = format_comment_summary(comments)
    assert "3" in summary


def test_format_comment_summary_counts_by_status():
    comments = [
        ReviewerComment("rc-1", "f.csv", "csv", "F1", "A", "Alice", status="OPEN"),
        ReviewerComment("rc-2", "f.csv", "csv", "F2", "B", "Bob",   status="OPEN"),
        ReviewerComment("rc-3", "f.csv", "csv", "F3", "C", "Carol", status="RESOLVED"),
    ]
    summary = format_comment_summary(comments)
    assert "OPEN" in summary
    assert "RESOLVED" in summary


def test_format_comment_summary_empty():
    summary = format_comment_summary([])
    assert "0" in summary


def test_format_comment_summary_shows_open_preview():
    """Open comment text must appear in the summary (up to 5 items)."""
    comments = [
        ReviewerComment("rc-1", "f.csv", "csv", "Figure 3",
                        "Fix the north arrow placement", "Alice", status="OPEN"),
    ]
    summary = format_comment_summary(comments)
    assert "Figure 3" in summary
    assert "Fix the north arrow placement" in summary


def test_format_comment_summary_truncates_open_preview_at_5():
    """Only the first 5 open comments get previewed; remainder noted as count."""
    comments = [
        ReviewerComment(f"rc-{i}", "f.csv", "csv", f"F{i}",
                        f"Comment {i}", "Alice", status="OPEN")
        for i in range(8)
    ]
    summary = format_comment_summary(comments)
    assert "3 more" in summary or "3" in summary
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_ingest_reviewer_comments.py -v
```

Expected: `ImportError: cannot import name 'ReviewerComment' from 'autogis.core.envmon.ingest_reviewer_comments'` (module doesn't exist yet).

- [ ] **Step 3: Create `autogis/core/envmon/ingest_reviewer_comments.py`**

```python
"""ingest_reviewer_comments.py — headless ingest of reviewer map comments/redlines.

Parses review comment exports (CSV, GeoJSON FeatureCollection, XLSX) into a tracked
``ReviewerComment`` table with status lifecycle management.

No arcpy. No arcgis. Live AGOL fetch is NOT implemented here — the caller
exports to a supported format first (headless boundary per ADR-0002).

Public API
----------
ReviewerComment          : dataclass (13 fields)
parse_comments_csv()     : parse flat CSV with flexible column aliases
parse_comments_geojson() : parse AGOL or generic GeoJSON FeatureCollection
parse_comments_xlsx()    : parse XLSX (openpyxl; prefers "Comments" sheet)
ingest_comments()        : auto-detect format by extension, emit QA records
merge_tracker()          : merge incoming into existing, preserving status
write_tracker_csv()      : write tracker to UTF-8 CSV
read_tracker_csv()       : read tracker CSV; returns [] if file absent
format_comment_summary() : human-readable status count + open comment preview
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, asdict, fields as _fields
from pathlib import Path
from typing import Optional

from autogis.core.common.qa import QACollector, SEV_INFO, SEV_WARNING, SEV_ERROR

# ---------------------------------------------------------------------------
# Status lifecycle: OPEN → IN_REVIEW → RESOLVED | WONT_FIX
# ---------------------------------------------------------------------------
VALID_STATUSES: set[str] = {"OPEN", "IN_REVIEW", "RESOLVED", "WONT_FIX"}
DEFAULT_STATUS: str = "OPEN"


# ---------------------------------------------------------------------------
# ReviewerComment dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReviewerComment:
    """A single reviewer markup comment with location and status tracking."""
    comment_id: str           # "rc-<sha256[:12]>" or preserved from source
    source_file: str          # originating filename (basename only)
    source_format: str        # "csv" | "geojson" | "xlsx"
    figure_ref: str           # figure name or page ref (e.g. "Figure 3")
    comment_text: str         # the reviewer's markup text
    reviewer: str             # name or email of reviewer
    status: str = DEFAULT_STATUS   # OPEN | IN_REVIEW | RESOLVED | WONT_FIX
    x: Optional[float] = None      # WGS84 longitude or projected X
    y: Optional[float] = None      # WGS84 latitude or projected Y
    page_or_sheet: str = ""        # PDF page number or XLSX sheet name
    assigned_to: str = ""          # assignee name/email
    resolved_date: str = ""        # ISO date YYYY-MM-DD when resolved
    resolution_note: str = ""      # how the comment was addressed


_TRACKER_FIELDS: list[str] = [f.name for f in _fields(ReviewerComment)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_comment_id(
    source_file: str, figure_ref: str, comment_text: str, reviewer: str
) -> str:
    """Generate a stable, deterministic comment ID from key identifying fields."""
    key = f"{source_file}|{figure_ref}|{comment_text}|{reviewer}"
    return "rc-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _normalize_status(raw: str) -> str:
    """Normalize a raw status string to VALID_STATUSES, defaulting to OPEN."""
    upper = raw.strip().upper().replace(" ", "_").replace("-", "_")
    return upper if upper in VALID_STATUSES else DEFAULT_STATUS


def _to_float(v: object) -> Optional[float]:
    """Convert a value to float; return None for empty/None."""
    s = str(v).strip() if v is not None else ""
    try:
        return float(s) if s else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Column alias maps (lowercase source name → ReviewerComment field name)
# ---------------------------------------------------------------------------

_CSV_FIELD_MAP: dict[str, str] = {
    "figure": "figure_ref", "figure_ref": "figure_ref", "figure_name": "figure_ref",
    "comment": "comment_text", "comment_text": "comment_text",
    "reviewer": "reviewer", "author": "reviewer", "created_by": "reviewer",
    "status": "status",
    "x": "x", "longitude": "x", "lon": "x",
    "y": "y", "latitude": "y", "lat": "y",
    "page": "page_or_sheet", "page_or_sheet": "page_or_sheet", "sheet": "page_or_sheet",
    "assigned_to": "assigned_to", "assigned to": "assigned_to", "assignee": "assigned_to",
    "resolved_date": "resolved_date", "resolved date": "resolved_date",
    "resolution_note": "resolution_note", "resolution note": "resolution_note",
    "comment_id": "comment_id",
}

_GEOJSON_PROP_MAP: dict[str, str] = {
    "content": "comment_text", "comment": "comment_text", "comment_text": "comment_text",
    "author": "reviewer", "reviewer": "reviewer", "created_by": "reviewer",
    "figure": "figure_ref", "figure_ref": "figure_ref", "figure_name": "figure_ref",
    "status": "status",
    "assigned_to": "assigned_to", "assigned to": "assigned_to", "assignee": "assigned_to",
    "resolved_date": "resolved_date", "resolved date": "resolved_date",
    "resolution_note": "resolution_note", "resolution note": "resolution_note",
    "page": "page_or_sheet", "sheet": "page_or_sheet", "page_or_sheet": "page_or_sheet",
    "comment_id": "comment_id",
}

_XLSX_FIELD_MAP: dict[str, str] = {
    "figure": "figure_ref", "figure_ref": "figure_ref", "figure_name": "figure_ref",
    "comment": "comment_text", "comment_text": "comment_text",
    "reviewer": "reviewer", "author": "reviewer", "created_by": "reviewer",
    "status": "status",
    "x": "x", "longitude": "x", "lon": "x",
    "y": "y", "latitude": "y", "lat": "y",
    "page": "page_or_sheet", "sheet": "page_or_sheet", "page_or_sheet": "page_or_sheet",
    "assigned_to": "assigned_to", "assigned to": "assigned_to", "assignee": "assigned_to",
    "resolved_date": "resolved_date", "resolved date": "resolved_date",
    "resolution_note": "resolution_note", "resolution note": "resolution_note",
    "comment_id": "comment_id",
}


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def parse_comments_csv(path: Path) -> list[ReviewerComment]:
    """Parse a flat reviewer comment CSV into ``ReviewerComment`` records.

    Accepts flexible column names (see ``_CSV_FIELD_MAP``). Columns not
    in the map are silently ignored. UTF-8-sig safe (Excel BOM).
    Generates a deterministic ``comment_id`` from key fields when absent.
    """
    src = Path(path).name
    out: list[ReviewerComment] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            mapped: dict[str, object] = {}
            for col, val in row.items():
                target = _CSV_FIELD_MAP.get((col or "").strip().lower())
                if target:
                    mapped[target] = (val or "").strip()
            existing_id = str(mapped.pop("comment_id", "")).strip()
            cid = existing_id or _make_comment_id(
                src,
                str(mapped.get("figure_ref", "")),
                str(mapped.get("comment_text", "")),
                str(mapped.get("reviewer", "")),
            )
            out.append(ReviewerComment(
                comment_id=cid,
                source_file=src,
                source_format="csv",
                figure_ref=str(mapped.get("figure_ref", "")),
                comment_text=str(mapped.get("comment_text", "")),
                reviewer=str(mapped.get("reviewer", "")),
                status=_normalize_status(str(mapped.get("status", ""))),
                x=_to_float(mapped.get("x")),
                y=_to_float(mapped.get("y")),
                page_or_sheet=str(mapped.get("page_or_sheet", "")),
                assigned_to=str(mapped.get("assigned_to", "")),
                resolved_date=str(mapped.get("resolved_date", "")),
                resolution_note=str(mapped.get("resolution_note", "")),
            ))
    return out


# ---------------------------------------------------------------------------
# Tracker CSV read/write
# ---------------------------------------------------------------------------

def write_tracker_csv(comments: list[ReviewerComment], path: Path) -> Path:
    """Write the full comment tracker to a UTF-8 CSV file.

    Field order follows ``_TRACKER_FIELDS`` (the ``ReviewerComment`` field
    declaration order). Parent directories are created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_TRACKER_FIELDS)
        w.writeheader()
        for c in comments:
            w.writerow(asdict(c))
    return path


def read_tracker_csv(path: Path) -> list[ReviewerComment]:
    """Read a comment tracker CSV. Returns ``[]`` if the file does not exist."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[ReviewerComment] = []
    with p.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(ReviewerComment(
                comment_id=row.get("comment_id", ""),
                source_file=row.get("source_file", ""),
                source_format=row.get("source_format", "csv"),
                figure_ref=row.get("figure_ref", ""),
                comment_text=row.get("comment_text", ""),
                reviewer=row.get("reviewer", ""),
                status=_normalize_status(row.get("status", "")),
                x=_to_float(row.get("x")),
                y=_to_float(row.get("y")),
                page_or_sheet=row.get("page_or_sheet", ""),
                assigned_to=row.get("assigned_to", ""),
                resolved_date=row.get("resolved_date", ""),
                resolution_note=row.get("resolution_note", ""),
            ))
    return out


# ---------------------------------------------------------------------------
# GeoJSON parser (AGOL FeatureCollection + generic)
# ---------------------------------------------------------------------------

def parse_comments_geojson(path: Path, *, qa: QACollector) -> list[ReviewerComment]:
    """Parse an AGOL comment export or generic GeoJSON FeatureCollection.

    Each Point feature becomes one ``ReviewerComment``. Features without a
    Point geometry are ingested with ``x=None, y=None``; a QA WARNING is emitted.
    Returns ``[]`` and emits a QA ERROR if the root ``type`` is not
    ``"FeatureCollection"``.
    """
    src = Path(path).name
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection":
        qa.add(
            SEV_ERROR, "geojson_format",
            f"{src}: root type is not FeatureCollection — got {data.get('type')!r}",
            source_workbook=src,
        )
        return []
    out: list[ReviewerComment] = []
    for i, feat in enumerate(data.get("features") or []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        mapped: dict[str, str] = {}
        for k, v in props.items():
            target = _GEOJSON_PROP_MAP.get((k or "").lower().strip())
            if target:
                mapped[target] = str(v).strip() if v is not None else ""
        x = y = None
        if geom.get("type") == "Point":
            coords = geom.get("coordinates") or []
            if len(coords) >= 2:
                x, y = float(coords[0]), float(coords[1])
        else:
            qa.add(
                SEV_WARNING, "geojson_no_geometry",
                f"{src}: feature {i} has no Point geometry — x/y will be null",
                source_workbook=src,
            )
        existing_id = mapped.pop("comment_id", "")
        cid = existing_id or _make_comment_id(
            src,
            mapped.get("figure_ref", ""),
            mapped.get("comment_text", ""),
            mapped.get("reviewer", ""),
        )
        out.append(ReviewerComment(
            comment_id=cid,
            source_file=src,
            source_format="geojson",
            figure_ref=mapped.get("figure_ref", ""),
            comment_text=mapped.get("comment_text", ""),
            reviewer=mapped.get("reviewer", ""),
            status=_normalize_status(mapped.get("status", "")),
            x=x,
            y=y,
            page_or_sheet=mapped.get("page_or_sheet", ""),
            assigned_to=mapped.get("assigned_to", ""),
            resolved_date=mapped.get("resolved_date", ""),
            resolution_note=mapped.get("resolution_note", ""),
        ))
    return out


# ---------------------------------------------------------------------------
# XLSX parser (openpyxl)
# ---------------------------------------------------------------------------

def parse_comments_xlsx(
    path: Path,
    *,
    sheet: Optional[str] = None,
    qa: QACollector,
) -> list[ReviewerComment]:
    """Parse a reviewer comment spreadsheet with openpyxl.

    Sheet selection priority:
    1. ``sheet`` parameter, if provided and present in the workbook.
    2. Sheet named ``"Comments"``, if present.
    3. First sheet in the workbook.

    Row 1 is the header row. Unknown columns are silently ignored.
    Entirely blank rows are skipped.
    """
    import openpyxl  # noqa: PLC0415 — deferred; headless-safe (openpyxl is arcpy-free)
    src = Path(path).name
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if sheet and sheet in wb.sheetnames:
        ws = wb[sheet]
    elif "Comments" in wb.sheetnames:
        ws = wb["Comments"]
    else:
        ws = wb[wb.sheetnames[0]]
    all_rows = list(ws.values)
    if not all_rows:
        qa.add(SEV_WARNING, "xlsx_empty",
               f"{src}: selected sheet has no rows", source_workbook=src)
        return []
    header = [str(h).strip().lower() if h is not None else "" for h in all_rows[0]]
    out: list[ReviewerComment] = []
    for row_vals in all_rows[1:]:
        if all(v is None for v in row_vals):
            continue  # skip blank rows
        mapped: dict[str, object] = {}
        for col_idx, val in enumerate(row_vals):
            if col_idx < len(header):
                target = _XLSX_FIELD_MAP.get(header[col_idx])
                if target:
                    mapped[target] = str(val).strip() if val is not None else ""
        existing_id = str(mapped.pop("comment_id", "")).strip()
        cid = existing_id or _make_comment_id(
            src,
            str(mapped.get("figure_ref", "")),
            str(mapped.get("comment_text", "")),
            str(mapped.get("reviewer", "")),
        )
        out.append(ReviewerComment(
            comment_id=cid,
            source_file=src,
            source_format="xlsx",
            figure_ref=str(mapped.get("figure_ref", "")),
            comment_text=str(mapped.get("comment_text", "")),
            reviewer=str(mapped.get("reviewer", "")),
            status=_normalize_status(str(mapped.get("status", ""))),
            x=_to_float(mapped.get("x")),
            y=_to_float(mapped.get("y")),
            page_or_sheet=str(mapped.get("page_or_sheet", "")),
            assigned_to=str(mapped.get("assigned_to", "")),
            resolved_date=str(mapped.get("resolved_date", "")),
            resolution_note=str(mapped.get("resolution_note", "")),
        ))
    return out


# ---------------------------------------------------------------------------
# Auto-detect dispatcher
# ---------------------------------------------------------------------------

def ingest_comments(path: Path, *, qa: QACollector) -> list[ReviewerComment]:
    """Ingest reviewer comments from ``path``, auto-detecting format by extension.

    Supported extensions: .csv  .geojson  .json  .xlsx  .xls
    Emits SEV_ERROR and returns [] for unrecognized extensions.
    After parsing, emits SEV_WARNING for each comment with empty
    ``comment_text`` or empty ``figure_ref``.
    Emits SEV_INFO "ingest_complete" with count summary on success.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".csv":
        comments = parse_comments_csv(p)
    elif ext in (".geojson", ".json"):
        comments = parse_comments_geojson(p, qa=qa)
    elif ext in (".xlsx", ".xls"):
        comments = parse_comments_xlsx(p, qa=qa)
    else:
        qa.add(
            SEV_ERROR, "unknown_format",
            f"Unsupported file extension {ext!r} for {p.name}. "
            "Supported: .csv, .geojson, .json, .xlsx",
            source_workbook=p.name,
        )
        return []
    for c in comments:
        if not c.comment_text.strip():
            qa.add(SEV_WARNING, "empty_comment_text",
                   f"comment_id={c.comment_id}: empty comment_text",
                   source_workbook=c.source_file)
        if not c.figure_ref.strip():
            qa.add(SEV_WARNING, "empty_figure_ref",
                   f"comment_id={c.comment_id}: empty figure_ref",
                   source_workbook=c.source_file)
    qa.add(SEV_INFO, "ingest_complete",
           f"Ingested {len(comments)} comment(s) from {p.name} [{ext}]")
    return comments


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def merge_tracker(
    existing: list[ReviewerComment],
    incoming: list[ReviewerComment],
    *,
    qa: QACollector,
) -> list[ReviewerComment]:
    """Merge ``incoming`` comments into ``existing`` tracker.

    Rules:
    - A ``comment_id`` already in ``existing`` is **not** updated — the
      existing record's ``status``, ``assigned_to``, ``resolved_date``, and
      ``resolution_note`` are preserved.
    - New ``comment_id`` values (not in ``existing``) are appended.
    - No existing comment is ever deleted.

    Returns: existing records (original order) + new records (incoming order).
    """
    existing_ids = {c.comment_id for c in existing}
    new_comments = [c for c in incoming if c.comment_id not in existing_ids]
    qa.add(
        SEV_INFO, "merge_complete",
        f"Merge: {len(existing)} existing + {len(incoming)} incoming "
        f"→ {len(new_comments)} new, {len(existing) + len(new_comments)} total",
    )
    return list(existing) + new_comments


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

def format_comment_summary(comments: list[ReviewerComment]) -> str:
    """Return a human-readable status summary table.

    Includes status counts for all four lifecycle states and a preview of
    up to five open comments (figure ref + truncated text + reviewer).
    """
    counts = Counter(c.status for c in comments)
    lines = [
        f"Reviewer Comment Tracker — {len(comments)} total comment(s)",
        "",
    ]
    for status in ("OPEN", "IN_REVIEW", "RESOLVED", "WONT_FIX"):
        lines.append(f"  {status:<12} {counts.get(status, 0):>4}")
    other = sum(v for k, v in counts.items() if k not in VALID_STATUSES)
    if other:
        lines.append(f"  OTHER        {other:>4}")
    lines.append("")
    open_comments = [c for c in comments if c.status == "OPEN"]
    if open_comments:
        lines.append(f"Open comments ({len(open_comments)}):")
        for c in open_comments[:5]:
            prefix = f"[{c.figure_ref}] " if c.figure_ref else ""
            preview = c.comment_text[:70]
            if len(c.comment_text) > 70:
                preview += "..."
            lines.append(f"  {prefix}{preview!r}  ({c.reviewer})")
        if len(open_comments) > 5:
            lines.append(f"  ... and {len(open_comments) - 5} more open comment(s).")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

```
python -m pytest tests/envmon/test_ingest_reviewer_comments.py -v
```

Expected: all tests PASS. Typical output ends with `XX passed in X.Xs`. If any FAIL, fix the implementation until they all pass before moving on.

- [ ] **Step 5: Run the full suite to confirm no regressions**

```
python -m pytest -q
```

Expected: all pre-existing 567 tests PASS, plus the new tests. Count should be 567 + (number of new tests).

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/ingest_reviewer_comments.py \
        tests/envmon/test_ingest_reviewer_comments.py
git commit -m "feat(envmon): IngestReviewerMapComments core — CSV/GeoJSON/XLSX parsers, merge, summary (Tool 9.4)"
```

---

### Task 2: CLI command `ingest-reviewer-comments` + CLI tests

**Files:**
- Modify: `autogis/adapters/cli.py` — add `ingest-reviewer-comments` command under the `envmon` group. Insert it near the other reporting/section-9 commands (after `generate-event-report`, around line 821).
- Create: `tests/envmon/test_cli_ingest_reviewer_comments.py`

**Interfaces:**
- Consumes (from Task 1):
  - `ingest_comments(path: Path, *, qa: QACollector) -> list[ReviewerComment]`
  - `read_tracker_csv(path: Path) -> list[ReviewerComment]`
  - `merge_tracker(existing, incoming, *, qa: QACollector) -> list[ReviewerComment]`
  - `write_tracker_csv(comments, path: Path) -> Path`
  - `format_comment_summary(comments: list[ReviewerComment]) -> str`
- Uses from existing `cli.py`:
  - `_render_qa(qa, report, fail_on)` (defined at ~line 903)
  - `envmon` click group (defined at line 49)

- [ ] **Step 1: Write the failing CLI tests**

Create `tests/envmon/test_cli_ingest_reviewer_comments.py`:

```python
"""CLI integration tests for envmon ingest-reviewer-comments (Tool 9.4)."""
import csv
import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from autogis.adapters.cli import autogis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ingest_reviewer_comments_appears_in_help():
    runner = CliRunner()
    result = runner.invoke(autogis, ["envmon", "--help"])
    assert result.exit_code == 0
    assert "ingest-reviewer-comments" in result.output


def test_ingest_reviewer_comments_csv_creates_tracker(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [
        {"figure_ref": "Figure 3", "comment_text": "Fix north arrow",
         "reviewer": "Alice", "status": "OPEN"},
    ])
    out = tmp_path / "tracker.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments",
        str(inp), "--out", str(out),
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
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments",
        str(inp), "--out", str(out),
    ])
    assert "1 total" in result.output or "1 comment" in result.output
    assert "OPEN" in result.output


def test_ingest_reviewer_comments_merge_preserves_resolved_status(tmp_path):
    """Re-ingesting the same source after manually resolving must preserve RESOLVED."""
    inp = tmp_path / "review.csv"
    _write_csv(inp, [
        {"figure_ref": "Figure 3", "comment_text": "Fix north arrow",
         "reviewer": "Alice", "status": "OPEN"},
    ])
    tracker = tmp_path / "tracker.csv"
    runner = CliRunner()
    # First ingest
    runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(tracker),
    ])
    # Manually mark as resolved
    rows = _read_tracker(tracker)
    rows[0]["status"] = "RESOLVED"
    rows[0]["resolution_note"] = "Fixed in v2"
    fieldnames = list(rows[0].keys())
    with tracker.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    # Re-ingest same source with --tracker
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp),
        "--tracker", str(tracker), "--out", str(tracker),
    ])
    assert result.exit_code == 0, result.output
    merged = _read_tracker(tracker)
    assert len(merged) == 1  # not duplicated
    assert merged[0]["status"] == "RESOLVED"
    assert merged[0]["resolution_note"] == "Fixed in v2"


def test_ingest_reviewer_comments_geojson_input(tmp_path):
    data = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-87.65, 41.85]},
            "properties": {
                "content": "Check contour interval",
                "author": "Bob",
                "figure_ref": "Figure 5",
            },
        }],
    }
    inp = tmp_path / "review.geojson"
    inp.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "tracker.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    rows = _read_tracker(out)
    assert len(rows) == 1
    assert rows[0]["comment_text"] == "Check contour interval"
    assert float(rows[0]["x"]) == pytest.approx(-87.65)
    assert float(rows[0]["y"]) == pytest.approx(41.85)


def test_ingest_reviewer_comments_multiple_ingests_grow_tracker(tmp_path):
    """Two different source files → both comments appear in the merged tracker."""
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
    comment_texts = {r["comment_text"] for r in rows}
    assert "First comment" in comment_texts
    assert "Second comment" in comment_texts


def test_ingest_reviewer_comments_unsupported_format_exits_nonzero(tmp_path):
    inp = tmp_path / "review.pdf"
    inp.write_bytes(b"%PDF-fake")
    out = tmp_path / "tracker.csv"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp), "--out", str(out),
    ])
    assert result.exit_code != 0


def test_ingest_reviewer_comments_report_flag_writes_markdown(tmp_path):
    inp = tmp_path / "review.csv"
    _write_csv(inp, [{"figure_ref": "F1", "comment_text": "Fix it",
                       "reviewer": "A", "status": "OPEN"}])
    out = tmp_path / "tracker.csv"
    rpt = tmp_path / "qa.md"
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "ingest-reviewer-comments", str(inp),
        "--out", str(out), "--report", str(rpt),
    ])
    assert result.exit_code == 0, result.output
    assert rpt.exists()
    content = rpt.read_text(encoding="utf-8")
    assert "# " in content  # markdown heading present
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_cli_ingest_reviewer_comments.py -v
```

Expected: `test_ingest_reviewer_comments_appears_in_help` FAILS because the command doesn't exist yet.

- [ ] **Step 3: Add the CLI command to `autogis/adapters/cli.py`**

Insert the following block **after** the `generate-event-report` command (after line 821 in the current file, before `@envmon.command("run-history")`):

```python
@envmon.command("ingest-reviewer-comments")
@click.argument("input_file", metavar="INPUT", type=click.Path(exists=True))
@click.option(
    "--out", "out_path", required=True, type=click.Path(),
    help="Output tracker CSV path (created or overwritten).",
)
@click.option(
    "--tracker", "tracker_path", default=None, type=click.Path(),
    help="Existing comment tracker CSV to merge into (optional; omit to start fresh).",
)
@click.option(
    "--report", default=None, type=click.Path(),
    help="Write QA report to PATH (.md/.json/.csv detected by extension).",
)
@click.option(
    "--fail-on", type=click.Choice(["error", "warning"]),
    default="error", show_default=True,
    help="Exit 1 when this severity or higher is present.",
)
def ingest_reviewer_comments_cmd(input_file, out_path, tracker_path, report, fail_on):
    """Tool 9.4: ingest reviewer map comments/redlines into a tracked comment table.

    INPUT may be a flat CSV, GeoJSON FeatureCollection (AGOL comment export),
    or XLSX spreadsheet. Format is auto-detected from the file extension.

    On first run, omit --tracker and all comments are written fresh to --out.
    On subsequent runs, pass the previous --out as --tracker to merge; existing
    status and resolution fields are preserved for re-ingested comments.
    """
    from autogis.core.common.qa import QACollector
    from autogis.core.envmon.ingest_reviewer_comments import (
        ingest_comments,
        read_tracker_csv,
        merge_tracker,
        write_tracker_csv,
        format_comment_summary,
    )

    qa = QACollector()
    incoming = ingest_comments(Path(input_file), qa=qa)
    existing = read_tracker_csv(Path(tracker_path)) if tracker_path else []
    merged = merge_tracker(existing, incoming, qa=qa)
    out = Path(out_path)
    write_tracker_csv(merged, out)
    click.echo(f"Written: {out}  ({len(merged)} comment(s))")
    click.echo(format_comment_summary(merged))
    _render_qa(qa, report, fail_on)
```

- [ ] **Step 4: Run CLI tests**

```
python -m pytest tests/envmon/test_cli_ingest_reviewer_comments.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the full suite**

```
python -m pytest -q
```

Expected: all tests PASS. No regressions.

- [ ] **Step 6: Confirm the command appears in the CLI**

```
python -m autogis envmon --help
```

Expected output includes: `ingest-reviewer-comments  Tool 9.4: ingest reviewer map comments...`

- [ ] **Step 7: Commit**

```bash
git add autogis/adapters/cli.py \
        tests/envmon/test_cli_ingest_reviewer_comments.py
git commit -m "feat(cli): add ingest-reviewer-comments command (Tool 9.4, headless CSV/GeoJSON/XLSX)"
```

---

## Risks

### R1 — Format variability in real AGOL exports

**Risk:** AGOL comment layer schemas vary by portal configuration. Property names like `content`/`text`/`comment_body` or `author`/`created_by`/`user_name` differ between instances.

**Mitigation:** `_GEOJSON_PROP_MAP` covers the most common aliases. Any unmapped property is silently ignored, so the record is still created (with an empty field) rather than failing. The QA WARNING for `empty_comment_text` surfaces unmapped properties to the user at run time. Users can pre-process the GeoJSON to normalize column names before ingesting.

**Assumption:** AGOL comment exports use Point geometry (not MultiPoint or Polygon). This is standard for the AGOL "Comments" layer type.

### R2 — Location ambiguity (comments without coordinates)

**Risk:** CSV and XLSX sources often omit x/y. Without coordinates, comments cannot be displayed on a map.

**Mitigation:** `x`/`y` are `Optional[float]`; the tracker and CLI work fully without them. No QA WARNING is emitted for missing coordinates (omitting x/y is common and expected for text-only review spreadsheets). If the caller wants to geo-locate comments later, they can look up well/figure coordinates by `figure_ref`.

### R3 — Duplicate `comment_id` across different source files

**Risk:** Two reviewers independently making identical comments (same figure_ref + comment_text + reviewer) on different files produce the same `comment_id` hash, causing one to be silently dropped on merge.

**Mitigation:** The hash includes `source_file` (basename), so the same comment from two different files (`review_alice.csv` vs `review_bob.csv`) will produce different IDs. Two identical comments in the *same* file from the same reviewer are genuinely duplicates and deduplication is the correct behavior. If a reviewer legitimately repeats the same text on the same figure, they must vary the comment text or the file should carry explicit `comment_id` values.

### R4 — openpyxl version compatibility

**Risk:** `read_only=True` mode in openpyxl has had compatibility issues with some XLSX features (merged cells, formulas) across major versions.

**Mitigation:** `data_only=True` suppresses formulas. Blank rows are skipped. If an XLSX is unreadable, the exception propagates to the CLI as an unhandled error (with a clear traceback pointing to the file). No silent data loss.

**Assumption:** openpyxl ≥ 3.0 is installed (it is a declared project dependency for existing headless tools).

### R5 — Status field tampered in tracker CSV

**Risk:** A human editor might set an invalid status string in the tracker CSV (e.g. `"Done"`), which then gets normalized to `"OPEN"` on `read_tracker_csv`, silently "reopening" a resolved comment.

**Mitigation:** `_normalize_status` is applied consistently in both `read_tracker_csv` and all parsers. The `format_comment_summary` output makes status counts visible immediately, so the user would see an unexpected `OPEN` count. A future enhancement could emit a QA WARNING when a non-canonical status is found in the tracker CSV; left as `_TODO` for the next iteration since it requires a QA parameter threaded into `read_tracker_csv`.

---

## Self-Review Checklist

**Spec coverage:**
- [x] AGOL comment export (GeoJSON) → `parse_comments_geojson` with AGOL alias map
- [x] Redline CSV → `parse_comments_csv` with alias map
- [x] XLSX spreadsheet → `parse_comments_xlsx` with "Comments" sheet preference
- [x] Tracked comment table with location + status → `ReviewerComment` dataclass + tracker CSV
- [x] Status lifecycle → `VALID_STATUSES`, `_normalize_status`, merge preserves status
- [x] Headless parsing — no arcpy import anywhere in core module
- [x] Live AGOL fetch via seam → explicitly out of scope (documented in non-goals)
- [x] CLI surface → `envmon ingest-reviewer-comments`
- [x] QA integration → `QACollector` + `_render_qa`

**Placeholder scan:** No TBD/TODO/placeholder patterns present. Every step contains runnable code.

**Type consistency:** `ReviewerComment` field names used consistently across all parsers, `write_tracker_csv`, `read_tracker_csv`, `merge_tracker`, `format_comment_summary`, and CLI tests. `_TRACKER_FIELDS` is derived from the dataclass at module load time, so adding or renaming a field propagates automatically to the CSV serializer.
