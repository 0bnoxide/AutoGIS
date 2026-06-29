# GenerateWellInspectionPhotoReport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GenerateWellInspectionPhotoReport` (roadmap 7.4) — assemble a per-well inspection photo report (HTML primary, optional PDF) from harvested Survey123 attachments plus inspection metadata, fully headless (no arcpy, no arcgis).

**Architecture:** A single core module `autogis/core/envmon/generate_inspection_report.py` holds all data models, the manifest reader, photo preparation (EXIF correction + resize via Pillow), HTML rendering (stdlib string building), and PDF rendering (fpdf2). The CLI command `autogis envmon generate-inspection-report` wraps it. Pillow and fpdf2 are **lazy imports** inside the functions that need them, keeping the module importable even when neither is installed, and keeping Tasks 1–3 arcpy-free and dep-free.

**Tech Stack:**
- Python stdlib: `csv`, `base64`, `io`, `pathlib`, `dataclasses`, `datetime`
- `Pillow >= 9.0` — EXIF orientation correction, image resize, RGBA→RGB conversion
- `fpdf2 >= 2.7` — headless PDF generation (pure-Python, no OS deps, accepts `BytesIO` for images)
- Both added under `[project.optional-dependencies] report = ["Pillow>=9.0", "fpdf2>=2.7"]`

## Scope

**In scope:**
- Load inspection metadata from a user-supplied CSV (`well_id, inspection_date, inspector, condition, depth_to_water_ft, notes`)
- Read the harvest `manifest.csv` written by `autogis/core/harvest/manifest.py` to find downloaded photo files
- Infer which photos belong to which well from saved-path structure (`harvest_dir/{well_id}/{filename}`)
- EXIF-correct and resize each photo (Pillow)
- Render HTML report with per-well metadata table + photo grid (base64 embedded, no external files)
- Render optional PDF report (`--pdf`, fpdf2)
- CLI command: `autogis envmon generate-inspection-report`

**Non-goals (v1):**
- No arcpy / GDB interaction of any kind
- No pulling feature attributes from AGOL/arcgis at report time (harvest already did that)
- No cover page, table of contents, or signature blocks
- No annotation or markup overlaid on photos
- PDF accessibility (tagged PDF, screen-reader support) — deferred

## Global Constraints

- `autogis/core/` and `autogis/adapters/` MUST import with neither `arcpy` nor `arcgis` present.
- Run tests with `python -m pytest -q`. All tests pass without Pillow or fpdf2 installed.
- `HarvestConfig` is canonical in `autogis/core/common/config.py` — not imported here (this tool doesn't read harvest config, only manifest output).
- Pillow and fpdf2 imports MUST be **lazy** — inside the functions that use them, never at module top.
- Tests that require Pillow begin with `PIL = pytest.importorskip("PIL")`. fpdf2-dependent tests begin with `fpdf = pytest.importorskip("fpdf")`.
- Pilot assumption (isolated in `match_photos_to_wells`): the harvest `group_template` maps to a single well_id directory, so `saved_path` has the structure `harvest_dir/{well_id}/{filename}`. Documented in module docstring.
- CLI command is headless; do NOT call `_guard()`.

---

### Task 1: Data models, inspection CSV loader, and manifest reader

**Files:**
- Create: `autogis/core/envmon/generate_inspection_report.py`
- Create: `tests/envmon/test_generate_inspection_report.py`

**Interfaces:**
- Produces:
  - `InspectionRecord` — dataclass: `well_id: str, inspection_date: str, inspector: str, condition: str = "", depth_to_water_ft: float | None = None, notes: str = ""`
  - `InspectionPhotoEntry` — dataclass: `original_name: str, saved_path: str, attachment_id: int, objectid: int, error: str | None = None, disposition: str | None = None`
  - `WellReportSection` — dataclass: `well_id: str, record: InspectionRecord | None, photos: list[InspectionPhotoEntry]`
  - `load_inspection_records(path: Path) -> list[InspectionRecord]`
  - `match_photos_to_wells(manifest_csv: Path, harvest_dir: Path) -> dict[str, list[InspectionPhotoEntry]]`
  - `build_sections(records: list[InspectionRecord], photo_map: dict[str, list[InspectionPhotoEntry]]) -> list[WellReportSection]`

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_generate_inspection_report.py`:

```python
import csv
import pytest
from pathlib import Path

from autogis.core.envmon.generate_inspection_report import (
    InspectionRecord, InspectionPhotoEntry, WellReportSection,
    load_inspection_records, match_photos_to_wells, build_sections,
)


# ── load_inspection_records ──────────────────────────────────────────────────

def _write_inspections_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "well_id", "inspection_date", "inspector",
            "condition", "depth_to_water_ft", "notes",
        ])
        w.writeheader()
        w.writerow({
            "well_id": "MW-01", "inspection_date": "2026-06-15",
            "inspector": "J. Smith", "condition": "Good",
            "depth_to_water_ft": "12.34", "notes": "No visible damage",
        })
        w.writerow({
            "well_id": "MW-02", "inspection_date": "2026-06-15",
            "inspector": "J. Smith", "condition": "Fair",
            "depth_to_water_ft": "", "notes": "Minor corrosion",
        })


def test_load_inspection_records_parses_rows(tmp_path):
    p = tmp_path / "inspections.csv"
    _write_inspections_csv(p)
    records = load_inspection_records(p)
    assert len(records) == 2
    assert records[0].well_id == "MW-01"
    assert records[0].depth_to_water_ft == pytest.approx(12.34)
    assert records[0].condition == "Good"


def test_load_inspection_records_none_for_blank_dtw(tmp_path):
    p = tmp_path / "inspections.csv"
    _write_inspections_csv(p)
    records = load_inspection_records(p)
    assert records[1].depth_to_water_ft is None


def test_load_inspection_records_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text(
        "well_id,inspection_date,inspector,condition,depth_to_water_ft,notes\n",
        encoding="utf-8",
    )
    assert load_inspection_records(p) == []


# ── match_photos_to_wells ────────────────────────────────────────────────────

