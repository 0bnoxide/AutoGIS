# GenerateRegulatorySubmissionTables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateRegulatorySubmissionTables` — pivot long-format results into agency regulatory table format (wells × analytes, MCL comparison, exceedance markers, footnotes sheet) as an openpyxl workbook.
See spec: `docs/superpowers/specs/2026-06-28-generate-regulatory-tables-design.md`.

**Architecture:**
- New: `autogis/core/envmon/regulatory_table_builder.py`
- Modify: `autogis/adapters/cli.py` — add `generate-reg-tables` command (headless)
- New: `tests/envmon/test_regulatory_table_builder.py`

## Global Constraints

- Arcpy-free. openpyxl only.
- `exceed_marker` (`**`) appended to cell value string when value > MCL.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `regulatory_table_builder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_regulatory_table_builder.py`:

```python
from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.regulatory_table_builder import (
    RegulatoryTableSpec, build_regulatory_table_specs,
    write_regulatory_workbook,
)

_ROWS = [
    {"LocationID": "MW-01", "AnalyteName": "Benzene",
     "ResultValue": "12.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
    {"LocationID": "MW-01", "AnalyteName": "Toluene",
     "ResultValue": "ND", "ResultQualifier": "ND", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
    {"LocationID": "MW-02", "AnalyteName": "Benzene",
     "ResultValue": "2.0", "ResultQualifier": "", "ReportedUnits": "ug/L",
     "SampleDate": "2026-01-15"},
]
_SL = {"Benzene": 5.0, "Toluene": 1000.0}
_GROUPS = {"Benzene": "VOC", "Toluene": "VOC"}


def test_build_specs_groups_analytes():
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    assert len(specs) == 1
    assert specs[0].analyte_group == "VOC"
    assert "Benzene" in specs[0].analytes


def test_write_workbook_produces_xlsx(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    result = write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    assert out.exists()


def test_exceedance_marker_in_cell(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    result = write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    wb = openpyxl.load_workbook(str(out))
    ws = wb["VOC"]
    found_marker = any(
        "**" in str(cell.value)
        for row in ws.iter_rows()
        for cell in row
        if cell.value
    )
    assert found_marker


def test_nd_text_in_cell(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    wb = openpyxl.load_workbook(str(out))
    ws = wb["VOC"]
    found_nd = any(
        str(cell.value) == "ND"
        for row in ws.iter_rows()
        for cell in row
        if cell.value
    )
    assert found_nd


def test_mcl_row_present(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    wb = openpyxl.load_workbook(str(out))
    ws = wb["VOC"]
    values = [str(cell.value) for row in ws.iter_rows() for cell in row if cell.value]
    assert "5.0" in values


def test_exceedance_count(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    result = write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    assert result.exceedance_count == 1  # MW-01 Benzene 12.0 > 5.0


def test_footnotes_sheet_present(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS, screening_levels=_SL)
    out = tmp_path / "reg_tables.xlsx"
    write_regulatory_workbook(_ROWS, specs, out, screening_levels=_SL)
    wb = openpyxl.load_workbook(str(out))
    assert any("Footnote" in s or "footnote" in s.lower() for s in wb.sheetnames)


def test_missing_screening_level_no_crash(tmp_path):
    specs = build_regulatory_table_specs(_ROWS, group_map=_GROUPS)
    out = tmp_path / "reg_tables.xlsx"
    result = write_regulatory_workbook(_ROWS, specs, out)
    assert out.exists()
    assert result.exceedance_count == 0
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_regulatory_table_builder.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/regulatory_table_builder.py`**

