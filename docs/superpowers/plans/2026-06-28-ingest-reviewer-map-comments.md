# IngestReviewerMapComments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `IngestReviewerMapComments` — validate structured reviewer comment CSV, assign UUIDs, write `Env_FigureComments.csv` with full QA trail.
See spec: `docs/superpowers/specs/2026-06-28-ingest-reviewer-map-comments-design.md`.

**Architecture:**
- New: `autogis/core/envmon/reviewer_comments.py`
- Modify: `autogis/adapters/cli.py` — add `ingest-reviewer-comments` command (headless)
- New: `tests/envmon/test_reviewer_comments.py`

## Global Constraints

- Arcpy-free. stdlib only: `csv`, `uuid`, `datetime`.
- `status` defaults to `"open"` on every ingested record.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `reviewer_comments.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_reviewer_comments.py`:

```python
from pathlib import Path
import csv
import pytest
from autogis.core.envmon.reviewer_comments import (
    COMMENT_TYPES, FigureComment, validate_comments,
    write_figure_comments_csv, load_comment_csv,
)

_VALID_ROWS = [
    {"FigureID": "Fig-1A", "CommentType": "callout_position",
     "LocationID": "MW-01", "AnalyteName": "Benzene",
     "OldValue": "quadrant=NE", "NewValue": "quadrant=SW",
     "Notes": "overlapping contour", "Reviewer": "J.Smith",
     "ReviewDate": "2026-06-20"},
    {"FigureID": "Fig-1A", "CommentType": "missing_location",
     "LocationID": "MW-05", "AnalyteName": "",
     "OldValue": "", "NewValue": "",
     "Notes": "MW-05 missing", "Reviewer": "J.Smith",
     "ReviewDate": "2026-06-20"},
    {"FigureID": "Fig-2B", "CommentType": "approved",
     "LocationID": "", "AnalyteName": "",
     "OldValue": "", "NewValue": "",
     "Notes": "No changes required", "Reviewer": "J.Smith",
     "ReviewDate": "2026-06-20"},
]

_KNOWN_FIGS = {"Fig-1A", "Fig-2B"}
_KNOWN_LOCS = {"MW-01", "MW-02", "MW-03"}


def test_valid_rows_all_accepted():
    result = validate_comments(_VALID_ROWS)
    assert len(result.records) == 3
    assert not result.invalid_comment_types


def test_records_get_uuids():
    result = validate_comments(_VALID_ROWS)
    for rec in result.records:
        assert len(rec.comment_id) == 36  # UUID4 hyphenated


def test_status_defaults_open():
    result = validate_comments(_VALID_ROWS)
    for rec in result.records:
        assert rec.status == "open"


def test_invalid_comment_type_excluded():
    rows = [dict(_VALID_ROWS[0], CommentType="nonsense")]
    result = validate_comments(rows)
    assert len(result.records) == 0
    assert "nonsense" in result.invalid_comment_types
    assert any(r.severity == "ERROR" for r in result.qa.records)


def test_unknown_figure_id_warning():
    rows = [dict(_VALID_ROWS[0], FigureID="Fig-99")]
    result = validate_comments(rows, known_figure_ids=_KNOWN_FIGS)
    assert "Fig-99" in result.unknown_figure_ids
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_unknown_location_id_warning():
    rows = [dict(_VALID_ROWS[0], LocationID="MW-99")]
    result = validate_comments(rows, known_location_ids=_KNOWN_LOCS)
    assert "MW-99" in result.unknown_location_ids
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_approved_type_empty_location_valid():
    rows = [dict(_VALID_ROWS[2])]  # approved, no location
    result = validate_comments(rows, known_location_ids=_KNOWN_LOCS)
    assert len(result.records) == 1
    assert not result.unknown_location_ids


def test_write_figure_comments_csv(tmp_path):
    result = validate_comments(_VALID_ROWS)
    out = tmp_path / "comments.csv"
    write_figure_comments_csv(result.records, out)
    assert out.exists()
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert "comment_id" in rows[0]


def test_append_adds_to_existing(tmp_path):
    result = validate_comments(_VALID_ROWS[:1])
    out = tmp_path / "comments.csv"
    write_figure_comments_csv(result.records, out)
    result2 = validate_comments(_VALID_ROWS[1:2])
    write_figure_comments_csv(result2.records, out, append=True)
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_reviewer_comments.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/reviewer_comments.py`**

