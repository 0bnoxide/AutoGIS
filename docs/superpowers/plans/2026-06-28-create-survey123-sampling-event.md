# CreateSurvey123SamplingEvent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `CreateSurvey123SamplingEvent` — pre-field event planner that cross-products wells × analyte groups into a plan CSV + draft COC workbook.
See spec: `docs/superpowers/specs/2026-06-28-create-survey123-sampling-event-design.md`.

**Architecture:**
- New: `autogis/core/envmon/sampling_event_planner.py`
- Modify: `autogis/adapters/cli.py` — add `create-sampling-event` command (headless)
- New: `tests/envmon/test_sampling_event_planner.py`

## Global Constraints

- Arcpy-free. openpyxl for COC; stdlib for CSV/YAML.
- Sample ID convention: `{site_id}-{loc_nohyphen}-{YYYYMMDD}-{matrix}{suffix}`.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `sampling_event_planner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_sampling_event_planner.py`:

```python
from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.sampling_event_planner import (
    build_sample_id, plan_sampling_event, write_event_plan_csv,
    write_coc_workbook, SamplingEventWell,
)

_GROUPS = {
    "GW_VOC": {
        "matrix": "GW", "container": "40mL VOA",
        "preservative": "HCl", "hold_time_days": 14
    },
    "GW_METALS": {
        "matrix": "GW", "container": "250mL HDPE",
        "preservative": "HNO3", "hold_time_days": 180
    },
}
_WELLS = ["MW-01", "MW-02"]


def test_build_sample_id():
    sid = build_sample_id("H281", "MW-01", "2026-06-15", "GW")
    assert sid == "H281-MW01-20260615-GW"


def test_build_sample_id_dup():
    sid = build_sample_id("H281", "MW-01", "2026-06-15", "GW", suffix="-DUP")
    assert sid == "H281-MW01-20260615-GW-DUP"


def test_plan_well_count():
    plan = plan_sampling_event("H281", "2026-06-15", _WELLS, _GROUPS)
    assert len(plan.wells) == 4  # 2 wells × 2 groups


def test_plan_duplicate_well():
    plan = plan_sampling_event("H281", "2026-06-15", _WELLS, _GROUPS,
                               duplicate_wells=["MW-01"])
    sample_ids = [w.sample_id for w in plan.wells]
    assert any("-DUP" in sid for sid in sample_ids)


def test_plan_matrix_from_group():
    plan = plan_sampling_event("H281", "2026-06-15", ["MW-01"], _GROUPS)
    matrices = {w.matrix for w in plan.wells}
    assert "GW" in matrices


def test_write_plan_csv(tmp_path):
    plan = plan_sampling_event("H281", "2026-06-15", _WELLS, _GROUPS)
    out = tmp_path / "plan.csv"
    write_event_plan_csv(plan, out)
    import csv
    with out.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 4
    assert "SampleID" in rows[0]


def test_write_coc_workbook(tmp_path):
    plan = plan_sampling_event("H281", "2026-06-15", _WELLS, _GROUPS)
    out = tmp_path / "coc.xlsx"
    write_coc_workbook(plan, None, out)
    wb = openpyxl.load_workbook(str(out))
    assert len(wb.sheetnames) > 0


def test_hold_time_in_plan():
    plan = plan_sampling_event("H281", "2026-06-15", ["MW-01"], _GROUPS)
    voc = next(w for w in plan.wells if w.analyte_group == "GW_VOC")
    assert voc.hold_time_days == 14
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_sampling_event_planner.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/sampling_event_planner.py`**

