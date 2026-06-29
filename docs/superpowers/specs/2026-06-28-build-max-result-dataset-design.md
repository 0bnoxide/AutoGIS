# BuildMaxResultMapDataset Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildMaxResultMapDataset (Phase 4 / Tool 4.9)
**Priority:** MEDIUM — required for lifetime-maximum plume figures and summary tables

---

## Problem

Regulatory summary figures often show the **maximum detected concentration**
per well per analyte across all sampling events, not just the latest event.
Producing this dataset currently requires manual Excel work — sorting by
concentration, picking maxima — which is slow, error-prone, and not tied to
the normalized `Env_AnalyticalResults` table.

---

## Approach

**Chosen:** Headless aggregation from a long-format results CSV. Groups by
`(LocationID, AnalyteName)`, finds the row with the maximum numeric
`ResultValue` (excluding non-detects unless `--include-nd` is set), and
outputs a flat CSV with the same columns as the input plus `MaxEventDate`,
`MaxSampleID`, and `DetectionCount`. Fully stdlib; no arcpy.

**Rejected: "Latest with highest" hybrid.** Ambiguous for regulatory use.
Max-over-all-events is the unambiguous interpretation and the most commonly
requested by regulators.

**Rejected: Absorbing into `build_current_event.py`.** That tool is for
single-event pivot. Max-result is a cross-event aggregation — separate concern.

---

## Architecture

```
autogis/
  core/envmon/
    max_result_dataset.py       ← NEW
  adapters/
    cli.py                      ← add build-max-result-dataset command (headless)
tests/envmon/
  test_max_result_dataset.py    ← NEW
```

---

## Public API (`max_result_dataset.py`)

```python
@dataclass
class MaxResultRecord:
    location_id: str
    analyte_name: str
    max_result_value: float | None
    max_result_qualifier: str
    reported_units: str
    max_sample_date: str
    max_sample_id: str
    detection_count: int          # number of detected (non-ND) samples
    total_sample_count: int       # all samples in period
    screening_level: float | None
    exceedance_ratio: float | None
    has_exceedance: bool
    first_detection_date: str
    last_detection_date: str

def build_max_result_dataset(
    result_rows: list[dict],
    *,
    screening_levels: dict[str, float] | None = None,
    analytes: list[str] | None = None,
    wells: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_nd: bool = False,
    nd_qualifiers: set[str] = frozenset({"ND", "U", "BDL"}),
    qa: QACollector | None = None,
) -> list[MaxResultRecord]:
    """
    Group result_rows by (LocationID, AnalyteName), aggregate to max detected.
    Optional filters: analytes, wells, date range.
    """

def write_max_result_csv(records: list[MaxResultRecord], path: Path) -> None:
```

---

## Aggregation Logic

```
for each (location_id, analyte_name) group:
    all_rows = rows in group (after date/well/analyte filter)
    detected = [r for r in all_rows if qualifier not in nd_qualifiers and value is numeric]
    if not detected and not include_nd:
        skip (all ND)
    if detected:
        max_row = row with highest ResultValue in detected
    else:
        max_row = row with most recent date (ND case)
    
    MaxResultRecord:
        max_result_value = max_row.ResultValue (numeric) or None
        detection_count  = len(detected)
        total_sample_count = len(all_rows)
        first/last_detection_date from detected rows
        exceedance_ratio = max_value / screening_level if available
```

---

## CLI Command

```
autogis envmon build-max-result-dataset \
  --results <env_results.csv> \
  [--screening-levels <screening.yaml>] \
  [--analytes Benzene,Toluene] \
  [--wells MW-01,MW-02] \
  [--date-from YYYY-MM-DD] \
  [--date-to YYYY-MM-DD] \
  [--include-nd] \
  --out <max_results.csv> \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_max_result_dataset.py` — arcpy-free:

1. Two rows same location+analyte → record with higher value selected as max
2. ND row with detected row → detected row selected (ND excluded by default)
3. `include_nd=True` → all-ND group produces record with `max_result_value=None`
4. `detection_count` correct (2 detects out of 3 total)
5. `exceedance_ratio` computed when `screening_levels` provided
6. `date_from` filter excludes older rows
7. `analytes` filter restricts output to listed analytes only
8. `first/last_detection_date` span full detection history
