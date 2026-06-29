# BuildGroundwaterElevationEvent Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** BuildGroundwaterElevationEvent (Tool 4.1)
**Priority:** HIGH — the map-ready event layer that feeds the potentiometric contour tool

---

## Problem

`gw-contours` (Tool 4.2, shipped) needs a clean per-event point dataset that says, for
each well: the water-level elevation, the label text, and **whether the point is valid
for contouring**. Today the inputs are scattered — `normalize_groundwater.py` produces
elevations and `gw-level-summary` produces DTW/trend, but neither emits the
contour-event layer with the exclusion flags (`Dry`, `NM`, `NS`, anomalous,
excluded-from-contouring, perched/separate zone). The `EnvWaterLevelEvent` schema
dataclass already exists (`schema/envmon.py`); nothing fills it.

This is the "Foundation laid / partial" gap called out in `ROADMAP_STATUS_2026-06-27`:
schema present, dedicated event-builder + flags missing.

---

## Approach

**Chosen:** A headless builder that selects one water-level record per well for the
target event and computes the contour-event fields + flags, populating
`EnvWaterLevelEvent`. Reuses `normalize_groundwater` output (elevations) and the same
trend logic as `gw-level-summary` (which it does **not** duplicate — that tool stays the
DTW summary; this tool is the contouring layer).

Flag rules (each flag → QA note):
- **Dry / NM (not measured) / NS (not sampled):** carried from the field status code; a
  dry/NM/NS well is `use_for_contour = False`.
- **Anomalous:** elevation outside `mean ± N·stdev` of the event population (configurable
  N, default 3) → WARNING + `use_for_contour = False` unless overridden.
- **Excluded-from-contouring:** explicit per-well exclusion list (perched/separate-zone
  wells, off-network points).
- **Perched/separate zone:** carried from site config when configured; excluded from the
  main potentiometric surface.

Output is the `EnvWaterLevelEvent` table (label fields included) plus a contour
inclusion/exclusion summary and a hydrograph-ready long CSV.

**Rejected: folding into `gw-level-summary`.** That tool answers "what is the water level
and trend per well" for tables/hydrographs. This tool answers "what points feed the
contour surface, with exclusions." Different consumers; shared trend helper, separate
outputs.

**Rejected: doing interpolation here.** Contour generation stays in `gw-contours`
(arcpy). This tool only prepares and flags the input points — fully headless.

---

## Architecture

```
autogis/
  core/common/schema/
    envmon.py                       ← EnvWaterLevelEvent (EXISTS, populated here)
  core/envmon/
    normalize_groundwater.py        ← EXISTS (elevation source)
    gw_level_summary.py             ← EXISTS (trend helper reused, not duplicated)
    build_gwe_event.py              ← NEW
  adapters/
    cli.py                          ← add build-gwe-event command (headless)
tests/envmon/
  test_build_gwe_event.py           ← NEW
```

---

## Public API (`build_gwe_event.py`)

```python
@dataclass
class GWEventResult:
    records: list[EnvWaterLevelEvent]
    contour_points: int          # use_for_contour == True
    excluded: int
    anomalous: int
    qa: QACollector

def build_gwe_event(
    water_levels: list[dict],
    *,
    event_date: str,
    exclude_locations: set[str] | None = None,
    perched_locations: set[str] | None = None,
    anomaly_stdev: float = 3.0,
) -> GWEventResult:
    """Build the per-event contour layer with exclusion flags from water-level records."""

def write_gwe_event(result: GWEventResult, out_path: Path) -> Path:
    """Write EnvWaterLevelEvent rows to CSV; flags as columns."""
```

---

## CLI Command

```
autogis envmon build-gwe-event \
  --water-levels <levels.csv> \
  --event-date 2026-06-15 \
  --out <gwe_event.csv> \
  [--exclude <exclude_wells.txt>] \
  [--perched <perched_wells.txt>] \
  [--anomaly-stdev 3.0] \
  [--report <gwe_qa.md>]
```

Headless. Output feeds `gw-contours` (arcpy).

---

## Test Strategy

`tests/envmon/test_build_gwe_event.py` — arcpy-free:

1. One record per well selected for the target event date.
2. Dry/NM/NS status → `use_for_contour = False`.
3. Anomalous elevation (> mean+3σ) → flagged, excluded, WARNING.
4. Explicit exclude list → `use_for_contour = False` + flag set.
5. Perched well excluded from the main surface, flagged separate-zone.
6. `contour_points` count equals records with `use_for_contour == True`.
7. Label fields populated for every record.