def _write_manifest_csv(path: Path, harvest_dir: Path) -> None:
    rows = [
        {   # downloaded, explicit disposition
            "objectid": 1, "attachment_id": 101,
            "original_name": "photo_a.jpg",
            "saved_path": str(harvest_dir / "MW-01" / "photo_a.jpg"),
            "size": 50000, "status": "downloaded",
            "error": "", "disposition": "downloaded",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        },
        {   # skipped (file exists on disk)
            "objectid": 2, "attachment_id": 102,
            "original_name": "photo_b.jpg",
            "saved_path": str(harvest_dir / "MW-01" / "photo_b.jpg"),
            "size": 60000, "status": "skipped",
            "error": "", "disposition": "skipped",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        },
        {   # failed — no saved_path; must be excluded
            "objectid": 3, "attachment_id": 103,
            "original_name": "photo_c.jpg",
            "saved_path": "",
            "size": 0, "status": "failed",
            "error": "Connection timeout", "disposition": "failed",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        },
        {   # blank disposition, status=downloaded → fallback to status
            "objectid": 4, "attachment_id": 104,
            "original_name": "photo_d.jpg",
            "saved_path": str(harvest_dir / "MW-02" / "photo_d.jpg"),
            "size": 45000, "status": "downloaded",
            "error": "", "disposition": "",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        },
    ]
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_match_photos_groups_by_well(tmp_path):
    harvest_dir = tmp_path / "harvest"
    manifest = tmp_path / "manifest.csv"
    _write_manifest_csv(manifest, harvest_dir)
    photo_map = match_photos_to_wells(manifest, harvest_dir)
    assert "MW-01" in photo_map
    assert len(photo_map["MW-01"]) == 2   # downloaded + skipped


def test_match_photos_excludes_failed_entries(tmp_path):
    harvest_dir = tmp_path / "harvest"
    manifest = tmp_path / "manifest.csv"
    _write_manifest_csv(manifest, harvest_dir)
    photo_map = match_photos_to_wells(manifest, harvest_dir)
    all_entries = [e for entries in photo_map.values() for e in entries]
    assert not any(e.original_name == "photo_c.jpg" for e in all_entries)


def test_match_photos_blank_disposition_falls_back_to_status(tmp_path):
    harvest_dir = tmp_path / "harvest"
    manifest = tmp_path / "manifest.csv"
    _write_manifest_csv(manifest, harvest_dir)
    photo_map = match_photos_to_wells(manifest, harvest_dir)
    # MW-02's row has blank disposition but status=downloaded — must appear
    assert "MW-02" in photo_map
    assert len(photo_map["MW-02"]) == 1


def test_match_photos_missing_manifest(tmp_path):
    photo_map = match_photos_to_wells(tmp_path / "nonexistent.csv", tmp_path)
    assert photo_map == {}


def test_match_photos_path_outside_harvest_dir_is_skipped(tmp_path):
    """Rows whose saved_path is not under harvest_dir are silently dropped."""
    harvest_dir = tmp_path / "harvest"
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "objectid", "attachment_id", "original_name", "saved_path",
            "size", "status", "error", "disposition",
            "checksum", "algorithm", "geometry", "source_table", "relationship_id",
        ])
        w.writeheader()
        w.writerow({
            "objectid": 9, "attachment_id": 999,
            "original_name": "stray.jpg",
            "saved_path": str(tmp_path / "other_dir" / "stray.jpg"),
            "size": 1000, "status": "downloaded",
            "error": "", "disposition": "downloaded",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        })
    photo_map = match_photos_to_wells(manifest, harvest_dir)
    assert photo_map == {}


# ── build_sections ───────────────────────────────────────────────────────────

def test_build_sections_union_of_well_ids():
    records = [InspectionRecord("MW-01", "2026-06-15", "J. Smith")]
    photo_map = {
        "MW-01": [InspectionPhotoEntry("a.jpg", "/h/MW-01/a.jpg", 1, 1)],
        "MW-03": [InspectionPhotoEntry("b.jpg", "/h/MW-03/b.jpg", 2, 2)],
    }
    sections = build_sections(records, photo_map)
    well_ids = [s.well_id for s in sections]
    assert "MW-01" in well_ids
    assert "MW-03" in well_ids   # photos-only well; no inspection record


def test_build_sections_record_none_for_photos_only_well():
    photo_map = {"MW-03": [InspectionPhotoEntry("b.jpg", "/h/MW-03/b.jpg", 2, 2)]}
    sections = build_sections([], photo_map)
    s = next(s for s in sections if s.well_id == "MW-03")
    assert s.record is None


def test_build_sections_empty_photos_for_record_only_well():
    records = [InspectionRecord("MW-04", "2026-06-15", "J. Smith")]
    sections = build_sections(records, {})
    s = next(s for s in sections if s.well_id == "MW-04")
    assert s.photos == []