```python
"""sampling_event_planner.py — pre-field sampling event planner."""
from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl

from ..common.qa import QACollector


@dataclass
class SamplingEventWell:
    location_id: str
    analyte_group: str
    sample_id: str
    matrix: str
    container_type: str
    preservative: str
    hold_time_days: int
    crew_notes: str = ""


@dataclass
class SamplingEventPlan:
    site_id: str
    event_date: str
    wells: list = field(default_factory=list)
    qa: QACollector = field(default_factory=QACollector)


def build_sample_id(
    site_id: str,
    location_id: str,
    event_date: str,
    matrix: str,
    suffix: str = "",
) -> str:
    loc_clean = re.sub(r"[-\s]", "", location_id).upper()
    date_clean = event_date.replace("-", "")
    return f"{site_id}-{loc_clean}-{date_clean}-{matrix}{suffix}"


def plan_sampling_event(
    site_id: str,
    event_date: str,
    well_ids: list,
    analyte_groups: dict,
    *,
    duplicate_wells: Optional[list] = None,
    qa: Optional[QACollector] = None,
) -> SamplingEventPlan:
    if qa is None:
        qa = QACollector()
    plan = SamplingEventPlan(site_id=site_id, event_date=event_date, qa=qa)
    dup_set = set(duplicate_wells or [])
    seen = set()

    for well in well_ids:
        if well in seen:
            continue
        seen.add(well)
        for group_name, group_cfg in analyte_groups.items():
            matrix = group_cfg.get("matrix", "GW")
            sid = build_sample_id(site_id, well, event_date, matrix)
            plan.wells.append(SamplingEventWell(
                location_id=well,
                analyte_group=group_name,
                sample_id=sid,
                matrix=matrix,
                container_type=group_cfg.get("container", ""),
                preservative=group_cfg.get("preservative", ""),
                hold_time_days=group_cfg.get("hold_time_days", 0),
            ))
            if well in dup_set:
                dup_sid = build_sample_id(site_id, well, event_date, matrix, suffix="-DUP")
                plan.wells.append(SamplingEventWell(
                    location_id=well,
                    analyte_group=group_name,
                    sample_id=dup_sid,
                    matrix=matrix,
                    container_type=group_cfg.get("container", ""),
                    preservative=group_cfg.get("preservative", ""),
                    hold_time_days=group_cfg.get("hold_time_days", 0),
                    crew_notes="DUPLICATE",
                ))
    return plan


_COC_HEADERS = [
    "SampleID", "LocationID", "AnalyteGroup", "Matrix",
    "Container", "Preservative", "HoldTimeDays", "CollectionDate",
    "CollectedBy", "Notes",
]


def write_event_plan_csv(plan: SamplingEventPlan, path: Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "SiteID", "LocationID", "AnalyteGroup", "SampleID",
            "Matrix", "Container", "Preservative", "HoldTimeDays", "Notes",
        ])
        w.writeheader()
        for well in plan.wells:
            w.writerow({
                "SiteID": plan.site_id, "LocationID": well.location_id,
                "AnalyteGroup": well.analyte_group, "SampleID": well.sample_id,
                "Matrix": well.matrix, "Container": well.container_type,
                "Preservative": well.preservative,
                "HoldTimeDays": well.hold_time_days, "Notes": well.crew_notes,
            })


def write_coc_workbook(
    plan: SamplingEventPlan,
    template_path: Optional[Path],
    out_path: Path,
) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Chain of Custody"
    ws.append(_COC_HEADERS)
    for well in plan.wells:
        ws.append([
            well.sample_id, well.location_id, well.analyte_group,
            well.matrix, well.container_type, well.preservative,
            well.hold_time_days, plan.event_date, "", well.crew_notes,
        ])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_sampling_event_planner.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/sampling_event_planner.py \
        tests/envmon/test_sampling_event_planner.py
git commit -m "feat(envmon): sampling_event_planner — pre-field event plan + draft COC"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("create-sampling-event")
@click.option("--site", "site_id", required=True)
@click.option("--event-date", required=True, help="ISO date YYYY-MM-DD")
@click.option("--wells", required=True, help="Comma-separated well IDs")
@click.option("--analyte-groups", "groups_path", required=True, type=click.Path(exists=True))
@click.option("--duplicate-wells", default=None)
@click.option("--out-csv", required=True, type=click.Path())
@click.option("--out-coc", default=None, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def create_sampling_event_cmd(site_id, event_date, wells, groups_path,
                               duplicate_wells, out_csv, out_coc, report):
    """Generate pre-field sampling event plan and draft COC (headless)."""
    import yaml as _yaml
    from autogis.core.envmon.sampling_event_planner import (
        plan_sampling_event, write_event_plan_csv, write_coc_workbook)
    from autogis.core.common.qa import QACollector

    groups = _yaml.safe_load(Path(groups_path).read_text(encoding="utf-8"))
    well_list = [w.strip() for w in wells.split(",")]
    dup_list = [w.strip() for w in duplicate_wells.split(",")] if duplicate_wells else None
    qa = QACollector()
    plan = plan_sampling_event(site_id, event_date, well_list, groups,
                                duplicate_wells=dup_list, qa=qa)
    write_event_plan_csv(plan, Path(out_csv))
    if out_coc:
        write_coc_workbook(plan, None, Path(out_coc))
    click.echo(f"Samples planned: {len(plan.wells)}  CSV: {out_csv}")
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_create_sampling_event_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "create-sampling-event" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_sampling_event_planner.py
git commit -m "feat(cli): add create-sampling-event command"
```
