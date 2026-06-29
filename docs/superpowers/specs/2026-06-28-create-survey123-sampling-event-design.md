# CreateSurvey123SamplingEvent Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** CreateSurvey123SamplingEvent (Phase 2 / Tool 2.7)
**Priority:** MEDIUM — pre-field planning tool; reduces field crew prep time

---

## Problem

Before each sampling event, the field crew needs:
1. A list of wells to sample with expected analyte groups
2. Sample ID assignments (consistent with the lab naming convention)
3. A draft chain-of-custody (COC) showing expected containers, preservatives, and analyte groups

Currently this is assembled manually from the config file and prior event records
— a 30–60 minute task per event with no systematic connection to the normalized
config or analyte dictionary.

---

## Approach

**Chosen:** Headless event planner that reads the site config, well list, and
analyte dictionary to produce: (a) an event plan CSV (one row per well per
analyte group) and (b) a draft COC Excel workbook (openpyxl). Fully headless;
no arcpy, no AGOL connectivity at plan time.

**Rejected: Auto-submit to Survey123.** Requires AGOL credentials and is
Phase 4 territory. This tool produces the plan document; field crew uses it
to pre-configure their Survey123 form.

**Rejected: Absorbing into `BuildSurvey123XLSFormFromConfig`.** The XLSForm
builder generates the form structure; this tool generates the *event-specific*
well list and sample IDs for a specific upcoming event date.

---

## Architecture

```
autogis/
  core/envmon/
    sampling_event_planner.py   ← NEW
  adapters/
    cli.py                      ← add create-sampling-event command (headless)
tests/envmon/
  test_sampling_event_planner.py ← NEW
```

---

## Public API (`sampling_event_planner.py`)

```python
@dataclass
class SamplingEventWell:
    location_id: str
    analyte_group: str
    sample_id: str          # e.g. "H281-MW01-20260615-GW"
    matrix: str             # GW | SOIL | SW | AIR
    container_type: str     # 40mL VOA | 1L amber | 250mL poly
    preservative: str       # HCl | H2SO4 | NaOH | none
    hold_time_days: int
    crew_notes: str = ""

@dataclass
class SamplingEventPlan:
    site_id: str
    event_date: str
    wells: list[SamplingEventWell]
    qa: QACollector

def build_sample_id(
    site_id: str,
    location_id: str,
    event_date: str,
    matrix: str,
    suffix: str = "",
) -> str:
    """
    Build canonical sample ID: {site_id}-{loc_stripped}-{YYYYMMDD}-{matrix}{suffix}
    e.g. H281-MW01-20260615-GW
    """

def plan_sampling_event(
    site_id: str,
    event_date: str,
    well_ids: list[str],
    analyte_groups: dict[str, dict],   # {group_name: {matrix, container, preservative, hold_days}}
    *,
    duplicate_wells: list[str] | None = None,
    qa: QACollector | None = None,
) -> SamplingEventPlan:
    """
    Cross well_ids × analyte_groups → SamplingEventWell list.
    Duplicate wells get a "-DUP" suffix sample ID.
    """

def write_event_plan_csv(plan: SamplingEventPlan, path: Path) -> None:
    """Write one row per well per analyte group."""

def write_coc_workbook(plan: SamplingEventPlan, template_path: Path | None,
                       out_path: Path) -> None:
    """
    Write draft COC Excel. Columns: SampleID, LocationID, AnalyteGroup,
    Matrix, Container, Preservative, HoldTime, CollectionDate, CollectedBy.
    """
```

---

## Analyte Group Config (YAML)

```yaml
# analyte_groups.yaml
GW_VOC:
  matrix: GW
  container: "40mL VOA vial x3"
  preservative: HCl
  hold_time_days: 14
GW_METALS:
  matrix: GW
  container: "250mL HDPE"
  preservative: HNO3
  hold_time_days: 180
```

---

## Sample ID Convention

```
{site_id}-{location_no_dashes}-{YYYYMMDD}-{matrix}
H281-MW01-20260615-GW
H281-MW01-20260615-GW-DUP   ← duplicate
```

Location ID cleanup: remove hyphens/spaces, uppercase.

---

## CLI Command

```
autogis envmon create-sampling-event \
  --site <site_id> \
  --event-date YYYY-MM-DD \
  --wells MW-01,MW-02,MW-03 \
  --analyte-groups <analyte_groups.yaml> \
  [--duplicate-wells MW-01] \
  --out-csv <event_plan.csv> \
  [--out-coc <coc_draft.xlsx>] \
  [--coc-template <coc_template.xlsx>] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_sampling_event_planner.py` — arcpy-free:

1. `build_sample_id("H281", "MW-01", "2026-06-15", "GW")` → `"H281-MW01-20260615-GW"`
2. `plan_sampling_event` 3 wells × 2 analyte groups → 6 `SamplingEventWell` records
3. Duplicate well → additional record with `-DUP` suffix
4. `write_event_plan_csv` produces correct columns
5. `write_coc_workbook` produces valid xlsx
6. Matrix populated from analyte_groups config (not hard-coded)
7. `hold_time_days` from config appears in COC rows
8. Wells list deduplicated before crossing with groups
