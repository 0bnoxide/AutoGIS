# GenerateSyntheticEnvWorkbook Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateSyntheticEnvWorkbook (Tool 10.6)
**Priority:** MEDIUM — lets parser hardening run on realistic data without exposing project data

---

## Problem

The parsers and importers must survive ugly real-world workbooks: merged headers, formula
cells, nondetects, qualifiers, missing dates, unknown wells, RPD sheets, soil depths,
metals, IBI. Testing against real project workbooks risks exposing client data, and
hand-crafting messy fixtures is slow. There is no generator for fake-but-realistic
workbooks.

---

## Approach

**Chosen:** A seeded openpyxl workbook generator (openpyxl is already a base dependency, and
Tools 1/9/10 are openpyxl-only per CLAUDE.md). A scenario config selects which "messiness"
features to inject; a fixed seed makes output deterministic for tests. It can emit a clean
baseline workbook or one with any subset of: merged header cells, formula cells (including
a deliberate `#VALUE!`), nondetects (`<0.5 U`), qualifiers, missing dates, an unknown well
ID, an RPD sheet, soil depth intervals, metals, and IBI data — exactly the cases the
validators must catch.

**Rejected: random unseeded data.** Tests need determinism; the seed makes a generated
workbook reproducible so a parser regression is debuggable.

**Rejected: a real-data anonymizer.** Out of scope and riskier (residual PII). Synthetic
generation sidesteps client data entirely.

This is a pure-core, headless, openpyxl-only writer — no arcpy.

---

## Architecture

```
autogis/
  core/envmon/
    synthetic_workbook.py     ← NEW (openpyxl generator, seeded)
  adapters/
    cli.py                    ← add gen-synthetic-workbook command (headless)
tests/envmon/
  test_synthetic_workbook.py  ← NEW (arcpy-free; openpyxl)
```

---

## Public API (`synthetic_workbook.py`)

```python
MESSINESS = (
    "merged_headers", "formulas", "formula_error", "nondetects", "qualifiers",
    "missing_dates", "unknown_well", "rpd_sheet", "soil_depths", "metals", "ibi",
)

@dataclass
class WorkbookScenario:
    site_id: str
    n_wells: int
    n_events: int
    features: set[str]        # subset of MESSINESS
    seed: int = 0

def generate_workbook(scenario: WorkbookScenario, out_path: Path) -> Path:
    """Write a deterministic synthetic environmental workbook with the requested quirks."""
```

---

## CLI Command

```
autogis envmon gen-synthetic-workbook \
  --site-id TEST01 \
  --wells 10 --events 4 \
  --features merged_headers,nondetects,formula_error,rpd_sheet \
  --seed 0 \
  --out <synthetic.xlsx>
```

Headless (openpyxl).

---

## Test Strategy

`tests/envmon/test_synthetic_workbook.py` — arcpy-free, openpyxl:

1. Same seed + scenario → byte-identical (or cell-identical) workbook on re-run.
2. `merged_headers` feature produces at least one merged cell range.
3. `formula_error` injects a cell that evaluates to `#VALUE!`.
4. `nondetects` produces `<`-prefixed values with a `U` qualifier.
5. `unknown_well` includes a well ID absent from the well network.
6. `rpd_sheet` adds a parent/duplicate sheet.
7. The clean baseline (empty `features`) parses without QA errors through `result_parser`.