def test_build_sections_sorted_by_well_id():
    records = [
        InspectionRecord("MW-02", "2026-06-15", "J. Smith"),
        InspectionRecord("MW-01", "2026-06-15", "J. Smith"),
    ]
    sections = build_sections(records, {})
    assert [s.well_id for s in sections] == ["MW-01", "MW-02"]
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_generate_inspection_report.py -v
```

Expected: `ModuleNotFoundError` — `generate_inspection_report` does not exist yet.

- [ ] **Step 3: Create `autogis/core/envmon/generate_inspection_report.py`**

```python
"""generate_inspection_report.py — per-well inspection photo report (Tool 7.4).

Assembles an HTML report (and optionally PDF) from:
  - A harvest manifest.csv written by autogis/core/harvest/manifest.py
  - An inspection metadata CSV (well_id, inspection_date, inspector, ...)

PILOT ASSUMPTION: The harvest run used group_template = "{WellID}" (or an
equivalent single-level template), so every saved_path has the structure:
    harvest_dir/{well_id}/{filename}

This assumption is isolated in match_photos_to_wells(). If the group_template
was not well-id-based, override photo_map before calling build_sections().

Pillow and fpdf2 are lazy imports inside the functions that need them. The
module imports cleanly without either installed. Tasks 1–3 (models + HTML)
require only stdlib.

No arcpy. No arcgis.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class InspectionRecord:
    well_id: str
    inspection_date: str            # ISO "YYYY-MM-DD"
    inspector: str
    condition: str = ""
    depth_to_water_ft: Optional[float] = None
    notes: str = ""


@dataclass
class InspectionPhotoEntry:
    original_name: str
    saved_path: str
    attachment_id: int
    objectid: int
    error: Optional[str] = None
    disposition: Optional[str] = None


@dataclass
class WellReportSection:
    well_id: str
    record: Optional[InspectionRecord]
    photos: list[InspectionPhotoEntry] = field(default_factory=list)


# ── Loaders ──────────────────────────────────────────────────────────────────

def load_inspection_records(path: Path) -> list[InspectionRecord]:
    """Load inspection metadata rows from a CSV file."""
    records: list[InspectionRecord] = []
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dtw_raw = (row.get("depth_to_water_ft") or "").strip()
            records.append(InspectionRecord(
                well_id=row.get("well_id", "").strip(),
                inspection_date=row.get("inspection_date", "").strip(),
                inspector=row.get("inspector", "").strip(),
                condition=row.get("condition", "").strip(),
                depth_to_water_ft=float(dtw_raw) if dtw_raw else None,
                notes=row.get("notes", "").strip(),
            ))
    return records


def match_photos_to_wells(
    manifest_csv: Path,
    harvest_dir: Path,
) -> dict[str, list[InspectionPhotoEntry]]:
    """Group harvest attachments by well_id.

    well_id is inferred as the first path component of saved_path relative to
    harvest_dir — matching the harvester's group_template = "{WellID}" pattern.

    Only rows whose effective disposition is "downloaded" or "skipped" are
    included (those have a usable saved_path). The disposition field mirrors
    the AttachmentResult fallback: ``disposition or status``.
    """
    manifest_csv = Path(manifest_csv)
    harvest_dir = Path(harvest_dir)
    photo_map: dict[str, list[InspectionPhotoEntry]] = {}

    if not manifest_csv.exists():
        return photo_map

    with manifest_csv.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # Mirror AttachmentResult summary: disposition falling back to status
            eff = (row.get("disposition") or row.get("status") or "").strip()
            if eff not in ("downloaded", "skipped"):
                continue
            saved = (row.get("saved_path") or "").strip()
            if not saved:
                continue
            try:
                rel = Path(saved).relative_to(harvest_dir)
                well_id = rel.parts[0]
            except (ValueError, IndexError):
                continue   # path not under harvest_dir; skip

            entry = InspectionPhotoEntry(
                original_name=row.get("original_name", ""),
                saved_path=saved,
                attachment_id=int(row.get("attachment_id") or 0),
                objectid=int(row.get("objectid") or 0),
                error=row.get("error") or None,
                disposition=eff,
            )
            photo_map.setdefault(well_id, []).append(entry)

    return photo_map


def build_sections(
    records: list[InspectionRecord],
    photo_map: dict[str, list[InspectionPhotoEntry]],
) -> list[WellReportSection]:
    """Build report sections for the union of wells in records + photo_map.

    Sections are sorted by well_id. A well that has photos but no inspection
    row gets record=None. A well that has a record but no photos gets photos=[].
    """
    record_by_id = {r.well_id: r for r in records}
    all_ids = sorted(set(record_by_id) | set(photo_map))
    return [
        WellReportSection(
            well_id=wid,
            record=record_by_id.get(wid),
            photos=photo_map.get(wid, []),
        )
        for wid in all_ids
    ]
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_generate_inspection_report.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/generate_inspection_report.py \
        tests/envmon/test_generate_inspection_report.py
git commit -m "feat(envmon): generate_inspection_report — models, CSV loader, manifest reader"
```

---

### Task 2: Photo preparation (EXIF correction, resize, RGBA→RGB)

Adds `_load_prepared_image()` to the core module. Pillow is imported lazily inside the function. Tests skip the entire file when Pillow is absent.

**Files:**
- Modify: `autogis/core/envmon/generate_inspection_report.py` (append photo function)
- Create: `tests/envmon/test_inspection_report_photos.py`

**Interfaces:**
- Consumes: `PIL.Image`, `PIL.ImageOps`
- Produces:
  - `_load_prepared_image(path: Path, max_px: int) -> PIL.Image.Image | None`
    — opens, EXIF-transposes, converts RGBA→RGB, thumbnails. Returns `None` if file missing.

- [ ] **Step 1: Write failing tests**

Create `tests/envmon/test_inspection_report_photos.py`:

```python
"""Photo preparation tests. Skipped entirely when Pillow is not installed."""
import io
import pytest
from pathlib import Path

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402 — after importorskip

from autogis.core.envmon.generate_inspection_report import _load_prepared_image


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_jpeg(tmp_path: Path, width: int = 4, height: int = 2,
               orientation: int = 1) -> Path:
    """Write a tiny JPEG with the given EXIF orientation tag."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    exif = img.getexif()
    exif[274] = orientation   # 274 = Orientation tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    p = tmp_path / f"test_{width}x{height}_orient{orientation}.jpg"
    p.write_bytes(buf.getvalue())
    return p


