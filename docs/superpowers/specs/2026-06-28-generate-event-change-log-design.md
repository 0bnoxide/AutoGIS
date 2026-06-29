# GenerateEventChangeLog Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateEventChangeLog (Tool 9.3)
**Priority:** MEDIUM — a human-readable per-event summary for PMs and reviewers

---

## Problem

After an event is imported and processed, PMs want a plain-language summary:

```text
Imported Q2 2026 groundwater event. 38 samples imported. 7 detected benzene results.
3 benzene exceedances. 2 wells dry. 1 unmatched location ID.
Draft contours generated from 9 wells. 2 callout collisions require review.
```

Today this is written by hand by re-reading every QA report and output table. There is no
tool that rolls the event's existing outputs into a narrative change log.

---

## Approach

**Chosen:** A pure-stdlib aggregator over outputs that already exist, matching the
`generate_event_report.py` pattern (reads CSVs, emits Markdown, no deps). It consumes the
normalized results, the QA report(s), the GWE event layer (4.1), and the callout-collision
output (5.2), counts the salient facts (samples imported, detections/exceedances by
analyte, dry wells, unmatched locations, contour input count, collision count), and renders
them as ordered Markdown sentences. Counts come from the source artifacts — the tool
computes nothing analytical, it *summarizes*.

**Rejected: an LLM narrative.** That is the AI track (`AIExplainQAReport`, 11.2). This tool
is deterministic and template-driven so the change log is reproducible and CI-testable.

**Rejected: re-deriving counts from raw data.** It reads the already-computed QA/event
outputs so its numbers match the figures and QA reports exactly (single source of truth).

---

## Architecture

```
autogis/
  core/envmon/
    generate_event_report.py  ← EXISTS (pattern reference: CSV in, Markdown out)
    event_change_log.py       ← NEW (arcpy-free aggregation + Markdown)
  adapters/
    cli.py                    ← add gen-change-log command (headless)
tests/envmon/
  test_event_change_log.py    ← NEW (arcpy-free)
```

---

## Public API (`event_change_log.py`)

```python
@dataclass
class ChangeLogFacts:
    event_label: str
    samples_imported: int
    detections_by_analyte: dict[str, int]
    exceedances_by_analyte: dict[str, int]
    dry_wells: int
    unmatched_locations: int
    contour_input_wells: int
    callout_collisions: int

def collect_facts(
    *,
    event_label: str,
    results_csv: Path,
    qa_csv: Path | None = None,
    gwe_event_csv: Path | None = None,
    collisions_csv: Path | None = None,
) -> ChangeLogFacts:
    """Read existing event outputs and tally the change-log facts."""

def render_change_log(facts: ChangeLogFacts) -> str:
    """Render the facts as ordered Markdown sentences."""
```

---

## CLI Command

```
autogis envmon gen-change-log \
  --event "Q2 2026 groundwater" \
  --results <results.csv> \
  --out <change_log.md> \
  [--qa <qa.csv>] \
  [--gwe-event <gwe_event.csv>] \
  [--collisions <collisions.csv>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_event_change_log.py` — arcpy-free:

1. `collect_facts` counts samples imported from the results CSV.
2. Detections and exceedances tallied per analyte from screening flags.
3. Dry wells counted from the GWE event layer flags.
4. Unmatched locations counted from the QA report.
5. `render_change_log` includes a sentence per non-zero fact.
6. Zero-value facts are omitted from the narrative (no "0 wells dry").
7. Missing optional input → that section omitted, no crash.
