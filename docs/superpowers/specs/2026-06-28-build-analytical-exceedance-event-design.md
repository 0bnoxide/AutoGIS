# BuildAnalyticalExceedanceEvent Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildAnalyticalExceedanceEvent (Phase 4 / Tool 4.4)
**Priority:** HIGH — foundation for all exceedance figure production

---

## Problem

`build_current_event.py` already emits `Env_CurrentEventWide` with `HasDetection`
and `HasExceedance` flags for the "latest" sample-selection mode. What it lacks
are the dedicated **exceedance event** selectors needed for regulatory figures:

- `max_exceedance_per_location` — pick the sample with the highest ratio to
  screening level (not necessarily the latest)
- `date_range_latest` — latest sample within a date window
- style/status fields: `ExceedanceRatio`, `ExceedanceTier` (e.g. 1–2×, 2–5×, >5×),
  `ScreeningLevelName`, `ScreeningLevelValue`

Without these, every exceedance figure requires manual post-processing.

---

## Approach

**Chosen:** Thin wrapper around the existing `select_samples()` +
`build_wide_event()` from `build_current_event.py`. Adds:
1. Exceedance-specific sample selection rules (already declared in
   `SAMPLE_SELECTION_RULES` but not fully implemented for the exceedance path).
2. Post-pivot enrichment step: for each result column, compute
   `ExceedanceRatio` and `ExceedanceTier` by joining against a
   screening-level lookup (YAML or dict).

All headless; no arcpy.

**Rejected: Separate pivot module.** The pivot logic is already correct in
`build_current_event.py`. A thin call + enrichment avoids duplication.

---

## Architecture

```
autogis/
  core/envmon/
    build_exceedance_event.py   ← NEW (thin wrapper + enrichment)
  adapters/
    cli.py                      ← add build-exceedance-event command (headless)
tests/envmon/
  test_build_exceedance_event.py ← NEW
```

---

## Public API (`build_exceedance_event.py`)

```python
EXCEEDANCE_TIERS = {
    (0.0, 1.0):  "below",
    (1.0, 2.0):  "1x-2x",
    (2.0, 5.0):  "2x-5x",
    (5.0, 10.0): "5x-10x",
    (10.0, None): ">10x",
}

@dataclass
class ExceedanceEventRecord:
    location_id: str
    sample_id: str
    sample_date: str
    analyte_name: str
    result_value: float | None
    result_qualifier: str
    reported_units: str
    screening_level: float | None
    screening_level_name: str
    exceedance_ratio: float | None
    exceedance_tier: str          # "below" | "1x-2x" | "2x-5x" | "5x-10x" | ">10x"
    has_exceedance: bool
    has_detection: bool
    selection_reason: str

def classify_exceedance_tier(ratio: float | None) -> str:
    """Map numeric ratio to tier label."""

def build_exceedance_event(
    result_rows: list[dict],
    screening_levels: dict[str, float],
    *,
    rule: str = "max_exceedance_per_location",
    event_date: str | None = None,
    date_range: tuple[str, str] | None = None,
    qa: QACollector | None = None,
) -> list[ExceedanceEventRecord]:
    """
    Select samples by rule, compute exceedance ratio/tier for each result.
    Returns one record per location-analyte pair.
    """

def load_screening_levels_yaml(path: Path) -> dict[str, float]:
    """Load {AnalyteName: screening_value} from YAML."""

def write_exceedance_event_csv(records: list[ExceedanceEventRecord], path: Path) -> None:
```

---

## Sample Selection Rules (exceedance path)

| Rule | Logic |
|---|---|
| `max_exceedance_per_location` | Per location: row with highest `result / screening_level` |
| `latest_per_location` | Latest sample per location (existing) |
| `specific_event_date` | Exact date match |
| `date_range_latest` | Latest sample within `date_range` window |

---

## Exceedance Tier Mapping

| Ratio | Tier |
|---|---|
| None or result=ND | `"below"` |
| 0 – 1.0 | `"below"` |
| 1.0 – 2.0 | `"1x-2x"` |
| 2.0 – 5.0 | `"2x-5x"` |
| 5.0 – 10.0 | `"5x-10x"` |
| > 10.0 | `">10x"` |

---

## CLI Command

```
autogis envmon build-exceedance-event \
  --results <env_results.csv> \
  --screening-levels <screening.yaml> \
  --rule max_exceedance_per_location|latest_per_location|specific_event_date|date_range_latest \
  [--event-date YYYY-MM-DD] \
  [--date-from YYYY-MM-DD --date-to YYYY-MM-DD] \
  --out <exceedance_event.csv> \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_build_exceedance_event.py` — arcpy-free:

1. `classify_exceedance_tier(1.5)` → `"1x-2x"`
2. `classify_exceedance_tier(None)` → `"below"`
3. `build_exceedance_event` max_exceedance rule selects highest-ratio sample per location
4. `has_exceedance=True` when ratio ≥ 1.0
5. `has_detection=False` for ND results
6. `specific_event_date` filter excludes other dates
7. `date_range_latest` returns latest within window
8. `load_screening_levels_yaml` parses YAML dict correctly
