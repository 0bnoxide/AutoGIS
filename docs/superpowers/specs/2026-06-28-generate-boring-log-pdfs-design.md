# GenerateBoringLogPDFs Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateBoringLogPDFs (Tool 8.0c)
**Priority:** MEDIUM — standardized boring-log deliverables from the normalized store
**Runtime:** CLI ✓ (Markdown/tables, headless) / render to PDF downstream

---

## Problem

Field work deliverables include a standardized boring log per boring: header, drilling
method, driller/logger/date, ground elevation/coordinates, lithologic column, USCS
pattern, sample intervals, PID readings, groundwater observations, well construction
diagram, remarks, approval block — plus a combined appendix, photo log, and sample summary
table. Today these are assembled by hand. The data is (or will be) in the boring database
(8.0a), but nothing assembles the log document.

---

## Approach

**Chosen:** Match the repo's report pattern (`generate_event_report.py`: pure-stdlib
Markdown assembly, no PDF/graphics dependency). The headless tool reads the boring database
(8.0a) and assembles, per boring, a structured **boring-log document model** rendered to
Markdown (with the lithologic column and well-construction diagram as a depth-indexed
table), plus a combined appendix `.md`, a photo-log `.md`, and a sample-summary CSV. PDF
rendering (with true graphical lithology/well-construction diagrams) is an explicit
**downstream step** — a Markdown-to-PDF converter or the Pro layout path — kept out of core
so no heavy graphics dependency enters the arcpy-free layer.

**Rejected: reportlab/weasyprint in core.** The repo deliberately has zero PDF deps;
report tools emit Markdown/CSV and convert downstream. Introducing a graphics PDF lib here
would break that and the arcpy-free dependency budget.

**Rejected: graphical diagrams in v1.** The lithologic column and well-construction diagram
render as depth-ordered tables (defensible, reproducible, testable); a graphical renderer is
a downstream enhancement, not a blocker. (ponytail: tabular diagram now, graphical when a
report actually requires the picture.)

---

## Architecture

```
autogis/
  core/envmon/
    boring_database.py        ← EXISTS after 8.0a (read source)
    boring_log_report.py      ← NEW (arcpy-free Markdown/CSV assembly)
  adapters/
    cli.py                    ← add gen-boring-logs command (headless)
tests/envmon/
  test_boring_log_report.py   ← NEW (arcpy-free)
```

---

## Public API (`boring_log_report.py`)

```python
@dataclass
class BoringLogDoc:
    boring_id: str
    markdown: str
    sample_rows: list[dict]      # for the sample-summary CSV

def build_boring_log(
    boring_id: str,
    *,
    location: dict,
    lithology: list[dict],
    samples: list[dict],
    construction: list[dict],
    groundwater: list[dict],
    photos: list[dict],
) -> BoringLogDoc:
    """Assemble one boring-log Markdown document + sample rows from DB records."""

def build_appendix(docs: list[BoringLogDoc]) -> str:
    """Combine per-boring docs into one appendix Markdown with a contents list."""

def write_outputs(docs, out_dir: Path) -> list[Path]:
    """Write per-boring .md, appendix .md, photo-log .md, and sample-summary.csv."""
```

---

## CLI Command

```
autogis envmon gen-boring-logs \
  --db <borings.sqlite> \
  --out-dir <boring_logs/> \
  [--borings B-1,B-2] \
  [--report <boring_qa.md>]
```

Headless. PDF conversion (graphical) is a downstream step.

---

## Test Strategy

`tests/envmon/test_boring_log_report.py` — arcpy-free:

1. `build_boring_log` includes header, drilling method, and approval-block sections.
2. Lithology intervals render in depth order in the Markdown.
3. Sample intervals and PID readings appear in the sample table.
4. Well-construction records render as a depth-indexed diagram table.
5. `build_appendix` lists every boring in its contents.
6. `write_outputs` produces per-boring `.md` + appendix + photo-log + sample CSV.
7. A boring with no samples still renders (empty sample section, WARNING).