```python
"""regulatory_table_builder.py — regulatory submission pivot table (openpyxl)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

ND_QUALIFIERS = frozenset({"ND", "U", "BDL"})
_FILL_EXCEED = PatternFill(fill_type="solid", fgColor="FF9999")
_FILL_HEADER = PatternFill(fill_type="solid", fgColor="D9E1F2")


@dataclass
class RegulatoryTableSpec:
    analyte_group: str
    analytes: list
    screening_levels: dict
    units: dict


@dataclass
class RegulatoryTableResult:
    workbook_path: Path
    group_count: int
    well_count: int
    exceedance_count: int
    qa: QACollector


def build_regulatory_table_specs(
    result_rows: list,
    group_map: Optional[dict] = None,
    screening_levels: Optional[dict] = None,
) -> list:
    gm = group_map or {}
    sl = screening_levels or {}
    by_group: dict[str, set] = defaultdict(set)
    units_map: dict[str, str] = {}
    for r in result_rows:
        analyte = r.get("AnalyteName", "")
        group = gm.get(analyte, "All Analytes")
        by_group[group].add(analyte)
        if r.get("ReportedUnits"):
            units_map[analyte] = r["ReportedUnits"]

    specs = []
    for group, analytes in sorted(by_group.items()):
        sorted_analytes = sorted(analytes)
        specs.append(RegulatoryTableSpec(
            analyte_group=group,
            analytes=sorted_analytes,
            screening_levels={a: sl[a] for a in sorted_analytes if a in sl},
            units={a: units_map.get(a, "ug/L") for a in sorted_analytes},
        ))
    return specs


def write_regulatory_workbook(
    result_rows: list,
    specs: list,
    out_path: Path,
    *,
    site_id: str = "",
    event_label: str = "",
    screening_levels: Optional[dict] = None,
    nd_text: str = "ND",
    exceed_marker: str = "**",
    qa: Optional[QACollector] = None,
) -> RegulatoryTableResult:
    if qa is None:
        qa = QACollector()
    sl = screening_levels or {}

    # Index: {(loc, analyte): row}
    data: dict[tuple, dict] = {}
    for r in result_rows:
        key = (r.get("LocationID", ""), r.get("AnalyteName", ""))
        data[key] = r

    all_wells = sorted({r.get("LocationID", "") for r in result_rows})
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    total_exceedances = 0

    for spec in specs:
        ws = wb.create_sheet(spec.analyte_group[:31])
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Row 1: site header
        ws.cell(1, 1, f"Site: {site_id}")
        ws.cell(1, 3, f"Event: {event_label}")
        ws.cell(1, 5, f"Generated: {generated}")

        # Row 2: analyte headers (offset from col 2)
        ws.cell(2, 1, "Location")
        for col_idx, analyte in enumerate(spec.analytes, start=2):
            cell = ws.cell(2, col_idx, analyte)
            cell.font = Font(bold=True)
            cell.fill = _FILL_HEADER

        # Row 3: MCL values
        ws.cell(3, 1, "MCL (ug/L)")
        ws.cell(3, 1).font = Font(italic=True)
        for col_idx, analyte in enumerate(spec.analytes, start=2):
            mcl = spec.screening_levels.get(analyte)
            ws.cell(3, col_idx, mcl if mcl is not None else "—")

        # Data rows
        for row_idx, well in enumerate(all_wells, start=4):
            ws.cell(row_idx, 1, well)
            ws.cell(row_idx, 1).font = Font(bold=True)
            for col_idx, analyte in enumerate(spec.analytes, start=2):
                r = data.get((well, analyte))
                cell = ws.cell(row_idx, col_idx)
                if r is None:
                    cell.value = "—"
                else:
                    qual = r.get("ResultQualifier", "").upper().strip()
                    val_str = r.get("ResultValue", "")
                    if qual in ND_QUALIFIERS:
                        cell.value = nd_text
                    else:
                        try:
                            val = float(val_str)
                            mcl = sl.get(analyte) or spec.screening_levels.get(analyte)
                            if mcl and val > mcl:
                                cell.value = f"{val}{exceed_marker}"
                                cell.fill = _FILL_EXCEED
                                total_exceedances += 1
                            else:
                                cell.value = val
                        except (TypeError, ValueError):
                            cell.value = val_str

    # Footnotes sheet
    fn_ws = wb.create_sheet("Footnotes")
    fn_ws.cell(1, 1, "Symbol").font = Font(bold=True)
    fn_ws.cell(1, 2, "Meaning").font = Font(bold=True)
    fn_ws.cell(2, 1, exceed_marker)
    fn_ws.cell(2, 2, "Concentration exceeds the MCL/RSL")
    fn_ws.cell(3, 1, nd_text)
    fn_ws.cell(3, 2, "Not detected at or above the method detection limit")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    qa.add(QARecord(SEV_INFO, "reg_tables_built",
                    f"{len(specs)} groups, {len(all_wells)} wells, "
                    f"{total_exceedances} exceedances → {out_path}"))

    return RegulatoryTableResult(
        workbook_path=out_path,
        group_count=len(specs),
        well_count=len(all_wells),
        exceedance_count=total_exceedances,
        qa=qa,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_regulatory_table_builder.py -v
```

Expected: all 8 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/regulatory_table_builder.py \
        tests/envmon/test_regulatory_table_builder.py
git commit -m "feat(envmon): regulatory_table_builder — agency pivot table with MCL comparison"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("generate-reg-tables")
@click.option("--results", "results_path", required=True, type=click.Path(exists=True))
@click.option("--screening-levels", "sl_path", default=None, type=click.Path(exists=True))
@click.option("--group-map", "gm_path", default=None, type=click.Path(exists=True))
@click.option("--site", "site_id", default="")
@click.option("--event-label", default="")
@click.option("--out", required=True, type=click.Path())
@click.option("--report", default=None, type=click.Path())
def generate_reg_tables_cmd(results_path, sl_path, gm_path, site_id,
                             event_label, out, report):
    """Build regulatory submission pivot table workbook (headless, openpyxl)."""
    import csv as _csv, yaml as _yaml
    from autogis.core.envmon.regulatory_table_builder import (
        build_regulatory_table_specs, write_regulatory_workbook)

    with open(results_path, newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    sl = _yaml.safe_load(Path(sl_path).read_text()) if sl_path else None
    gm = _yaml.safe_load(Path(gm_path).read_text()) if gm_path else None
    specs = build_regulatory_table_specs(rows, group_map=gm, screening_levels=sl)
    result = write_regulatory_workbook(rows, specs, Path(out), site_id=site_id,
                                        event_label=event_label, screening_levels=sl)
    click.echo(f"Groups: {result.group_count}  Wells: {result.well_count}  "
               f"Exceedances: {result.exceedance_count}  Output: {out}")
    _render_qa(result.qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_generate_reg_tables_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-reg-tables" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_regulatory_table_builder.py
git commit -m "feat(cli): add generate-reg-tables command"
```
