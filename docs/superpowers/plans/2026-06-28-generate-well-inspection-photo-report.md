# GenerateWellInspectionPhotoReport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement `GenerateWellInspectionPhotoReport` — build a formatted openpyxl XLSX with one row per well, embedding field photos and inspection metadata.
See spec: `docs/superpowers/specs/2026-06-28-generate-well-inspection-photo-report-design.md`.

**Architecture:**
- New: `autogis/core/envmon/well_inspection_report.py`
- Modify: `autogis/adapters/cli.py` — add `generate-inspection-report` command (headless)
- New: `tests/envmon/test_well_inspection_report.py`

## Global Constraints

- Arcpy-free. openpyxl only (already a core dependency).
- `openpyxl.drawing.image.Image` for photo insertion; missing photos → WARNING + placeholder text.
- Run tests with `python -m pytest -q`.

---

### Task 1: Core `well_inspection_report.py`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_well_inspection_report.py`:

```python
from pathlib import Path
import pytest
import openpyxl
from autogis.core.envmon.well_inspection_report import (
    WellInspectionRecord, load_inspection_manifest,
    write_inspection_report,
)


def _make_manifest(tmp_path, include_photo=True):
    """Write a minimal manifest CSV, optionally with a real PNG photo."""
    if include_photo:
        # Create a 1×1 white PNG (valid minimal PNG bytes)
        photo = tmp_path / "MW-01.png"
        photo.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd4\x8e\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        photo_path = str(photo)
    else:
        photo_path = str(tmp_path / "missing.png")

    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "WellID,PhotoPath,GPS_Lat,GPS_Lon,InspectionDate,"
        "CompletionType,Inspector,Notes,Condition\n"
        f"MW-01,{photo_path},34.1234,-118.4567,2026-06-15,"
        "monitoring well,J.Smith,No issues.,good\n"
        "MW-02,,34.2345,-118.5678,2026-06-15,"
        "piezometer,J.Smith,Cap loose.,fair\n",
        encoding="utf-8",
    )
    return manifest


def test_load_manifest_parses_records(tmp_path):
    manifest = _make_manifest(tmp_path)
    records = load_inspection_manifest(manifest)
    assert len(records) == 2
    assert records[0].well_id == "MW-01"
    assert records[0].gps_lat == pytest.approx(34.1234)
    assert records[0].condition == "good"


def test_load_manifest_empty_gps_none(tmp_path):
    manifest = _make_manifest(tmp_path)
    records = load_inspection_manifest(manifest)
    assert records[1].gps_lat == pytest.approx(34.2345)


def test_write_report_produces_xlsx(tmp_path):
    manifest = _make_manifest(tmp_path, include_photo=True)
    records = load_inspection_manifest(manifest)
    out = tmp_path / "report.xlsx"
    result = write_inspection_report(records, out)
    assert out.exists()
    wb = openpyxl.load_workbook(str(out))
    assert len(wb.sheetnames) > 0


def test_well_count(tmp_path):
    manifest = _make_manifest(tmp_path)
    records = load_inspection_manifest(manifest)
    out = tmp_path / "report.xlsx"
    result = write_inspection_report(records, out)
    assert result.well_count == 2


def test_missing_photo_warning(tmp_path):
    manifest = _make_manifest(tmp_path, include_photo=False)
    records = load_inspection_manifest(manifest)
    out = tmp_path / "report.xlsx"
    result = write_inspection_report(records, out)
    assert result.photos_missing >= 1
    assert any(r.severity == "WARNING" for r in result.qa.records)


def test_condition_in_cell(tmp_path):
    manifest = _make_manifest(tmp_path)
    records = load_inspection_manifest(manifest)
    out = tmp_path / "report.xlsx"
    write_inspection_report(records, out)
    wb = openpyxl.load_workbook(str(out))
    ws = wb.active
    found = any(
        cell.value and "good" in str(cell.value).lower()
        for row in ws.iter_rows()
        for cell in row
    )
    assert found


def test_gps_decimal_in_cell(tmp_path):
    manifest = _make_manifest(tmp_path)
    records = load_inspection_manifest(manifest)
    out = tmp_path / "report.xlsx"
    write_inspection_report(records, out)
    wb = openpyxl.load_workbook(str(out))
    ws = wb.active
    found = any(
        cell.value and "34.1234" in str(cell.value)
        for row in ws.iter_rows()
        for cell in row
    )
    assert found
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_well_inspection_report.py -v
```

- [ ] **Step 3: Create `autogis/core/envmon/well_inspection_report.py`**

