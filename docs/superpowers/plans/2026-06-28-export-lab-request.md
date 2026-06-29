# ExportLabAnalyticalRequest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `ExportLabAnalyticalRequest` — expand sampling event plan rows with analyte group details, write a lab request openpyxl workbook (Sheet 1: sample request, Sheet 2: analyte list) and optional CSV.
See spec: `docs/superpowers/specs/2026-06-28-export-lab-request-design.md`.

**Architecture:**
- New: `autogis/core/envmon/lab_request_exporter.py`
- Modify: `autogis/adapters/cli.py` — add `export-lab-request` command (headless)
- New: `tests/envmon/test_lab_request_exporter.py`

## Global Constraints

- Arcpy-free. openpyxl + stdlib (`csv`, `yaml`).
- `analyte_list` = comma-joined analyte names from groups config `analytes` key.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `lab_request_exporter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_lab_request_exporter.py`:

```python
from pathlib import Path
import csv
import pytest
import openpyxl
from autogis.core.envmon.lab_request_exporter import (
    LabRequestRow, LabRequestResult,
    build_lab_request_rows, write_lab_request_workbook, write_lab_request_csv,
)

_PLAN = [
    {"SampleID": "H281-MW01-20260615-GW", "LocationID": "MW-01",
     "AnalyteGroup": "GW_VOC", "Matrix": "GW",
     "Container": "40mL VOA", "Preservative": "HCl",
     "HoldTimeDays": "14", "Notes": ""},
    {"SampleID": "H281-MW02-20260615-GW", "LocationID": "MW-02",
     "AnalyteGroup": "GW_METALS", "Matrix": "GW",
     "Container": "250mL HDPE", "Preservative": "HNO3",
     "HoldTimeDays": "180", "Notes": ""},
]
_GROUPS = {
    "GW_VOC": {
        "analytes": ["Benzene", "Toluene", "Ethylbenzene", "Xylenes"],
        "container": "40mL VOA", "preservative": "HCl", "hold_time_days": 14,
    },
    "GW_METALS": {
        "analytes": ["Arsenic", "Cadmium", "Lead"],
        "container": "250mL HDPE", "preservative": "HNO3", "hold_time_days": 180,
    },
}


def test_build_rows_count():
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    assert len(rows) == 2


def test_analyte_list_populated():
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    voc_row = next(r for r in rows if r.analyte_group == "GW_VOC")
    assert "Benzene" in voc_row.analyte_list
    assert "Toluene" in voc_row.analyte_list


def test_hold_time_from_plan():
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    voc_row = next(r for r in rows if r.analyte_group == "GW_VOC")
    assert voc_row.hold_time_days == 14


def test_turnaround_days_default():
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    assert all(r.turnaround_days == 5 for r in rows)


def test_write_workbook_produces_xlsx(tmp_path):
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    out = tmp_path / "lab_request.xlsx"
    result = write_lab_request_workbook(rows, out, site_id="H281",
                                         event_date="2026-06-15")
    assert out.exists()


def test_sheet1_has_sampleid_column(tmp_path):
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    out = tmp_path / "lab_request.xlsx"
    write_lab_request_workbook(rows, out)
    wb = openpyxl.load_workbook(str(out))
    ws = wb.worksheets[0]
    headers = [cell.value for cell in ws[1]]
    assert "SampleID" in headers


def test_sheet2_analyte_list(tmp_path):
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    out = tmp_path / "lab_request.xlsx"
    write_lab_request_workbook(rows, out)
    wb = openpyxl.load_workbook(str(out))
    assert len(wb.sheetnames) == 2


def test_write_csv(tmp_path):
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    out = tmp_path / "lab_request.csv"
    write_lab_request_csv(rows, out)
    assert out.exists()
    with out.open() as fh:
        rows_read = list(csv.DictReader(fh))
    assert len(rows_read) == 2
    assert "SampleID" in rows_read[0]


def test_column_map_renames(tmp_path):
    rows = build_lab_request_rows(_PLAN, _GROUPS)
    out = tmp_path / "lab_request.xlsx"
    write_lab_request_workbook(rows, out, column_map={"SampleID": "Lab Sample ID"})
    wb = openpyxl.load_workbook(str(out))
    ws = wb.worksheets[0]
    headers = [cell.value for cell in ws[1]]
    assert "Lab Sample ID" in headers
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_lab_request_exporter.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/lab_request_exporter.py`**