def _make_rgba_png(tmp_path: Path) -> Path:
    img = Image.new("RGBA", (4, 4), color=(0, 255, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p = tmp_path / "rgba.png"
    p.write_bytes(buf.getvalue())
    return p


# ── _load_prepared_image ─────────────────────────────────────────────────────

def test_load_prepared_image_returns_pil_image(tmp_path):
    p = _make_jpeg(tmp_path, orientation=1)
    result = _load_prepared_image(p, max_px=800)
    assert result is not None
    assert hasattr(result, "size")   # PIL Image has .size attribute


def test_load_prepared_image_missing_file_returns_none(tmp_path):
    result = _load_prepared_image(tmp_path / "nonexistent.jpg", max_px=800)
    assert result is None


def test_exif_orientation_6_transposes_dimensions(tmp_path):
    """Orientation=6 (90° CW): a 4×2 pixel image becomes 2×4 after transpose."""
    p = _make_jpeg(tmp_path, width=4, height=2, orientation=6)
    img = _load_prepared_image(p, max_px=800)
    assert img is not None
    w, h = img.size
    assert h > w, f"Expected portrait after orientation-6 transpose, got {w}×{h}"


def test_exif_orientation_1_unchanged(tmp_path):
    """Normal orientation: 4×2 stays 4×2."""
    p = _make_jpeg(tmp_path, width=4, height=2, orientation=1)
    img = _load_prepared_image(p, max_px=800)
    assert img is not None
    assert img.size == (4, 2)


def test_oversized_photo_resized_to_max_px(tmp_path):
    """A 1600×900 image resized to max_px=800 fits within 800×800."""
    p = _make_jpeg(tmp_path, width=1600, height=900, orientation=1)
    img = _load_prepared_image(p, max_px=800)
    assert img is not None
    assert max(img.size) <= 800


def test_small_photo_not_upscaled(tmp_path):
    """thumbnail() never upscales: 4×2 with max_px=800 stays 4×2."""
    p = _make_jpeg(tmp_path, width=4, height=2, orientation=1)
    img = _load_prepared_image(p, max_px=800)
    assert img is not None
    assert img.size == (4, 2)


def test_rgba_png_converted_to_rgb(tmp_path):
    """RGBA PNG converted to RGB so it can be JPEG-encoded without OSError."""
    p = _make_rgba_png(tmp_path)
    img = _load_prepared_image(p, max_px=800)
    assert img is not None
    assert img.mode == "RGB"


def test_load_prepared_image_no_pillow_raises(tmp_path, monkeypatch):
    """ImportError with helpful message when Pillow is not installed."""
    import sys
    import autogis.core.envmon.generate_inspection_report as mod
    p = _make_jpeg(tmp_path)

    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _block_pil(name, *args, **kwargs):
        if name in ("PIL", "PIL.Image", "PIL.ImageOps"):
            raise ImportError("No module named 'PIL'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block_pil)
    with pytest.raises(ImportError, match="Pillow"):
        mod._load_prepared_image(p, max_px=800)
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_inspection_report_photos.py -v
```

Expected: `AttributeError` — `_load_prepared_image` not defined yet (or `ImportError` if Pillow absent, in which case the file skips cleanly).

- [ ] **Step 3: Append photo function to `autogis/core/envmon/generate_inspection_report.py`**

Add this block after `build_sections`:

```python
# ── Photo preparation (Pillow — lazy import) ──────────────────────────────────

def _load_prepared_image(path: Path, max_px: int):
    """Open a photo, apply EXIF orientation, resize, and convert to RGB.

    Returns a ``PIL.Image.Image``, or ``None`` if the file does not exist.
    Raises ``ImportError`` with a clear install hint when Pillow is absent.

    Steps:
    1. ``PIL.ImageOps.exif_transpose`` reads EXIF tag 274 (Orientation) and
       rotates/flips the pixel data to match, then strips the tag. This
       corrects the common "iPhone landscape photo displays portrait" problem.
    2. RGBA images (e.g., PNG with transparency) are composited onto a white
       RGB background — JPEG does not support an alpha channel.
    3. ``PIL.Image.thumbnail`` shrinks the image to fit within
       ``max_px × max_px`` preserving aspect ratio. It never upscales.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for photo processing. "
            "Install with: pip install 'autogis[report]'"
        ) from exc

    path = Path(path)
    if not path.exists():
        return None

    img = Image.open(path)
    img = ImageOps.exif_transpose(img)   # apply EXIF orientation, strip tag

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])   # alpha channel as paste mask
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.thumbnail((max_px, max_px), Image.LANCZOS)
    return img
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/envmon/test_inspection_report_photos.py -v
```

Expected: all 8 tests PASS (or the file is skipped cleanly if Pillow is absent).

Note: `test_load_prepared_image_no_pillow_raises` patches `builtins.__import__` to simulate a missing Pillow. If the monkeypatch approach is flaky in your environment, replace it with a direct module-level mock:

```python
def test_load_prepared_image_no_pillow_raises(tmp_path, monkeypatch):
    import autogis.core.envmon.generate_inspection_report as mod
    p = _make_jpeg(tmp_path)
    import unittest.mock as mock
    with mock.patch.dict("sys.modules", {"PIL": None, "PIL.Image": None, "PIL.ImageOps": None}):
        with pytest.raises(ImportError, match="Pillow"):
            mod._load_prepared_image(p, max_px=800)
```

- [ ] **Step 5: Full suite + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/generate_inspection_report.py \
        tests/envmon/test_inspection_report_photos.py
git commit -m "feat(envmon): _load_prepared_image — EXIF transpose, resize, RGBA→RGB"
```

---

### Task 3: HTML report renderer

Adds `build_html_report()`. Photos are base64-encoded JPEG data URIs — no external files required to render. HTML tests mock `_load_prepared_image` and need no Pillow.

**Files:**
- Modify: `autogis/core/envmon/generate_inspection_report.py` (append HTML helpers + `build_html_report`)
- Modify: `tests/envmon/test_generate_inspection_report.py` (append HTML tests)

**Interfaces:**
- Consumes: `list[WellReportSection]`, `_load_prepared_image` (mocked in tests)
- Produces:
  - `build_html_report(sections, *, site_id, harvest_dir, max_photo_px=800, title=None, generated_date=None) -> str`

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_generate_inspection_report.py`:

```python
import base64
import io
import unittest.mock as mock

from autogis.core.envmon.generate_inspection_report import build_html_report


# ── Helpers ──────────────────────────────────────────────────────────────────

class _StubImg:
    """Minimal object satisfying the PIL.Image.Image protocol used in renderer."""
    def save(self, buf, format="JPEG", quality=75, **kw):
        buf.write(b"FAKEJPEG")

    @property
    def size(self):
        return (4, 2)


def _make_section(well_id="MW-01", with_record=True, photo_paths=None):
    record = InspectionRecord(
        well_id=well_id, inspection_date="2026-06-15",
        inspector="J. Smith", condition="Good",
        depth_to_water_ft=12.34, notes="No issues.",
    ) if with_record else None
    photos = [
        InspectionPhotoEntry(p, p, idx + 1, idx + 1)
        for idx, p in enumerate(photo_paths or [])
    ]
    return WellReportSection(well_id=well_id, record=record, photos=photos)


_PATCH = "autogis.core.envmon.generate_inspection_report._load_prepared_image"


# ── build_html_report ────────────────────────────────────────────────────────

def test_build_html_report_contains_site_id(tmp_path):
    sections = [_make_section()]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "H281" in html


def test_build_html_report_contains_well_id(tmp_path):
    sections = [_make_section("MW-07")]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "MW-07" in html


def test_build_html_report_metadata_in_output(tmp_path):
    sections = [_make_section()]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "J. Smith" in html
    assert "12.34" in html
    assert "Good" in html


def test_build_html_report_no_photos_shows_placeholder(tmp_path):
    sections = [_make_section(photo_paths=[])]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "No photos" in html


def test_build_html_report_embeds_base64_photo(tmp_path):
    photo_path = str(tmp_path / "MW-01" / "photo.jpg")
    sections = [_make_section(photo_paths=[photo_path])]
    with mock.patch(_PATCH, return_value=_StubImg()):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    expected_b64 = base64.b64encode(b"FAKEJPEG").decode()
    assert expected_b64 in html


def test_build_html_report_custom_title(tmp_path):
    sections = [_make_section()]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path,
                                 title="Q2 2026 Inspection Report")
    assert "Q2 2026 Inspection Report" in html


def test_build_html_report_no_record_shows_placeholder(tmp_path):
    sections = [_make_section("MW-99", with_record=False)]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "MW-99" in html
    assert "No inspection record" in html


def test_build_html_report_file_not_on_disk_shows_placeholder(tmp_path):
    """When _load_prepared_image returns None the renderer emits a placeholder."""
    photo_path = str(tmp_path / "MW-01" / "missing.jpg")
    sections = [_make_section(photo_paths=[photo_path])]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert "not on disk" in html or "missing" in html.lower()


def test_build_html_report_is_valid_html(tmp_path):
    sections = [_make_section()]
    with mock.patch(_PATCH, return_value=None):
        html = build_html_report(sections, site_id="H281", harvest_dir=tmp_path)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_generate_inspection_report.py -v -k "html"
```

Expected: `ImportError` — `build_html_report` not defined yet.

- [ ] **Step 3: Append HTML helpers + renderer to `autogis/core/envmon/generate_inspection_report.py`**

Add after `_load_prepared_image`:

```python
# ── HTML renderer ─────────────────────────────────────────────────────────────

_HTML_STYLE = """\
body{font-family:Arial,sans-serif;margin:2em;color:#222}
h1{color:#2c5f8a}
.well-section{margin-top:2em;page-break-before:always}
.well-section:first-of-type{page-break-before:avoid}
.well-header{background:#2c5f8a;color:#fff;padding:.5em 1em;margin-bottom:.5em}
.well-header h2{margin:0;font-size:1.25em}
.meta-table td{padding:.2em .6em;vertical-align:top}
.meta-table td:first-child{font-weight:bold;white-space:nowrap}
.photo-grid{display:flex;flex-wrap:wrap;gap:1em;margin-top:1em}
.photo-card{border:1px solid #ccc;padding:.5em;max-width:440px}
.photo-card img{max-width:420px;display:block}
.photo-caption{font-size:.85em;color:#555;margin-top:.3em}
.no-photos{color:#888;font-style:italic;margin-top:.5em}
.no-record{color:#c80;font-style:italic}
@media print{
  .well-section{page-break-before:always}
  .well-section:first-of-type{page-break-before:avoid}
}
"""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _meta_row(label: str, value) -> str:
    return (f"<tr><td>{_esc(label)}</td>"
            f"<td>{_esc(str(value) if value is not None else '—')}</td></tr>")


def _render_well_section_html(
    section: WellReportSection,
    harvest_dir: Path,
    max_photo_px: int,
) -> str:
    import base64
    import io as _io

    parts: list[str] = [
        '<div class="well-section">',
        f'<div class="well-header"><h2>{_esc(section.well_id)}</h2></div>',
    ]

    if section.record:
        r = section.record
        dtw = f"{r.depth_to_water_ft:.2f} ft" if r.depth_to_water_ft is not None else "—"
        parts += [
            '<table class="meta-table">',
            _meta_row("Inspection Date:", r.inspection_date),
            _meta_row("Inspector:", r.inspector),
            _meta_row("Condition:", r.condition or "—"),
            _meta_row("Depth to Water:", dtw),
            _meta_row("Notes:", r.notes or "—"),
            "</table>",
        ]
    else:
        parts.append('<p class="no-record">No inspection record for this well.</p>')

    if section.photos:
        parts.append('<div class="photo-grid">')
        for entry in section.photos:
            img = _load_prepared_image(Path(entry.saved_path), max_photo_px)
            if img is None:
                parts.append(
                    f'<div class="photo-card">'
                    f'<p class="no-photos">File not on disk: '
                    f'{_esc(entry.original_name)}</p></div>'
                )
                continue
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            b64 = base64.b64encode(buf.getvalue()).decode()
            parts.append(
                f'<div class="photo-card">'
                f'<img src="data:image/jpeg;base64,{b64}" '
                f'alt="{_esc(entry.original_name)}">'
                f'<p class="photo-caption">{_esc(entry.original_name)}</p>'
                f'</div>'
            )
        parts.append("</div>")
    else:
        parts.append('<p class="no-photos">No photos downloaded for this well.</p>')

    parts.append("</div>")
    return "\n".join(parts)


def build_html_report(
    sections: list[WellReportSection],
    *,
    site_id: str,
    harvest_dir: Path,
    max_photo_px: int = 800,
    title: Optional[str] = None,
    generated_date: Optional[str] = None,
) -> str:
    """Assemble the inspection photo report as a self-contained HTML string.

    Photos are embedded as base64 JPEG data URIs — no external files required
    to render. Print-media CSS (``page-break-before: always``) produces clean
    per-well pages when the HTML is printed to PDF from a browser.

    Args:
        sections: list of WellReportSection from build_sections().
        site_id: site identifier for the header.
        harvest_dir: root directory of the harvest run (path resolution for
            _load_prepared_image).
        max_photo_px: max dimension in pixels per embedded photo (default 800).
        title: report title override.
        generated_date: ISO date string for header (defaults to today).
    """
    from datetime import date

    harvest_dir = Path(harvest_dir)
    report_title = title or f"Well Inspection Photo Report — {site_id}"
    gen_date = generated_date or date.today().isoformat()

    body = "\n".join(
        _render_well_section_html(s, harvest_dir, max_photo_px)
        for s in sections
    )

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        f"<title>{_esc(report_title)}</title>\n"
        f"<style>\n{_HTML_STYLE}\n</style>\n"
        "</head>\n<body>\n"
        f"<h1>{_esc(report_title)}</h1>\n"
        f"<p>Site: <strong>{_esc(site_id)}</strong> &bull; "
        f"Generated: {_esc(gen_date)}</p>\n"
        f"{body}\n"
        "</body>\n</html>"
    )
```

- [ ] **Step 4: Run all tests**

```
python -m pytest tests/envmon/test_generate_inspection_report.py -v
```

Expected: all 21 tests PASS (HTML tests pass without Pillow via mocked `_load_prepared_image`).

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/generate_inspection_report.py \
        tests/envmon/test_generate_inspection_report.py
git commit -m "feat(envmon): build_html_report — base64 photo grid, per-well metadata, print-CSS"
```

---

### Task 4: CLI command + pyproject.toml extras

Wires the core into `autogis envmon generate-inspection-report`.

**Files:**
- Modify: `autogis/adapters/cli.py` — add command (headless section, before the LOCAL/arcpy block)
- Modify: `pyproject.toml` — add `report` optional extras
- Create: `tests/envmon/test_cli_generate_inspection_report.py`

**Interfaces:**
- Consumes: `load_inspection_records`, `match_photos_to_wells`, `build_sections`, `build_html_report`, `build_pdf_report` from `autogis.core.envmon.generate_inspection_report`
- Produces: CLI command `autogis envmon generate-inspection-report`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/envmon/test_cli_generate_inspection_report.py`:

```python
import csv
import unittest.mock as mock
from pathlib import Path

import pytest
from click.testing import CliRunner

from autogis.adapters.cli import autogis

_PATCH = "autogis.core.envmon.generate_inspection_report._load_prepared_image"


def _write_inspections_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "well_id", "inspection_date", "inspector",
            "condition", "depth_to_water_ft", "notes",
        ])
        w.writeheader()
        w.writerow({
            "well_id": "MW-01", "inspection_date": "2026-06-15",
            "inspector": "J. Smith", "condition": "Good",
            "depth_to_water_ft": "12.34", "notes": "OK",
        })


def _write_empty_manifest(path: Path) -> None:
    path.write_text(
        "objectid,attachment_id,original_name,saved_path,size,status,"
        "error,disposition,checksum,algorithm,geometry,source_table,relationship_id\n",
        encoding="utf-8",
    )


def test_generate_inspection_report_in_help():
    r = CliRunner().invoke(autogis, ["envmon", "--help"])
    assert "generate-inspection-report" in r.output


def test_generate_inspection_report_requires_inspections_file(tmp_path):
    """Missing --inspections file → non-zero exit (click type=Path(exists=True))."""
    manifest = tmp_path / "manifest.csv"
    _write_empty_manifest(manifest)
    r = CliRunner().invoke(autogis, [
        "envmon", "generate-inspection-report",
        "--manifest", str(manifest),
        "--harvest-dir", str(tmp_path),
        "--inspections", str(tmp_path / "nonexistent.csv"),
        "--site", "H281",
        "--output", str(tmp_path / "report.html"),
    ])
    assert r.exit_code != 0


def test_generate_inspection_report_writes_html_no_photos(tmp_path):
    """HTML is written when manifest is empty (no photos for any well)."""
    insp = tmp_path / "inspections.csv"
    _write_inspections_csv(insp)
    manifest = tmp_path / "manifest.csv"
    _write_empty_manifest(manifest)
    out = tmp_path / "report.html"

    r = CliRunner().invoke(autogis, [
        "envmon", "generate-inspection-report",
        "--manifest", str(manifest),
        "--harvest-dir", str(tmp_path),
        "--inspections", str(insp),
        "--site", "H281",
        "--output", str(out),
    ])
    assert r.exit_code == 0, r.output
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "H281" in html
    assert "MW-01" in html
    assert "No photos" in html


def test_generate_inspection_report_with_photo_mock(tmp_path):
    """When photo loading is mocked, report includes base64 image block."""
    import base64

    class _StubImg:
        def save(self, buf, format="JPEG", quality=75, **kw):
            buf.write(b"FAKEPDF")

    insp = tmp_path / "inspections.csv"
    _write_inspections_csv(insp)
    harvest_dir = tmp_path / "harvest"
    photo_file = harvest_dir / "MW-01" / "photo.jpg"
    photo_file.parent.mkdir(parents=True, exist_ok=True)
    photo_file.write_bytes(b"FAKEPHOTOBYTES")
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "objectid", "attachment_id", "original_name", "saved_path",
            "size", "status", "error", "disposition",
            "checksum", "algorithm", "geometry", "source_table", "relationship_id",
        ])
        w.writeheader()
        w.writerow({
            "objectid": 1, "attachment_id": 101, "original_name": "photo.jpg",
            "saved_path": str(photo_file), "size": 14,
            "status": "downloaded", "error": "", "disposition": "downloaded",
            "checksum": "", "algorithm": "", "geometry": "",
            "source_table": "", "relationship_id": "",
        })
    out = tmp_path / "report.html"
    with mock.patch(_PATCH, return_value=_StubImg()):
        r = CliRunner().invoke(autogis, [
            "envmon", "generate-inspection-report",
            "--manifest", str(manifest),
            "--harvest-dir", str(harvest_dir),
            "--inspections", str(insp),
            "--site", "H281",
            "--output", str(out),
        ])
    assert r.exit_code == 0, r.output
    html = out.read_text(encoding="utf-8")
    assert base64.b64encode(b"FAKEPDF").decode() in html


def test_generate_inspection_report_echo_written(tmp_path):
    insp = tmp_path / "inspections.csv"
    _write_inspections_csv(insp)
    manifest = tmp_path / "manifest.csv"
    _write_empty_manifest(manifest)
    out = tmp_path / "report.html"
    r = CliRunner().invoke(autogis, [
        "envmon", "generate-inspection-report",
        "--manifest", str(manifest),
        "--harvest-dir", str(tmp_path),
        "--inspections", str(insp),
        "--site", "H281",
        "--output", str(out),
    ])
    assert r.exit_code == 0, r.output
    assert "Written:" in r.output
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_cli_generate_inspection_report.py -v
```

Expected: FAIL on `test_generate_inspection_report_in_help` — command not registered yet.

- [ ] **Step 3: Add command to `autogis/adapters/cli.py`**

Locate the headless command block (after `@envmon.command("generate-event-report")` is a natural anchor). Insert the new command there:

```python
@envmon.command("generate-inspection-report")
@click.option("--manifest", "manifest_csv", required=True, type=click.Path(exists=True),
              help="harvest manifest.csv produced by 'autogis harvest'.")
@click.option("--harvest-dir", required=True, type=click.Path(exists=True),
              help="Root directory of the harvested attachment tree.")
@click.option("--inspections", "inspections_csv", required=True,
              type=click.Path(exists=True),
              help="CSV of inspection metadata: well_id, inspection_date, inspector, "
                   "condition, depth_to_water_ft, notes.")
@click.option("--site", "site_id", required=True,
              help="Site identifier for the report header.")
@click.option("--output", required=True, type=click.Path(),
              help="Output HTML file path.")
@click.option("--title", default=None,
              help="Report title (default: 'Well Inspection Photo Report — {site_id}').")
@click.option("--max-photo-px", type=int, default=800, show_default=True,
              help="Max dimension (px) per embedded photo.")
@click.option("--pdf", "pdf_path", default=None, type=click.Path(),
              help="Also write a PDF to this path (requires fpdf2; "
                   "install with: pip install 'autogis[report]').")
def generate_inspection_report_cmd(
    manifest_csv, harvest_dir, inspections_csv, site_id,
    output, title, max_photo_px, pdf_path,
):
    """Tool 7.4: assemble per-well inspection photo report (HTML/PDF, headless)."""
    from autogis.core.envmon.generate_inspection_report import (
        load_inspection_records, match_photos_to_wells,
        build_sections, build_html_report, build_pdf_report,
    )
    records = load_inspection_records(Path(inspections_csv))
    photo_map = match_photos_to_wells(Path(manifest_csv), Path(harvest_dir))
    sections = build_sections(records, photo_map)

    html = build_html_report(
        sections,
        site_id=site_id,
        harvest_dir=Path(harvest_dir),
        max_photo_px=max_photo_px,
        title=title,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    click.echo(f"Written: {out}")

    if pdf_path:
        build_pdf_report(
            sections,
            site_id=site_id,
            harvest_dir=Path(harvest_dir),
            output_path=Path(pdf_path),
            max_photo_px=max_photo_px,
            title=title,
        )
        click.echo(f"PDF written: {pdf_path}")
```

- [ ] **Step 4: Add optional extras to `pyproject.toml`**

Replace the existing `[project.optional-dependencies]` block:

```toml
[project.optional-dependencies]
dev = ["pytest", "Pillow>=9.0", "fpdf2>=2.7"]
cloud = ["arcgis>=2.4,<3"]
report = ["Pillow>=9.0", "fpdf2>=2.7"]
```

> **Why dev includes Pillow + fpdf2:** Without them in the dev/test install, the
> `pytest.importorskip` guards at the top of `test_inspection_report_photos.py`
> cause the entire file to skip silently — the EXIF, resize, RGBA, and PDF tests
> never run and the risk mitigations are unverified. Keeping them out of the base
> `dependencies = [...]` list preserves the import-clean invariant (the module
> still imports without them); only the test environment requires them.

- [ ] **Step 5: Run CLI tests**

```
python -m pytest tests/envmon/test_cli_generate_inspection_report.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Full suite + commit**

```bash
python -m pytest -q
git add autogis/adapters/cli.py \
        pyproject.toml \
        tests/envmon/test_cli_generate_inspection_report.py
git commit -m "feat(cli): add generate-inspection-report command (Tool 7.4)"
```

---

### Task 5: Optional PDF output via fpdf2

Adds `build_pdf_report()`. fpdf2 is imported lazily. Tests skip when fpdf2 is absent (they also require Pillow, already guarded by the module-level `pytest.importorskip` at the top of `test_inspection_report_photos.py`).

**Files:**
- Modify: `autogis/core/envmon/generate_inspection_report.py` (append `build_pdf_report`)
- Modify: `tests/envmon/test_inspection_report_photos.py` (append PDF tests)

**Interfaces:**
- Consumes: `list[WellReportSection]`, `_load_prepared_image`, `fpdf.FPDF`
- Produces:
  - `build_pdf_report(sections, *, site_id, harvest_dir, output_path, max_photo_px=800, title=None) -> None`

- [ ] **Step 1: Write failing tests**

Append to `tests/envmon/test_inspection_report_photos.py` (after the existing Pillow-only tests):

```python
# ── PDF tests — require Pillow (already guarded above) + fpdf2 ───────────────
fpdf = pytest.importorskip("fpdf")

from autogis.core.envmon.generate_inspection_report import build_pdf_report  # noqa: E402


def _make_real_section(tmp_path: Path) -> "WellReportSection":
    """Build a WellReportSection with a real tiny JPEG on disk."""
    from autogis.core.envmon.generate_inspection_report import (
        InspectionRecord, InspectionPhotoEntry, WellReportSection,
    )
    photo_p = _make_jpeg(tmp_path, width=40, height=30, orientation=1)
    dest = tmp_path / "MW-01" / "photo.jpg"
    dest.parent.mkdir(exist_ok=True)
    dest.write_bytes(photo_p.read_bytes())
    record = InspectionRecord(
        well_id="MW-01", inspection_date="2026-06-15",
        inspector="J. Smith", condition="Good",
        depth_to_water_ft=12.34, notes="OK",
    )
    photo = InspectionPhotoEntry("photo.jpg", str(dest), 1, 1)
    return WellReportSection(well_id="MW-01", record=record, photos=[photo])


def test_build_pdf_report_creates_file(tmp_path):
    section = _make_real_section(tmp_path)
    out = tmp_path / "report.pdf"
    build_pdf_report([section], site_id="H281", harvest_dir=tmp_path,
                     output_path=out, max_photo_px=200)
    assert out.exists()
    assert out.stat().st_size > 0


def test_build_pdf_report_is_pdf(tmp_path):
    section = _make_real_section(tmp_path)
    out = tmp_path / "report.pdf"
    build_pdf_report([section], site_id="H281", harvest_dir=tmp_path,
                     output_path=out, max_photo_px=200)
    assert out.read_bytes()[:5] == b"%PDF-"


def test_build_pdf_report_no_photos_renders_cleanly(tmp_path):
    from autogis.core.envmon.generate_inspection_report import (
        InspectionRecord, WellReportSection,
    )
    record = InspectionRecord("MW-02", "2026-06-15", "J. Smith")
    section = WellReportSection(well_id="MW-02", record=record, photos=[])
    out = tmp_path / "report.pdf"
    build_pdf_report([section], site_id="H281", harvest_dir=tmp_path,
                     output_path=out, max_photo_px=200)
    assert out.exists()
    assert out.stat().st_size > 0


def test_build_pdf_report_no_record_renders_cleanly(tmp_path):
    from autogis.core.envmon.generate_inspection_report import WellReportSection
    section = WellReportSection(well_id="MW-99", record=None, photos=[])
    out = tmp_path / "report.pdf"
    build_pdf_report([section], site_id="H281", harvest_dir=tmp_path,
                     output_path=out, max_photo_px=200)
    assert out.exists()
    assert out.stat().st_size > 0


def test_build_pdf_report_missing_fpdf2_raises(tmp_path):
    """Shadowing fpdf in sys.modules causes build_pdf_report to raise ImportError."""
    import sys
    from autogis.core.envmon.generate_inspection_report import WellReportSection
    section = WellReportSection("MW-01", None, [])
    out = tmp_path / "report.pdf"
    original = sys.modules.get("fpdf")
    sys.modules["fpdf"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(ImportError, match="fpdf2"):
            build_pdf_report([section], site_id="H281", harvest_dir=tmp_path,
                             output_path=out, max_photo_px=200)
    finally:
        if original is None:
            sys.modules.pop("fpdf", None)
        else:
            sys.modules["fpdf"] = original
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/envmon/test_inspection_report_photos.py -v -k "pdf"
```

Expected: FAIL — `build_pdf_report` not defined yet. (If fpdf2 is absent, tests skip cleanly.)

- [ ] **Step 3: Append `build_pdf_report` to `autogis/core/envmon/generate_inspection_report.py`**

Add after `build_html_report`:

```python
# ── PDF renderer (Pillow + fpdf2 — both lazy imports) ────────────────────────

def build_pdf_report(
    sections: list[WellReportSection],
    *,
    site_id: str,
    harvest_dir: Path,
    output_path: Path,
    max_photo_px: int = 800,
    title: Optional[str] = None,
) -> None:
    """Write a PDF inspection photo report to output_path.

    Requires Pillow>=9.0 and fpdf2>=2.7. Install with:
        pip install 'autogis[report]'

    Layout: one page per well; metadata table followed by two photos per row.
    Photos are prepared via _load_prepared_image (EXIF-corrected, resized).
    Missing files render as a text placeholder.

    Args:
        sections: list of WellReportSection from build_sections().
        site_id: site identifier for the header.
        harvest_dir: root directory of the harvest run.
        output_path: destination PDF file path (parent dirs created if absent).
        max_photo_px: max dimension per photo in pixels.
        title: report title override.
    """
    try:
        from fpdf import FPDF
    except (ImportError, TypeError) as exc:
        raise ImportError(
            "fpdf2 is required for PDF output. "
            "Install with: pip install 'autogis[report]'"
        ) from exc

    import io as _io
    from datetime import date

    harvest_dir = Path(harvest_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_title = title or f"Well Inspection Photo Report — {site_id}"

    # A4 layout constants (millimetres)
    MARGIN = 15
    PAGE_W = 210
    USABLE_W = PAGE_W - 2 * MARGIN
    PHOTO_W = (USABLE_W - 5) / 2    # two columns with 5 mm gutter
    MAX_PHOTO_H = 80                  # cap photo row height

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=MARGIN)

    for section in sections:
        pdf.add_page()

        # Header bar
        pdf.set_fill_color(44, 95, 138)     # #2c5f8a
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, section.well_id, new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

        # Metadata table
        if section.record:
            r = section.record
            dtw = (f"{r.depth_to_water_ft:.2f} ft"
                   if r.depth_to_water_ft is not None else "—")
            for label, value in [
                ("Inspection Date:", r.inspection_date),
                ("Inspector:", r.inspector),
                ("Condition:", r.condition or "—"),
                ("Depth to Water:", dtw),
                ("Notes:", r.notes or "—"),
            ]:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(48, 6, label)
                pdf.set_font("Helvetica", "", 10)
                pdf.multi_cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 6, "No inspection record for this well.",
                     new_x="LMARGIN", new_y="NEXT")

        pdf.ln(4)

        # Photos
        if not section.photos:
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 6, "No photos downloaded for this well.",
                     new_x="LMARGIN", new_y="NEXT")
            continue

        col = 0
        current_row_y = pdf.get_y()

        for entry in section.photos:
            img = _load_prepared_image(Path(entry.saved_path), max_photo_px)
            if img is None:
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 6, f"[File not on disk: {entry.original_name}]",
                         new_x="LMARGIN", new_y="NEXT")
                col = 0
                current_row_y = pdf.get_y()
                continue

            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            buf.seek(0)

            x = MARGIN + col * (PHOTO_W + 5)
            pdf.image(buf, x=x, y=current_row_y, w=PHOTO_W, h=0)

            col += 1
            if col >= 2:
                w_px, h_px = img.size
                aspect = h_px / max(w_px, 1)
                row_h = min(PHOTO_W * aspect, MAX_PHOTO_H)
                pdf.set_y(current_row_y + row_h + 6)
                col = 0
                current_row_y = pdf.get_y()

        if col == 1:
            # Odd photo at end of section; advance past estimated height
            pdf.set_y(current_row_y + MAX_PHOTO_H + 6)

    pdf.output(str(output_path))
```

- [ ] **Step 4: Run all photo + PDF tests**

```
python -m pytest tests/envmon/test_inspection_report_photos.py -v
```

Expected: all Pillow-gated tests PASS; fpdf2-gated PDF tests PASS when fpdf2 installed, skip when absent.

- [ ] **Step 5: Full suite + commit**

```bash
python -m pytest -q
git add autogis/core/envmon/generate_inspection_report.py \
        tests/envmon/test_inspection_report_photos.py
git commit -m "feat(envmon): build_pdf_report — fpdf2 headless per-well PDF (Tool 7.4)"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| Problem statement | Goal / Scope |
| Scope and non-goals | Scope section |
| Inputs: harvest manifest + attachments | Task 1 `match_photos_to_wells` |
| Inputs: inspection records | Task 1 `load_inspection_records` |
| Headless core API | Tasks 1–3, 5 — full signatures in Interfaces |
| Report layout — HTML | Task 3 `build_html_report` |
| Report layout — PDF | Task 5 `build_pdf_report` |
| Library names | Tech Stack: Pillow, fpdf2 |
| CLI surface | Task 4 `generate-inspection-report` |
| TDD — tests first | All 5 tasks: Step 1 = write tests, Step 2 = confirm FAIL |
| Fixture images / metadata | Tasks 1 (`_write_inspections_csv`, `_write_manifest_csv`), 2 (`_make_jpeg`, `_make_rgba_png`) |
| Risk: missing photos | Task 3 `test_build_html_report_file_not_on_disk_shows_placeholder` |
| Risk: oversized photos | Task 2 `test_oversized_photo_resized_to_max_px` |
| Risk: EXIF orientation | Task 2 `test_exif_orientation_6_transposes_dimensions` |
| Risk: RGBA → JPEG | Task 2 `test_rgba_png_converted_to_rgb` |

### Type consistency check

All tasks reference:
- `InspectionRecord` — defined Task 1, imported in Tasks 2–5 tests ✓
- `InspectionPhotoEntry` — defined Task 1, used in Task 1 tests and Tasks 3–5 ✓
- `WellReportSection` — defined Task 1, consumed by `build_html_report` (Task 3) and `build_pdf_report` (Task 5) ✓
- `_load_prepared_image(path: Path, max_px: int) -> PIL.Image | None` — defined Task 2, mocked in Task 3 tests, called in Task 5 ✓
- `build_html_report(sections, *, site_id, harvest_dir, max_photo_px, title, generated_date)` — CLI Task 4 call matches Task 3 signature ✓
- `build_pdf_report(sections, *, site_id, harvest_dir, output_path, max_photo_px, title)` — CLI Task 4 `--pdf` call matches Task 5 signature ✓

### Placeholder scan

No "TBD", "TODO", "implement later", "fill in details", "add appropriate error handling", or "similar to Task N" found. Every step contains complete code.

---

## Risk Table

| Risk | Consequence | Mitigation in this plan |
|---|---|---|
| EXIF orientation (iPhone/Android tag 274 ≠ 1) | Photos display sideways | `PIL.ImageOps.exif_transpose` in `_load_prepared_image`; tested with tag=6 (90° CW) |
| Oversized source photos (20 MB RAW, full-res JPEG) | HTML balloons; browser OOM | `img.thumbnail(max_photo_px)` (default 800 px); `--max-photo-px` CLI flag |
| RGBA/PNG attachments | `OSError: cannot write mode RGBA as JPEG` | Convert RGBA → white-background RGB before JPEG save; tested in `test_rgba_png_converted_to_rgb` |
| Photo file missing on disk (manifest=failed) | Broken `<img>` tag or crash | `_load_prepared_image` returns `None`; renderer emits "File not on disk" placeholder text; tested in `test_build_html_report_file_not_on_disk_shows_placeholder` |
| group_template not well-id-based | All photos under unexpected key; zero matches | Documented as pilot assumption in module docstring; isolated in `match_photos_to_wells`; test `test_match_photos_path_outside_harvest_dir_is_skipped` covers the degenerate case |
| Pillow or fpdf2 absent at runtime | Crash without helpful message | Lazy import with `ImportError` pointing to `pip install 'autogis[report]'`; tested in `test_load_prepared_image_no_pillow_raises` and `test_build_pdf_report_missing_fpdf2_raises` |
| 100+ photos per well | HTML payload exceeds browser limit; PDF render time | Documented in `--max-photo-px --help`; no hard cap in v1 — recommend ≤200 photos per well as operational guideline |
| Non-JPEG, non-PNG format (TIFF, HEIC) | Pillow may raise `UnidentifiedImageError` | Pillow supports TIFF natively; HEIC requires pillow-heif plugin (out of scope); `_load_prepared_image` propagates unknown-format exceptions so CLI surfaces them rather than silently skipping |
