# IngestReviewerMapComments Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** IngestReviewerMapComments (Phase 5 / Tool 9.4)
**Priority:** MEDIUM — closes the figure QA loop; tracks reviewer changes

---

## Problem

After draft figures are sent to a project manager or regulatory reviewer, their
comments (callout position changes, label corrections, screening level updates,
missing wells) are currently tracked in email threads or PDF markup — no
structured audit trail. When the same figure is revised for the next reporting
period, there is no record of what was changed or why.

---

## Approach

**Chosen:** Structured comment CSV ingestion. Reviewers (or the analyst
translating PDF markup) fill in a simple comment template CSV:
`FigureID, CommentType, LocationID, AnalyteName, OldValue, NewValue, Notes`.
The tool validates the CSV against known figure IDs / location IDs, classifies
comment types, writes QA records, and outputs an `Env_FigureComments` CSV
that can be referenced when applying changes in subsequent tools.

This is explicitly a **structured input** design — the tool does not parse
free-text PDF annotations (that is AI-assisted territory, Tool 11.x).

**Rejected: PDF annotation parser.** Requires PDF parsing library (pdfminer,
pypdf) and NLP — deferred to AI-assisted tools (§11). This tool handles
structured reviewer input that has already been transcribed to CSV.

**Rejected: Absorbing into `ValidateEnvironmentalDatabase`.** Figure comments
are a post-production QA artifact, not a database schema check.

---

## Architecture

```
autogis/
  core/envmon/
    reviewer_comments.py        ← NEW
  adapters/
    cli.py                      ← add ingest-reviewer-comments command (headless)
tests/envmon/
  test_reviewer_comments.py     ← NEW
```

---

## Public API (`reviewer_comments.py`)

```python
COMMENT_TYPES = (
    "callout_position",      # move callout to different quadrant
    "label_correction",      # fix text label
    "screening_level",       # update screening level applied
    "missing_location",      # add well/location to figure
    "remove_location",       # remove well/location from figure
    "value_correction",      # fix displayed analytical value
    "note",                  # general note, no specific action
    "approved",              # explicit reviewer approval
)

@dataclass
class FigureComment:
    comment_id: str         # UUID
    figure_id: str
    comment_type: str
    location_id: str        # "" if not location-specific
    analyte_name: str       # "" if not analyte-specific
    old_value: str
    new_value: str
    notes: str
    reviewer: str
    review_date: str
    status: str             # open | applied | deferred | wontfix

@dataclass
class CommentIngestResult:
    records: list[FigureComment]
    invalid_comment_types: list[str]
    unknown_figure_ids: list[str]
    unknown_location_ids: list[str]
    qa: QACollector

def load_comment_csv(path: Path) -> list[dict]:
    """Read reviewer comment CSV. Expected columns per COMMENT_CSV_COLUMNS."""

def validate_comments(
    raw_rows: list[dict],
    known_figure_ids: set[str] | None = None,
    known_location_ids: set[str] | None = None,
) -> CommentIngestResult:
    """
    Validate comment types, figure IDs, location IDs.
    Assign UUIDs. Return structured FigureComment list + QA.
    """

def write_figure_comments_csv(
    records: list[FigureComment],
    out_path: Path,
    *,
    append: bool = False,
) -> None:
    """Write or append to Env_FigureComments.csv."""
```

---

## Comment CSV Template

```csv
FigureID,CommentType,LocationID,AnalyteName,OldValue,NewValue,Notes,Reviewer,ReviewDate
Fig-1A,callout_position,MW-01,Benzene,quadrant=NE,quadrant=SW,overlapping contour,J.Smith,2026-06-20
Fig-1A,missing_location,MW-05,,,,"MW-05 missing from figure",J.Smith,2026-06-20
Fig-2B,approved,,,,,No changes required,J.Smith,2026-06-20
```

---

## Validation Rules

| Check | Severity |
|---|---|
| `comment_type` not in `COMMENT_TYPES` | ERROR |
| `figure_id` not in `known_figure_ids` (if provided) | WARNING |
| `location_id` not in `known_location_ids` (if provided) | WARNING |
| `review_date` not parseable as ISO date | WARNING |
| Empty `new_value` on non-note type | INFO |

---

## CLI Command

```
autogis envmon ingest-reviewer-comments \
  --comments <reviewer_comments.csv> \
  [--figure-ids <known_figure_ids.txt>] \
  [--location-ids <known_locations.txt>] \
  --out <env_figure_comments.csv> \
  [--append] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_reviewer_comments.py` — arcpy-free:

1. `validate_comments` with valid rows → all records have UUIDs, no errors
2. Unknown `comment_type` → ERROR in QA, record excluded
3. Unknown `figure_id` (when known_figure_ids provided) → WARNING
4. Unknown `location_id` → WARNING
5. `status` defaults to `"open"` on ingest
6. `write_figure_comments_csv` produces correct columns
7. `append=True` adds to existing file without overwriting
8. `approved` type with empty location/analyte → valid (no location required)