```python
"""lab_request_exporter.py — lab analytical request workbook from sampling event plan."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font

from ..common.qa import QACollector, QARecord, SEV_INFO

_DEFAULT_COLUMNS = [
    "SampleID", "LocationID", "Matrix", "AnalyteGroup",
    "AnalyteList", "ContainerType", "Preservative",
    "HoldTimeDays", "TurnaroundDays", "ProjectCode",
    "CollectionDate", "Notes",
]


@dataclass
class LabRequestRow:
    sample_id: str
    location_id: str
    matrix: str
    analyte_group: str
    analyte_list: str
    container_type: str
    preservative: str
    hold_time_days: int
    turnaround_days: int
    project_code: str
    collection_date: str
    notes: str


@dataclass
class LabRequestResult:
    workbook_path: Path
    sample_count: int
    analyte_group_count: int
    qa: QACollector


def _parse_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def build_lab_request_rows(
    plan_rows: list,
    analyte_groups: dict,
    *,
    project_code: str = "",
    turnaround_days: int = 5,
) -> list:
    rows = []
    for p in plan_rows:
        group_name = p.get("AnalyteGroup", "")
        group_cfg = analyte_groups.get(group_name, {})
        analytes = group_cfg.get("analytes", [])
        analyte_list = ", ".join(analytes)
        hold_days = _parse_int(p.get("HoldTimeDays") or group_cfg.get("hold_time_days", 0))
        rows.append(LabRequestRow(
            sample_id=p.get("SampleID", ""),
            location_id=p.get("LocationID", ""),
            matrix=p.get("Matrix", group_cfg.get("matrix", "")),
            analyte_group=group_name,
            analyte_list=analyte_list,
            container_type=p.get("Container", group_cfg.get("container", "")),
            preservative=p.get("Preservative", group_cfg.get("preservative", "")),
            hold_time_days=hold_days,
            turnaround_days=turnaround_days,
            project_code=project_code,
            collection_date=p.get("CollectionDate", ""),
            notes=p.get("Notes", ""),
        ))
    return rows


def write_lab_request_workbook(
    rows: list,
    out_path: Path,
    *,
    site_id: str = "",
    event_date: str = "",
    column_map: Optional[dict] = None,
) -> LabRequestResult:
    cm = column_map or {}
    headers = [cm.get(c, c) for c in _DEFAULT_COLUMNS]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sample Request"

    # Site header
    ws.cell(1, 1, f"Site: {site_id}  Event Date: {event_date}")
    ws.cell(1, 1).font = Font(bold=True)

    # Column headers
    ws.append(headers)
    for cell in ws[2]:
        cell.font = Font(bold=True)

    for r in rows:
        ws.append([
            r.sample_id, r.location_id, r.matrix, r.analyte_group,
            r.analyte_list, r.container_type, r.preservative,
            r.hold_time_days, r.turnaround_days, r.project_code,
            r.collection_date, r.notes,
        ])

    # Sheet 2: analyte groups expanded
    analyte_ws = wb.create_sheet("Analyte Groups")
    analyte_ws.append(["AnalyteGroup", "Analyte"])
    analyte_ws[1][0].font = Font(bold=True)
    analyte_ws[1][1].font = Font(bold=True)
    seen_groups: set = set()
    for r in rows:
        if r.analyte_group in seen_groups:
            continue
        seen_groups.add(r.analyte_group)
        for analyte in r.analyte_list.split(", "):
            if analyte.strip():
                analyte_ws.append([r.analyte_group, analyte.strip()])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))

    group_count = len({r.analyte_group for r in rows})
    return LabRequestResult(
        workbook_path=out_path, sample_count=len(rows),
        analyte_group_count=group_count, qa=QACollector(),
    )


def write_lab_request_csv(rows: list, out_path: Path) -> None:
    fields = [
        "SampleID", "LocationID", "Matrix", "AnalyteGroup",
        "AnalyteList", "ContainerType", "Preservative",
        "HoldTimeDays", "TurnaroundDays", "ProjectCode",
        "CollectionDate", "Notes",
    ]
    with Path(out_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "SampleID": r.sample_id, "LocationID": r.location_id,
                "Matrix": r.matrix, "AnalyteGroup": r.analyte_group,
                "AnalyteList": r.analyte_list, "ContainerType": r.container_type,
                "Preservative": r.preservative, "HoldTimeDays": r.hold_time_days,
                "TurnaroundDays": r.turnaround_days, "ProjectCode": r.project_code,
                "CollectionDate": r.collection_date, "Notes": r.notes,
            })
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_lab_request_exporter.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/lab_request_exporter.py \
        tests/envmon/test_lab_request_exporter.py
git commit -m "feat(envmon): lab_request_exporter — lab analytical request workbook + CSV"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("export-lab-request")
@click.option("--plan", "plan_path", required=True, type=click.Path(exists=True))
@click.option("--analyte-groups", "groups_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--project-code", default="")
@click.option("--turnaround", type=int, default=5, show_default=True)
@click.option("--site", "site_id", default="")
@click.option("--csv-also", "csv_path", default=None, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def export_lab_request_cmd(plan_path, groups_path, out, project_code,
                            turnaround, site_id, csv_path, report):
    """Generate lab analytical request workbook from sampling event plan (headless)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.lab_request_exporter import (
        build_lab_request_rows, write_lab_request_workbook, write_lab_request_csv)

    with open(plan_path, newline="", encoding="utf-8") as fh:
        plan = list(_csv.DictReader(fh))
    groups = _yaml.safe_load(Path(groups_path).read_text(encoding="utf-8"))
    rows = build_lab_request_rows(plan, groups, project_code=project_code,
                                   turnaround_days=turnaround)
    result = write_lab_request_workbook(rows, Path(out), site_id=site_id)
    if csv_path:
        write_lab_request_csv(rows, Path(csv_path))
    click.echo(f"Samples: {result.sample_count}  Groups: {result.analyte_group_count}  "
               f"Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_export_lab_request_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "export-lab-request" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_lab_request_exporter.py
git commit -m "feat(cli): add export-lab-request command"
```
