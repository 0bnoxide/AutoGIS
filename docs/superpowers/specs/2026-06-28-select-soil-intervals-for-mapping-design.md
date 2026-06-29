# SelectSoilIntervalsForMapping Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** SelectSoilIntervalsForMapping (Tool 4.8)
**Priority:** MEDIUM — soil analytical maps need one defensible interval per boring callout

---

## Problem

A soil boring has multiple sampled depth intervals (e.g. 2–4 ft, 8–10 ft, 14–16 ft).
A soil analytical map can't show every interval in every callout — the cartographer
must pick which interval(s) appear per location, by a consistent rule (shallowest,
deepest, highest result, highest exceedance, a configured list, or excavation
confirmation samples only). Today this selection is manual and inconsistent between
figures, and the rule used is undocumented.

---

## Approach

**Chosen:** A headless selector that takes long-format soil results (with depth-interval
fields) and a selection rule, and emits a map-ready selection table — the subset of
rows that should appear in callouts, with the selection rule recorded per row for
auditability. Reuses the screening flags from `apply_screening.py` so
`highest_exceedance` can rank by exceedance, not just raw value.

Selection rules:
- `all` — every interval.
- `shallowest` / `deepest` — by interval top depth.
- `highest_result` — max result per (location, analyte).
- `highest_exceedance` — max exceedance ratio (result / screening level) per location.
- `interval_list` — configured depth windows.
- `confirmation_only` — rows flagged as excavation confirmation samples.

**Rejected: per-analyte vs per-location ambiguity.** Made explicit: `highest_result`
selects per (location, analyte); `shallowest`/`deepest` select per location. The chosen
rule and grouping are written into each output row.

**Rejected: building map graphics here.** This emits the *selection table*; the callout
builder (`build-callouts`, arcpy) consumes it. Fully headless.

---

## Architecture

```
autogis/
  core/envmon/
    apply_screening.py            ← EXISTS (exceedance flags reused)
    soil_interval_selector.py     ← NEW
  adapters/
    cli.py                        ← add select-soil-intervals command (headless)
tests/envmon/
  test_soil_interval_selector.py  ← NEW
```

---

## Public API (`soil_interval_selector.py`)

```python
SELECTION_RULES = (
    "all", "shallowest", "deepest", "highest_result",
    "highest_exceedance", "interval_list", "confirmation_only",
)

@dataclass
class IntervalSelection:
    location_id: str
    analyte: str
    depth_top: float
    depth_bottom: float
    result_value: float | None
    exceeds: bool
    selection_rule: str          # which rule selected this row

@dataclass
class SelectionResult:
    selected: list[IntervalSelection]
    rule: str
    qa: QACollector

def select_intervals(
    soil_rows: list[dict],
    *,
    rule: str = "highest_exceedance",
    interval_list: list[tuple[float, float]] | None = None,
) -> SelectionResult:
    """Apply the selection rule; record the rule on each kept row."""
```

---

## CLI Command

```
autogis envmon select-soil-intervals \
  --soil-results <soil_results.csv> \
  --rule highest_exceedance \
  --out <map_selection.csv> \
  [--interval-list 2-4,8-10] \
  [--report <selection_qa.md>]
```

Headless. Output feeds `build-callouts`.

---

## Test Strategy

`tests/envmon/test_soil_interval_selector.py` — arcpy-free:

1. `shallowest` keeps the min-top-depth interval per location.
2. `deepest` keeps the max-bottom-depth interval per location.
3. `highest_result` selects per (location, analyte) max value.
4. `highest_exceedance` ranks by result/screening ratio, not raw value.
5. `interval_list` keeps only rows inside configured windows.
6. `confirmation_only` keeps only confirmation-flagged rows.
7. Selection rule recorded on every kept row; QA notes locations with no qualifying interval.
