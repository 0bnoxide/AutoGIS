# CreateWorkbookParserProfile Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** CreateWorkbookParserProfile (Tool 2.1)
**Priority:** HIGH — reduces effort each time a slightly different lab/client workbook arrives

---

## Problem

Every new lab or client spreadsheet has a slightly different layout: sheet names,
header rows, where the date lives, which column holds the sample ID, which rows carry
analyte names/units/screening levels. Today an analyst hand-writes a parser profile
(YAML) for each new format by squinting at the workbook. The inspection primitives
already exist (`excel_workbook_inspector.py`, `excel_profile_reader.py`) but nothing
turns an inspection into a *draft profile* — the analyst still transcribes findings by
hand.

---

## Approach

**Chosen:** Inspection → heuristic profile drafter. Run the existing
`excel_workbook_inspector` to produce a structure report, then apply deterministic
heuristics to draft a parser profile (sheet pick, header row, date column, location
column, analyte/unit/screening rows). Emit the draft profile YAML plus a confidence
report listing every field that needs human confirmation. The deterministic parser
(`result_parser.py`) still performs the real import — this tool only drafts config.

Heuristics (all overridable, all logged to QA):
- **Sheet:** highest density of numeric cells matching the target data type's analyte
  vocabulary (from the analyte dictionary); else first non-empty sheet → WARNING.
- **Header row:** first row where >50% of cells are non-numeric strings and the row
  below begins numeric data.
- **Date column/cell:** first cell parseable as a date near the header.
- **Location column:** column whose values best match `reconcile_locations` ID patterns
  (`MW-\d+`, `HSS-?\d+`, etc.).
- **Analyte/unit/screening rows:** rows whose labels hit the analyte dictionary / a
  known-units set (`units.py`) / screening-level config.

**Rejected: LLM drafting here.** That is Tool 11.1 (`AIDraftParserProfile`), a separate
deferred tool that consumes this tool's inspection JSON. This tool is fully
deterministic so it runs in CI and offline.

**Rejected: auto-applying the draft.** The tool never imports; it emits a draft a human
reviews, then feeds to `BatchImportEnvironmentalWorkbooks` (2.2).

---

## Architecture

```
autogis/
  core/envmon/
    excel_workbook_inspector.py    ← EXISTS (reused)
    excel_profile_reader.py        ← EXISTS (reused)
    parser_profile_drafter.py      ← NEW
  adapters/
    cli.py                         ← add draft-parser-profile command (headless)
tests/envmon/
  test_parser_profile_drafter.py   ← NEW
```

---

## Public API (`parser_profile_drafter.py`)

```python
@dataclass
class ProfileFieldGuess:
    field: str            # "sheet", "header_row", "date_column", ...
    value: object
    confidence: str       # high | medium | low
    needs_confirmation: bool
    rationale: str

@dataclass
class DraftProfileResult:
    profile: dict                 # the drafted parser profile (YAML-serializable)
    guesses: list[ProfileFieldGuess]
    qa: QACollector

def draft_parser_profile(
    inspection: dict,             # output of excel_workbook_inspector
    *,
    target_type: str = "UNKNOWN", # GW | SOIL | METALS | IBI | RPD | UNKNOWN
    site_id: str | None = None,
    analyte_dict_path: Path | None = None,
) -> DraftProfileResult:
    """Heuristically draft a parser profile from a workbook inspection."""

def write_draft_profile(result: DraftProfileResult, out_path: Path) -> Path:
    """Write profile YAML; low-confidence guesses become `_TODO:` comments."""
```

Low-confidence guesses are written as `_TODO`-marked keys, matching the existing
DRAFT-stub convention (ADR-0011) so a human cannot silently ship an unverified profile.

---

## CLI Command

```
autogis envmon draft-parser-profile \
  --workbook <input.xlsx> \
  --out <profile.yaml> \
  [--target-type GW|SOIL|METALS|IBI|RPD] \
  [--site-id H281] \
  [--analyte-dict <analytes.yaml>] \
  [--report <draft_qa.md>]
```

Headless (openpyxl only). Registered as `Runtime.CLOUD`.

---

## Test Strategy

`tests/envmon/test_parser_profile_drafter.py` — arcpy-free:

1. Synthetic inspection dict with one obvious data sheet → that sheet is picked.
2. Header-row heuristic picks the string row above the first numeric row.
3. Date column detected from a parseable date cell.
4. Location column chosen by ID-pattern match over a non-matching column.
5. No analyte rows match dictionary → `low` confidence + `needs_confirmation` True + WARNING.
6. `write_draft_profile` emits `_TODO` keys for every low-confidence guess.
7. `target_type` filters the analyte vocabulary used for sheet scoring.
