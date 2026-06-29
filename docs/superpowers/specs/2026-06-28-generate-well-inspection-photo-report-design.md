# GenerateWellInspectionPhotoReport Design

**Date:** 2026-06-28
**Status:** Approved
**Tool:** GenerateWellInspectionPhotoReport (Phase 4 / Tool 7.4)
**Priority:** MEDIUM — required for annual O&M reports; saves 1–2 hours per site

---

## Problem

Annual monitoring well inspection reports require a photo inventory: one page
per well showing the well photo, GPS coordinates, completion status, and
inspection notes. Currently these are assembled manually in Word — copying
and pasting photos from a field folder, then typing coordinates from a
spreadsheet. The result is inconsistent formatting and takes 1–2 hours per site.

---

## Approach

**Chosen:** openpyxl-based photo report workbook. Reads a photo manifest CSV
(well_id, photo_path, gps_lat, gps_lon, inspection_date, notes) and inserts
each photo as an openpyxl `Image` object into a standardized layout — one row
per well with photo, coordinates, completion type, and inspector notes. Output
is a formatted XLSX suitable for PDF conversion via the boring-log PDF path.

**Rejected: Word/docx (python-docx).** Adds a dependency and produces `.docx`
files that render differently across Word versions. Excel is editable and
consistent.

**Rejected: Requiring AGOL photo download.** Photo paths are local; this tool
processes already-downloaded field photos. AGOL attachment harvesting is handled
by the existing attachment harvester domain.

---

## Architecture

```
autogis/
  core/envmon/
    well_inspection_report.py   ← NEW
  adapters/
    cli.py                      ← add generate-inspection-report command (headless)
tests/envmon/
  test_well_inspection_report.py ← NEW
```

---

## Public API (`well_inspection_report.py`)

```python
@dataclass
class WellInspectionRecord:
    well_id: str
    photo_path: str            # absolute or relative path to photo file
    gps_lat: float | None
    gps_lon: float | None
    inspection_date: str       # ISO date
    completion_type: str       # monitoring well | piezometer | soil boring | other
    inspector: str
    notes: str
    condition: str             # good | fair | poor | damaged | destroyed

@dataclass
class InspectionReportResult:
    workbook_path: Path
    well_count: int
    photos_found: int
    photos_missing: int
    qa: QACollector

def load_inspection_manifest(path: Path) -> list[WellInspectionRecord]:
    """
    Read inspection manifest CSV.
    Expected columns: WellID, PhotoPath, GPS_Lat, GPS_Lon,
    InspectionDate, CompletionType, Inspector, Notes, Condition
    """

def write_inspection_report(
    records: list[WellInspectionRecord],
    out_path: Path,
    *,
    site_id: str = "",
    photo_width_px: int = 300,
    photo_height_px: int = 225,
    qa: QACollector | None = None,
) -> InspectionReportResult:
    """
    Build openpyxl workbook. One row per well:
    - Col A: well_id + condition
    - Col B: photo (openpyxl Image)
    - Col C: GPS coordinates
    - Col D: inspection_date, inspector
    - Col E: notes
    If photo_path doesn't exist: placeholder text, WARNING in QA.
    """
```

---

## Report Layout (per row)

```
| Well ID       | Photo         | Coordinates       | Inspection Info  | Notes       |
|---------------|---------------|-------------------|------------------|-------------|
| MW-01 (good)  | [300×225 img] | 34.1234°N         | 2026-06-15       | No issues.  |
|               |               | -118.4567°W       | Inspector: J.S.  |             |
```

Row height scaled to `photo_height_px + 10` points. Column widths fixed.

---

## CLI Command

```
autogis envmon generate-inspection-report \
  --manifest <inspection_manifest.csv> \
  --out <well_inspection_report.xlsx> \
  [--site <site_id>] \
  [--photo-width 300] \
  [--photo-height 225] \
  [--report <qa.md>]
```

Headless.

---

## Test Strategy

`tests/envmon/test_well_inspection_report.py` — arcpy-free:

1. `load_inspection_manifest` parses CSV into correct WellInspectionRecord list
2. `write_inspection_report` with valid photo produces xlsx at out_path
3. Valid photo → `photos_found` count incremented
4. Missing photo file → WARNING in QA, placeholder text, `photos_missing` count
5. `well_count` equals number of input records
6. Output xlsx opens with openpyxl (valid file)
7. `condition` field appears in well ID cell text
8. GPS coordinates formatted as decimal degrees in output cells