```python
"""reviewer_comments.py — structured reviewer figure comment ingestion."""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING, SEV_ERROR

COMMENT_TYPES = (
    "callout_position",
    "label_correction",
    "screening_level",
    "missing_location",
    "remove_location",
    "value_correction",
    "note",
    "approved",
)

_COMMENT_TYPES_SET = frozenset(COMMENT_TYPES)

_CSV_COLUMNS = [
    "comment_id", "figure_id", "comment_type", "location_id",
    "analyte_name", "old_value", "new_value", "notes",
    "reviewer", "review_date", "status",
]

# Types that are valid without a location_id
_NO_LOCATION_REQUIRED = frozenset({"approved", "note"})


@dataclass
class FigureComment:
    comment_id: str
    figure_id: str
    comment_type: str
    location_id: str
    analyte_name: str
    old_value: str
    new_value: str
    notes: str
    reviewer: str
    review_date: str
    status: str


@dataclass
class CommentIngestResult:
    records: list
    invalid_comment_types: list
    unknown_figure_ids: list
    unknown_location_ids: list
    qa: QACollector


def load_comment_csv(path: Path) -> list:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def validate_comments(
    raw_rows: list,
    known_figure_ids: Optional[set] = None,
    known_location_ids: Optional[set] = None,
) -> CommentIngestResult:
    qa = QACollector()
    records = []
    invalid_types: list = []
    unknown_figs: list = []
    unknown_locs: list = []

    for i, row in enumerate(raw_rows):
        ctype = row.get("CommentType", "").strip()
        fig_id = row.get("FigureID", "").strip()
        loc_id = row.get("LocationID", "").strip()

        if ctype not in _COMMENT_TYPES_SET:
            if ctype not in invalid_types:
                invalid_types.append(ctype)
            qa.add(QARecord(SEV_ERROR, "invalid_comment_type",
                            f"Row {i+1}: unknown comment type '{ctype}' — row excluded."))
            continue

        if known_figure_ids is not None and fig_id and fig_id not in known_figure_ids:
            if fig_id not in unknown_figs:
                unknown_figs.append(fig_id)
            qa.add(QARecord(SEV_WARNING, "unknown_figure_id",
                            f"Row {i+1}: figure '{fig_id}' not in known figures."))

        needs_loc = ctype not in _NO_LOCATION_REQUIRED
        if known_location_ids is not None and loc_id and needs_loc \
                and loc_id not in known_location_ids:
            if loc_id not in unknown_locs:
                unknown_locs.append(loc_id)
            qa.add(QARecord(SEV_WARNING, "unknown_location_id",
                            f"Row {i+1}: location '{loc_id}' not in known locations."))

        review_date = row.get("ReviewDate", "").strip()

        records.append(FigureComment(
            comment_id=str(uuid.uuid4()),
            figure_id=fig_id,
            comment_type=ctype,
            location_id=loc_id,
            analyte_name=row.get("AnalyteName", "").strip(),
            old_value=row.get("OldValue", "").strip(),
            new_value=row.get("NewValue", "").strip(),
            notes=row.get("Notes", "").strip(),
            reviewer=row.get("Reviewer", "").strip(),
            review_date=review_date,
            status="open",
        ))

    qa.add(QARecord(SEV_INFO, "comments_ingested",
                    f"{len(records)} comments ingested, "
                    f"{len(invalid_types)} invalid types skipped."))

    return CommentIngestResult(
        records=records,
        invalid_comment_types=invalid_types,
        unknown_figure_ids=unknown_figs,
        unknown_location_ids=unknown_locs,
        qa=qa,
    )


def write_figure_comments_csv(
    records: list,
    out_path: Path,
    *,
    append: bool = False,
) -> None:
    p = Path(out_path)
    write_header = not append or not p.exists() or p.stat().st_size == 0
    mode = "a" if append else "w"
    with p.open(mode, newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        if write_header:
            w.writeheader()
        for rec in records:
            w.writerow({k: getattr(rec, k, "") for k in _CSV_COLUMNS})
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_reviewer_comments.py -v
```

Expected: all 9 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/reviewer_comments.py \
        tests/envmon/test_reviewer_comments.py
git commit -m "feat(envmon): reviewer_comments — structured figure comment ingestion with QA"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("ingest-reviewer-comments")
@click.option("--comments", "comments_path", required=True, type=click.Path(exists=True))
@click.option("--figure-ids", "fig_ids_path", default=None, type=click.Path(exists=True))
@click.option("--location-ids", "loc_ids_path", default=None, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--append", "do_append", is_flag=True, default=False)
@click.option("--report", default=None, type=click.Path())
def ingest_reviewer_comments_cmd(comments_path, fig_ids_path, loc_ids_path,
                                  out, do_append, report):
    """Ingest structured reviewer figure comments into Env_FigureComments.csv (headless)."""
    from autogis.core.envmon.reviewer_comments import (
        load_comment_csv, validate_comments, write_figure_comments_csv)

    rows = load_comment_csv(Path(comments_path))
    known_figs = (
        set(Path(fig_ids_path).read_text(encoding="utf-8").splitlines())
        if fig_ids_path else None
    )
    known_locs = (
        set(Path(loc_ids_path).read_text(encoding="utf-8").splitlines())
        if loc_ids_path else None
    )
    result = validate_comments(rows, known_figure_ids=known_figs,
                               known_location_ids=known_locs)
    write_figure_comments_csv(result.records, Path(out), append=do_append)
    click.echo(f"Ingested: {len(result.records)}  Output: {out}")
    if result.invalid_comment_types:
        click.echo(f"Invalid types skipped: {result.invalid_comment_types}", err=True)
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_ingest_reviewer_comments_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "ingest-reviewer-comments" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_reviewer_comments.py
git commit -m "feat(cli): add ingest-reviewer-comments command"
```
