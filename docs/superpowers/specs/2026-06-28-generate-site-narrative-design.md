# GenerateSiteNarrative Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateSiteNarrative (Phase 3 / Tool 5.8)
**Priority:** MEDIUM — reduces first-draft report writing time by 30–60 minutes per site

---

## Problem

Every monitoring report includes a site narrative section: highest detections
this event, comparison to previous events, notable trends (improving/worsening),
new exceedances or resolved exceedances, wells not sampled. This section is
written from scratch each report cycle by manually scanning tables. With
structured data available from `build-max-result-dataset`, `generate-change-log`,
and `build-compliance-table`, the narrative can be generated automatically as
a first-draft template that the analyst reviews and finalizes.

---

## Approach

**Chosen:** Template-driven text narrative from structured envmon data.
Reads max-result CSV, change-log CSV (optional), compliance summary CSV
(optional). Fills a set of sentence templates:
- Highest detections this event (top N by exceedance ratio)
- New exceedances (from change-log `exceedance_new` records)
- Resolved exceedances (`exceedance_resolved`)
- Locations with no samples this event
- Overall plume status (stable/expanding/contracting based on well count trends)

Output: plain-text `.txt` or Markdown `.md` file. Not a Word document —
the analyst pastes sections into their report template.

**Rejected: LLM-generated prose.** LLM integration is a Phase 5+/AI-assisted
tool. This tool uses deterministic templates to produce factually correct text
that doesn't require LLM validation.

**Rejected: Word/docx output.** Adds python-docx dependency. Plain text is
universally pasteable.

---

## Architecture

```
autogis/
  core/envmon/
    site_narrative_generator.py    ← NEW
  adapters/
    cli.py                         ← add generate-site-narrative command (headless)
tests/envmon/
  test_site_narrative_generator.py ← NEW
```

---

## Public API (`site_narrative_generator.py`)

```python
@dataclass
class NarrativeSection:
    heading: str
    text: str
    data_rows: list[dict]   # source data backing the narrative

@dataclass
class SiteNarrativeResult:
    sections: list[NarrativeSection]
    full_text: str
    site_id: str
    event_label: str
    qa: QACollector

def build_highest_detections_section(
    max_result_rows: list[dict],
    *,
    top_n: int = 5,
    screening_levels: dict[str, float] | None = None,
) -> NarrativeSection:
    """Top N detections by value or exceedance ratio."""

def build_exceedance_change_section(
    change_log_rows: list[dict],
) -> NarrativeSection:
    """New and resolved exceedances from event change log."""

def build_not_sampled_section(
    plan_rows: list[dict],
    result_rows: list[dict],
) -> NarrativeSection:
    """Wells in plan with no results."""

def generate_site_narrative(
    site_id: str,
    event_label: str,
    *,
    max_result_path: Path | None = None,
    change_log_path: Path | None = None,
    plan_path: Path | None = None,
    result_path: Path | None = None,
    screening_levels: dict[str, float] | None = None,
    top_n: int = 5,
    qa: QACollector | None = None,
) -> SiteNarrativeResult:
    """Assemble all available sections into a full narrative."""
```

---

## Narrative Template Examples

```
## Highest Detections

The highest concentration detected during the Q1-2026 monitoring event was
benzene at 12.0 ug/L at MW-01, which exceeded the MCL of 5.0 ug/L (2.4×).
Toluene was detected at MW-03 at 85.0 ug/L, below the MCL of 1000.0 ug/L.

## Exceedance Changes

The following new exceedances were identified this event:
- Benzene at MW-04 (3.2 ug/L; MCL = 5.0 ug/L — note: value below MCL; check data)

No previously identified exceedances were resolved this event.

## Sampling Completeness

All 12 scheduled monitoring locations were sampled during this event.
```

---

## CLI Command

```
autogis envmon generate-site-narrative \
  --site <site_id> \
  --event-label Q1-2026 \
  [--max-results <max_result.csv>] \
  [--change-log <change_log.csv>] \
  [--plan <event_plan.csv>] \
  [--results <results.csv>] \
  [--screening-levels <sl.yaml>] \
  [--top-n 5] \
  --out <narrative.md> \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_site_narrative_generator.py` — arcpy-free:

1. `build_highest_detections_section` selects top N by value
2. Exceedance ratio included when screening_level provided
3. `build_exceedance_change_section` with `new_exceedance` rows → section mentions new exceedance
4. `build_not_sampled_section` lists wells in plan absent from results
5. `generate_site_narrative` with only max-result input → produces non-empty `full_text`
6. All sections concatenated in `full_text`
7. `SiteNarrativeResult.event_label` echoed in output text
8. No results → `build_not_sampled_section` returns informative empty-plan message