```python
"""well_inspection_report.py — openpyxl well inspection photo report."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter

from ..common.qa import QACollector, QARecord, SEV_INFO, SEV_WARNING

_HEADERS = ["Well ID", "Photo", "Coordinates", "Inspection Info", "Notes"]
_COL_WIDTHS = [18, 40, 22, 28, 40]


@dataclass
class WellInspectionRecord:
    well_id: str
    photo_path: str
    gps_lat: Optional[float]
    gps_lon: Optional[float]
    inspection_date: str
    completion_type: str
    inspector: str
    notes: str
    condition: str


@dataclass
class InspectionReportResult:
    workbook_path: Path
    well_count: int
    photos_found: int
    photos_missing: int
    qa: QACollector


def _parse_float(v: str) -> Optional[float]:
    try:
        return float(v) if v and v.strip() else None
    except (TypeError, ValueError):
        return None


def load_inspection_manifest(path: Path) -> list:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    records = []
    for r in rows:
        records.append(WellInspectionRecord(
            well_id=r.get("WellID", "").strip(),
            photo_path=r.get("PhotoPath", "").strip(),
            gps_lat=_parse_float(r.get("GPS_Lat", "")),
            gps_lon=_parse_float(r.get("GPS_Lon", "")),
            inspection_date=r.get("InspectionDate", "").strip(),
            completion_type=r.get("CompletionType", "").strip(),
            inspector=r.get("Inspector", "").strip(),
            notes=r.get("Notes", "").strip(),
            condition=r.get("Condition", "").strip(),
        ))
    return records


def write_inspection_report(
    records: list,
    out_path: Path,
    *,
    site_id: str = "",
    photo_width_px: int = 300,
    photo_height_px: int = 225,
    qa: Optional[QACollector] = None,
) -> InspectionReportResult:
    if qa is None:
        qa = QACollector()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Well Inspections"

    # Header
    ws.append(_HEADERS)
    for i, (h, w) in enumerate(zip(_HEADERS, _COL_WIDTHS), 1):
        cell = ws.cell(1, i)
        cell.font = Font(bold=True)
        ws.column_dimensions[get_column_letter(i)].width = w

    photos_found = 0
    photos_missing = 0
    row_px_height = photo_height_px + 10

    for row_num, rec in enumerate(records, start=2):
        # Column A: well ID + condition
        ws.cell(row_num, 1, f"{rec.well_id} ({rec.condition})")
        ws.cell(row_num, 1).alignment = Alignment(vertical="top")

        # Column B: photo (if exists) or placeholder
        photo_p = Path(rec.photo_path) if rec.photo_path else None
        if photo_p and photo_p.exists():
            try:
                from openpyxl.drawing.image import Image as XlImage
                img = XlImage(str(photo_p))
                img.width = photo_width_px
                img.height = photo_height_px
                cell_ref = f"B{row_num}"
                ws.add_image(img, cell_ref)
                photos_found += 1
            except Exception as exc:
                ws.cell(row_num, 2, f"[Photo error: {exc}]")
                photos_missing += 1
                qa.add(QARecord(SEV_WARNING, "photo_load_error",
                                f"{rec.well_id}: {exc}"))
        else:
            ws.cell(row_num, 2, "[Photo not found]")
            photos_missing += 1
            qa.add(QARecord(SEV_WARNING, "photo_missing",
                            f"{rec.well_id}: photo path '{rec.photo_path}' not found."))

        # Column C: GPS
        lat_str = f"{rec.gps_lat:.4f}" if rec.gps_lat is not None else "—"
        lon_str = f"{rec.gps_lon:.4f}" if rec.gps_lon is not None else "—"
        ws.cell(row_num, 3, f"{lat_str}\n{lon_str}")
        ws.cell(row_num, 3).alignment = Alignment(vertical="top", wrap_text=True)

        # Column D: inspection info
        ws.cell(row_num, 4,
                f"{rec.inspection_date}\nInspector: {rec.inspector}\n"
                f"{rec.completion_type}")
        ws.cell(row_num, 4).alignment = Alignment(vertical="top", wrap_text=True)

        # Column E: notes
        ws.cell(row_num, 5, rec.notes)
        ws.cell(row_num, 5).alignment = Alignment(vertical="top", wrap_text=True)

        # Row height
        ws.row_dimensions[row_num].height = row_px_height * 0.75  # pts ≈ px × 0.75

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))

    qa.add(QARecord(SEV_INFO, "inspection_report_built",
                    f"{len(records)} wells, {photos_found} photos found, "
                    f"{photos_missing} missing → {out_path}"))

    return InspectionReportResult(
        workbook_path=out_path,
        well_count=len(records),
        photos_found=photos_found,
        photos_missing=photos_missing,
        qa=qa,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_well_inspection_report.py -v
```

Expected: all 7 PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add autogis/core/envmon/well_inspection_report.py \
        tests/envmon/test_well_inspection_report.py
git commit -m "feat(envmon): well_inspection_report — openpyxl photo report with per-well image insertion"
```

---

### Task 2: CLI command

- [ ] **Step 1: Add to `cli.py`**

```python
@envmon.command("generate-inspection-report")
@click.option("--manifest", "manifest_path", required=True, type=click.Path(exists=True))
@click.option("--out", required=True, type=click.Path())
@click.option("--site", "site_id", default="")
@click.option("--photo-width", type=int, default=300, show_default=True)
@click.option("--photo-height", type=int, default=225, show_default=True)
@click.option("--report", default=None, type=click.Path())
def generate_inspection_report_cmd(manifest_path, out, site_id,
                                    photo_width, photo_height, report):
    """Build well inspection photo report workbook (headless, openpyxl)."""
    from autogis.core.envmon.well_inspection_report import (
        load_inspection_manifest, write_inspection_report)
    from autogis.core.common.qa import QACollector

    records = load_inspection_manifest(Path(manifest_path))
    qa = QACollector()
    result = write_inspection_report(
        records, Path(out), site_id=site_id,
        photo_width_px=photo_width, photo_height_px=photo_height, qa=qa,
    )
    click.echo(f"Wells: {result.well_count}  Photos found: {result.photos_found}  "
               f"Missing: {result.photos_missing}  Output: {out}")
    _render_qa(qa, report, "warning")
```

- [ ] **Step 2: Help test + commit**

```python
def test_generate_inspection_report_in_help():
    result = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-inspection-report" in result.output
```

```bash
git add autogis/adapters/cli.py tests/envmon/test_well_inspection_report.py
git commit -m "feat(cli): add generate-inspection-report command"
```
