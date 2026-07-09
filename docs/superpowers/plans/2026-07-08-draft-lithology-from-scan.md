# DraftLithologyFromScan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a headless, arcpy-free tool that OCRs a scanned/PDF boring log into a
draft `lithology.csv` (human-reviewed, never authoritative) using Table-Transformer
for table structure and TrOCR for cell text, per the approved design at
`docs/superpowers/specs/2026-07-08-draft-lithology-from-scan-design.md`.

**Architecture:** One new arcpy-free module
(`autogis/core/envmon/draft_lithology_from_scan.py`) with a pure header-alias column
mapper, a confidence→QA-severity flagger, and a model-backed pipeline
(rasterize → detect table → recognize structure → OCR cells → map columns → rows).
One new headless CLI command wires it in, gated on the new `ocr` optional dependency
extra rather than the arcpy `_guard()` mechanism.

**Tech Stack:** Python 3.10+, `transformers`/`torch` (Table-Transformer + TrOCR via
`pipeline("object-detection", ...)` and `VisionEncoderDecoderModel`), `pymupdf`
(`fitz`) for PDF rasterization, `Pillow` for image cropping, stdlib `csv` for output,
existing `QACollector`/`LithologyInterval`.

## Global Constraints

- Core/adapters stay importable with **zero** OCR dependencies installed — every
  `torch`/`transformers`/`fitz` import in the new module is a lazy, function-local
  import, never a module-level import. (CLAUDE.md: "`core/` and `adapters/` import
  with neither `arcpy` nor `arcgis` present" — same discipline applies to this new
  optional dependency group.)
- No new schema: reuse `LithologyInterval` from `autogis/core/common/schema/boring.py`
  exactly as-is (spec: Architecture).
- Output CSV headers must exactly match what `parse_lithology_csv()` in
  `autogis/core/envmon/import_boring_logs.py` already reads: `BoringID`,
  `TopDepth_ft`, `BottomDepth_ft`, `USCS`, `PrimaryMaterial`, `Color`, `Moisture`,
  `Description` (spec: Architecture).
- CLI command is **headless** — no `_guard()` call, same class as
  `validate-boring-logs` (spec: CLI Command). It gates instead on the `ocr` extra
  being importable, raising `click.ClickException` with a
  `pip install autogis[ocr]` hint before touching any model (spec: CLI Command).
- Confidence → QA severity bands are fixed (spec: Confidence → QA Severity Mapping):
  - no table detected on any page → `SEV_ERROR`
  - row avg cell confidence < 0.6 → `SEV_WARNING`
  - row avg cell confidence 0.6–0.85 → `SEV_INFO`
  - row avg cell confidence ≥ 0.85 → no flag
- The QA gate is advisory only — the CLI does **not** call `qa.has_blocking()` to
  stop writing the CSV (spec: Confidence → QA Severity Mapping).
- Module and CLI help text carry an explicit DRAFT banner, matching the
  `draft_plume_boundary.py` / `screening_levels.yaml` convention (spec: Approach —
  DRAFT status).
- New optional extra in `pyproject.toml`: `ocr = ["torch", "transformers", "pillow",
  "pymupdf"]` (spec: Dependency Scope).

---

## File Structure

```
autogis/
  core/envmon/
    draft_lithology_from_scan.py       ← NEW (this plan builds it incrementally)
  adapters/
    cli.py                             ← MODIFY: add draft-lithology-from-scan command
pyproject.toml                         ← MODIFY: add `ocr` optional extra
tests/envmon/
  test_draft_lithology_from_scan.py    ← NEW: core module tests
  test_cli_draft_lithology_from_scan.py ← NEW: CLI wiring tests (splits core vs. CLI
                                           tests, matching the existing
                                           test_subsurface_profile.py /
                                           test_cli_subsurface_profile.py split)
```

**Note on scope:** the model-backed pipeline functions
(`rasterize_pdf`, `extract_table_regions`, `recognize_structure`, `ocr_cells`) call
real Hugging Face models. This environment has no `torch`/`transformers`/`fitz`
installed and no real scanned boring-log fixture (the spec's own Test Strategy item
5 flags this as a known, non-blocking gap). Task 4 below writes real, idiomatic
implementations against the documented `transformers` pipeline output schema, but
its tests are gated behind `pytest.importorskip(...)` and will not execute in this
environment — this matches the spec's explicit test strategy, not a shortcut taken
by this plan.

---

### Task 1: Dataclasses + header-alias column mapping

**Files:**
- Create: `autogis/core/envmon/draft_lithology_from_scan.py`
- Test: `tests/envmon/test_draft_lithology_from_scan.py`

**Interfaces:**
- Produces: `TableRegion(bbox: tuple[float,float,float,float], confidence: float)`,
  `CellResult(text: str, confidence: float)`,
  `TableGrid(header_row: list[str], rows: list[list[CellResult]], cell_boxes: list[list[tuple[float,float,float,float]]] = [], source_image=None)`,
  `DraftResult(rows: list[LithologyInterval], qa: QACollector)`,
  `HEADER_ALIASES: dict[str, list[str]]`, `map_columns(header_row: list[str]) -> dict[int, str]`.
  Later tasks import all of these from this same module.

- [ ] **Step 1: Write the failing test**

Create `tests/envmon/test_draft_lithology_from_scan.py`:

```python
"""Tests for draft_lithology_from_scan.py — arcpy-free.

Model-backed steps (rasterize_pdf, extract_table_regions, recognize_structure,
the TrOCR call inside ocr_cells) are integration-only and gated behind
pytest.importorskip; everything else here runs with zero OCR dependencies
installed, matching the dev extras already used for Pillow/matplotlib-gated
tests elsewhere in tests/envmon/.
"""
from autogis.core.envmon.draft_lithology_from_scan import map_columns


def test_map_columns_matches_known_aliases():
    header = ["Boring No", "Depth From", "Depth To", "USCS Symbol",
              "Soil Description", "Color", "Moisture Content", "Material"]
    result = map_columns(header)
    assert result == {
        0: "boring_id", 1: "top_depth", 2: "bottom_depth", 3: "uscs",
        4: "description", 5: "color", 6: "moisture", 7: "primary_material",
    }


def test_map_columns_ignores_unrecognized_header():
    header = ["Boring No", "Sample Type", "Blow Counts"]
    result = map_columns(header)
    assert result == {0: "boring_id"}


def test_map_columns_is_case_and_punctuation_insensitive():
    header = ["BORING-ID", "top depth (ft)", "bottom depth (ft)"]
    result = map_columns(header)
    assert result[0] == "boring_id"
    assert result[1] == "top_depth"
    assert result[2] == "bottom_depth"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autogis.core.envmon.draft_lithology_from_scan'`

- [ ] **Step 3: Write the module skeleton + dataclasses + column mapping**

Create `autogis/core/envmon/draft_lithology_from_scan.py`:

```python
"""draft_lithology_from_scan.py — DRAFT boring-log OCR digitization assist.

WARNING: All output is an unreviewed DRAFT. This module OCRs a scanned/PDF
boring log (Table-Transformer for table structure, TrOCR for cell text) into a
draft lithology.csv matching the exact columns parse_lithology_csv() already
expects. It is a transcription aid for analyst review — NOT an authoritative
importer. No real scanned boring-log sample has been used to validate this
pipeline (see docs/superpowers/specs/2026-07-08-draft-lithology-from-scan-design.md,
Test Strategy item 5); every row this tool produces must be checked against the
original scan, then run through `autogis envmon validate-boring-logs` before
anything downstream touches it.

Out of scope: the phase-gated AI-assisted tools group (CLAUDE.md §11) — this is
document OCR/table-structure ML, not an LLM-driven judgment tool.

arcpy usage: NONE. This module is arcpy-free.

Dependency note: `torch`/`transformers`/`fitz` (pymupdf) are imported lazily
inside the functions that need them, never at module level, so this module
stays importable with the `ocr` extra absent — only calling the model-backed
functions (rasterize_pdf, extract_table_regions, recognize_structure, ocr_cells)
requires it installed (`pip install autogis[ocr]`).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ..common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from ..common.schema.boring import LithologyInterval


@dataclass
class TableRegion:
    bbox: tuple[float, float, float, float]
    confidence: float


@dataclass
class CellResult:
    text: str
    confidence: float


@dataclass
class TableGrid:
    header_row: list[str]
    rows: list[list["CellResult"]]
    # Internal plumbing from recognize_structure to ocr_cells — cell pixel
    # boxes (row-major, row 0 = header) and the cropped table image they were
    # detected against. Not part of the documented header_row/rows contract.
    cell_boxes: list[list[tuple[float, float, float, float]]] = field(default_factory=list)
    source_image: Optional[object] = None


@dataclass
class DraftResult:
    rows: list[LithologyInterval]
    qa: QACollector


# Field name (matches LithologyInterval attribute names) -> known header text
# variants. Matching is case/punctuation-insensitive (see _normalize_header).
HEADER_ALIASES: dict[str, list[str]] = {
    "boring_id": ["boring id", "boring no", "boring", "hole id", "hole no"],
    "top_depth": ["top depth", "depth from", "from"],
    "bottom_depth": ["bottom depth", "depth to", "to"],
    "uscs": ["uscs", "uscs symbol", "symbol", "class", "classification"],
    "description": ["description", "soil description", "remarks"],
    "color": ["color", "colour"],
    "moisture": ["moisture", "moisture content"],
    "primary_material": ["material", "soil type", "primary material"],
}


def _normalize_header(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the "fuzzy" part of
    the header-alias match (real scans carry parens, extra spaces, etc.)."""
    cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
    return " ".join(cleaned.split())


def map_columns(header_row: list[str]) -> dict[int, str]:
    """Fuzzy-match header cells to LithologyInterval field names.

    First alias match wins per column; a column matching no known alias is
    omitted from the result (its data is preserved in the row but not mapped
    onto any LithologyInterval field).
    """
    mapped: dict[int, str] = {}
    for index, raw in enumerate(header_row):
        normalized = _normalize_header(raw)
        if not normalized:
            continue
        for field_name, aliases in HEADER_ALIASES.items():
            if any(normalized == alias or alias in normalized
                   for alias in aliases):
                mapped[index] = field_name
                break
    return mapped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/draft_lithology_from_scan.py tests/envmon/test_draft_lithology_from_scan.py
git commit -m "feat(envmon): add draft_lithology_from_scan header-alias column mapping"
```

---

### Task 2: Confidence → QA severity flagging + row building

**Files:**
- Modify: `autogis/core/envmon/draft_lithology_from_scan.py`
- Test: `tests/envmon/test_draft_lithology_from_scan.py`

**Interfaces:**
- Consumes: `CellResult`, `TableGrid`, `HEADER_ALIASES`, `map_columns` from Task 1.
- Produces: `_to_float(text: str) -> Optional[float]`,
  `_flag_row_confidence(qa: QACollector, avg_confidence: float, page_number: int, row_number: int) -> None`,
  `_row_to_lithology_interval(row_cells: list[CellResult], field_to_index: dict[str,int], qa: QACollector, page_number: int, row_number: int) -> Optional[LithologyInterval]`.
  Task 4's `draft_lithology()` calls these directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/envmon/test_draft_lithology_from_scan.py`:

```python
from autogis.core.common.qa import QACollector, SEV_ERROR, SEV_WARNING, SEV_INFO
from autogis.core.envmon.draft_lithology_from_scan import (
    CellResult, _flag_row_confidence, _row_to_lithology_interval, _to_float,
)


def test_to_float_parses_valid_number():
    assert _to_float("12.5") == 12.5


def test_to_float_returns_none_for_garbage():
    assert _to_float("illegible") is None
    assert _to_float("") is None


def test_flag_row_confidence_low_is_warning():
    qa = QACollector()
    _flag_row_confidence(qa, 0.4, page_number=1, row_number=3)
    assert qa.records[0].severity == SEV_WARNING
    assert "verify against scan" in qa.records[0].message


def test_flag_row_confidence_moderate_is_info():
    qa = QACollector()
    _flag_row_confidence(qa, 0.7, page_number=1, row_number=3)
    assert qa.records[0].severity == SEV_INFO
    assert "spot-check" in qa.records[0].message


def test_flag_row_confidence_high_is_unflagged():
    qa = QACollector()
    _flag_row_confidence(qa, 0.9, page_number=1, row_number=3)
    assert qa.records == []


def test_row_to_lithology_interval_builds_from_mapped_columns():
    qa = QACollector()
    field_to_index = {"boring_id": 0, "top_depth": 1, "bottom_depth": 2,
                       "uscs": 3, "description": 4}
    row = [CellResult("MW-1", 0.95), CellResult("2.0", 0.95),
           CellResult("4.0", 0.95), CellResult("CL", 0.95),
           CellResult("Lean clay, brown", 0.95)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 1)
    assert interval.boring_id == "MW-1"
    assert interval.top_depth == 2.0
    assert interval.bottom_depth == 4.0
    assert interval.uscs == "CL"
    assert interval.description == "Lean clay, brown"
    assert qa.records == []  # confidence 0.95 -> no flag


def test_row_to_lithology_interval_drops_row_with_unparseable_depth():
    qa = QACollector()
    field_to_index = {"boring_id": 0, "top_depth": 1, "bottom_depth": 2}
    row = [CellResult("MW-1", 0.9), CellResult("illegible", 0.3),
           CellResult("4.0", 0.9)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 2)
    assert interval is None
    assert qa.records[0].severity == SEV_WARNING
    assert qa.records[0].category == "row_dropped_unparseable_depth"


def test_row_to_lithology_interval_flags_missing_boring_id():
    qa = QACollector()
    field_to_index = {"top_depth": 0, "bottom_depth": 1}
    row = [CellResult("2.0", 0.9), CellResult("4.0", 0.9)]
    interval = _row_to_lithology_interval(row, field_to_index, qa, 1, 1)
    assert interval.boring_id == ""
    assert any(r.category == "boring_id_not_detected" for r in qa.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: FAIL with `ImportError: cannot import name '_flag_row_confidence'`

- [ ] **Step 3: Implement the flagging + row-building helpers**

Append to `autogis/core/envmon/draft_lithology_from_scan.py`:

```python
def _to_float(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _flag_row_confidence(qa: QACollector, avg_confidence: float,
                          page_number: int, row_number: int) -> None:
    where = f"page {page_number} row {row_number}"
    if avg_confidence < 0.6:
        qa.add(SEV_WARNING, "low_confidence_row",
               f"{where}: avg OCR confidence {avg_confidence:.2f} — "
               f"verify against scan")
    elif avg_confidence < 0.85:
        qa.add(SEV_INFO, "moderate_confidence_row",
               f"{where}: avg OCR confidence {avg_confidence:.2f} — "
               f"low-moderate confidence, spot-check")


def _row_to_lithology_interval(
    row_cells: list["CellResult"], field_to_index: dict[str, int],
    qa: QACollector, page_number: int, row_number: int,
) -> Optional[LithologyInterval]:
    """Build one LithologyInterval from a mapped OCR row, or None if the
    row's depths can't be parsed (dropped, matching parse_lithology_csv's
    existing missing-depth convention in import_boring_logs.py)."""
    def _cell_text(field_name: str) -> str:
        index = field_to_index.get(field_name)
        if index is None or index >= len(row_cells):
            return ""
        return row_cells[index].text.strip()

    top = _to_float(_cell_text("top_depth"))
    bottom = _to_float(_cell_text("bottom_depth"))
    where = f"page {page_number} row {row_number}"
    if top is None or bottom is None:
        qa.add(SEV_WARNING, "row_dropped_unparseable_depth",
               f"{where}: could not parse TopDepth_ft/BottomDepth_ft, row skipped")
        return None

    boring_id = _cell_text("boring_id")
    if not boring_id:
        qa.add(SEV_WARNING, "boring_id_not_detected",
               f"{where}: BoringID column not detected or empty; fill in "
               f"manually before validate-boring-logs")

    if row_cells:
        avg_confidence = sum(c.confidence for c in row_cells) / len(row_cells)
        _flag_row_confidence(qa, avg_confidence, page_number, row_number)

    return LithologyInterval(
        boring_id=boring_id, top_depth=top, bottom_depth=bottom,
        uscs=_cell_text("uscs"), primary_material=_cell_text("primary_material"),
        color=_cell_text("color"), moisture=_cell_text("moisture"),
        description=_cell_text("description"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/draft_lithology_from_scan.py tests/envmon/test_draft_lithology_from_scan.py
git commit -m "feat(envmon): add confidence-to-QA-severity flagging and row building"
```

---

### Task 3: write_draft_csv + round-trip with the existing parser

**Files:**
- Modify: `autogis/core/envmon/draft_lithology_from_scan.py`
- Test: `tests/envmon/test_draft_lithology_from_scan.py`

**Interfaces:**
- Consumes: `LithologyInterval` (Task 1 import), `parse_lithology_csv` from
  `autogis.core.envmon.import_boring_logs` (test-only).
- Produces: `write_draft_csv(rows: list[LithologyInterval], out_path: Path) -> Path`.
  Task 5's CLI command calls this directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/envmon/test_draft_lithology_from_scan.py`:

```python
from autogis.core.common.schema.boring import LithologyInterval
from autogis.core.envmon.draft_lithology_from_scan import write_draft_csv
from autogis.core.envmon.import_boring_logs import parse_lithology_csv


def test_write_draft_csv_round_trips_through_existing_parser(tmp_path):
    rows = [
        LithologyInterval(boring_id="MW-1", top_depth=0.0, bottom_depth=2.0,
                           uscs="ML", primary_material="Silt", color="Brown",
                           moisture="Moist", description="Sandy silt"),
        LithologyInterval(boring_id="MW-1", top_depth=2.0, bottom_depth=5.0,
                           uscs="CL", primary_material="Clay", color="Gray",
                           moisture="Wet", description="Lean clay"),
    ]
    out_path = write_draft_csv(rows, tmp_path / "lithology.csv")
    assert out_path.exists()

    parsed = parse_lithology_csv(out_path)
    assert len(parsed) == 2
    assert parsed[0].boring_id == "MW-1"
    assert parsed[0].top_depth == 0.0
    assert parsed[0].bottom_depth == 2.0
    assert parsed[0].uscs == "ML"
    assert parsed[0].description == "Sandy silt"
    assert parsed[1].color == "Gray"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: FAIL with `ImportError: cannot import name 'write_draft_csv'`

- [ ] **Step 3: Implement write_draft_csv**

Append to `autogis/core/envmon/draft_lithology_from_scan.py`:

```python
def write_draft_csv(rows: list[LithologyInterval], out_path: Path) -> Path:
    """Write draft lithology rows using the exact headers
    parse_lithology_csv() (import_boring_logs.py) already expects."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["BoringID", "TopDepth_ft", "BottomDepth_ft", "USCS",
                  "PrimaryMaterial", "Color", "Moisture", "Description"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "BoringID": row.boring_id,
                "TopDepth_ft": row.top_depth,
                "BottomDepth_ft": row.bottom_depth,
                "USCS": row.uscs,
                "PrimaryMaterial": row.primary_material,
                "Color": row.color,
                "Moisture": row.moisture,
                "Description": row.description,
            })
    return out_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add autogis/core/envmon/draft_lithology_from_scan.py tests/envmon/test_draft_lithology_from_scan.py
git commit -m "feat(envmon): write draft lithology CSV matching parse_lithology_csv headers"
```

---

### Task 4: Model-backed pipeline (rasterize → detect → recognize → OCR → orchestrate)

**Files:**
- Modify: `autogis/core/envmon/draft_lithology_from_scan.py`
- Modify: `pyproject.toml`
- Test: `tests/envmon/test_draft_lithology_from_scan.py`

**Interfaces:**
- Consumes: `TableRegion`, `TableGrid`, `CellResult`, `DraftResult`, `map_columns`,
  `_row_to_lithology_interval` from Tasks 1–2; `write_draft_csv` unaffected.
- Produces: `rasterize_pdf(path: Path, dpi: int = 200) -> list`,
  `extract_table_regions(image) -> list[TableRegion]`,
  `recognize_structure(image, region: TableRegion) -> TableGrid`,
  `ocr_cells(grid: TableGrid, *, handwritten: bool = False) -> TableGrid`,
  `draft_lithology(scan_path: Path, *, handwritten: bool = False) -> DraftResult`.
  Task 5's CLI command calls `draft_lithology` and `write_draft_csv` only.

**Note:** this environment has no `torch`/`transformers`/`fitz` installed and no
real scanned fixture. Steps 1–2 below add `pytest.importorskip` guards so these
tests report SKIPPED here rather than ERROR — this is expected, matches spec Test
Strategy item 4, and is not something to "fix" in this environment.

- [ ] **Step 1: Add the `ocr` extra to pyproject.toml**

In `pyproject.toml`, after the `profile = [...]` line (line 21), add:

```toml
ocr = ["torch", "transformers", "pillow", "pymupdf"]   # boring-log OCR digitization assist (draft-lithology-from-scan); DRAFT tool, see docs/superpowers/specs/2026-07-08-draft-lithology-from-scan-design.md
```

- [ ] **Step 2: Write the (skip-gated) failing tests**

Append to `tests/envmon/test_draft_lithology_from_scan.py`:

```python
import pytest

from autogis.core.envmon.draft_lithology_from_scan import (
    draft_lithology, extract_table_regions, ocr_cells, rasterize_pdf,
    recognize_structure,
)


def test_rasterize_pdf_returns_one_image_per_page(tmp_path):
    pytest.importorskip("fitz")
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    pages = rasterize_pdf(pdf_path)
    assert len(pages) == 2


def test_draft_lithology_no_table_detected_is_sev_error(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(
        "autogis.core.envmon.draft_lithology_from_scan.extract_table_regions",
        lambda image: [])

    result = draft_lithology(pdf_path)
    assert result.rows == []
    assert any(r.category == "no_table_detected" and r.severity == "ERROR"
               for r in result.qa.records)
```

- [ ] **Step 3: Run tests to verify they fail or skip**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: the two new tests report `ModuleNotFoundError`/`ImportError` for
`rasterize_pdf`/`draft_lithology` (not yet defined) — or SKIPPED if `fitz` is
absent, in which case re-run after Step 4 to confirm they still skip cleanly
rather than error.

- [ ] **Step 4: Implement the model-backed pipeline**

Append to `autogis/core/envmon/draft_lithology_from_scan.py`:

```python
def rasterize_pdf(path: Path, dpi: int = 200) -> list:
    """Render each page of a PDF (or a single-page image file) to a PIL Image."""
    import fitz  # pymupdf

    doc = fitz.open(str(path))
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pages = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=matrix)
            from PIL import Image
            image = Image.frombytes(
                "RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples)
            pages.append(image.convert("RGB"))
    finally:
        doc.close()
    return pages


@lru_cache(maxsize=1)
def _get_detector():
    from transformers import pipeline
    return pipeline("object-detection", model="microsoft/table-transformer-detection")


@lru_cache(maxsize=1)
def _get_structure_recognizer():
    from transformers import pipeline
    return pipeline("object-detection",
                     model="microsoft/table-transformer-structure-recognition")


@lru_cache(maxsize=2)
def _get_trocr(handwritten: bool):
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    name = ("microsoft/trocr-base-handwritten" if handwritten
            else "microsoft/trocr-base-printed")
    processor = TrOCRProcessor.from_pretrained(name)
    model = VisionEncoderDecoderModel.from_pretrained(name)
    model.eval()
    return processor, model


def extract_table_regions(image) -> list["TableRegion"]:
    """Detect table bounding boxes on a page image (table-transformer-detection)."""
    detector = _get_detector()
    results = detector(image)
    regions = []
    for detection in results:
        if detection["label"] != "table":
            continue
        box = detection["box"]
        regions.append(TableRegion(
            bbox=(box["xmin"], box["ymin"], box["xmax"], box["ymax"]),
            confidence=detection["score"]))
    return regions


def recognize_structure(image, region: "TableRegion") -> "TableGrid":
    """Detect row/column geometry inside one table region
    (table-transformer-structure-recognition) and derive per-cell boxes as
    row×column intersections. The topmost detected row is treated as the
    header row (cell text is filled in later by ocr_cells)."""
    crop = image.crop(region.bbox)
    recognizer = _get_structure_recognizer()
    results = recognizer(crop)

    row_boxes = sorted(
        (d["box"] for d in results if d["label"] == "table row"),
        key=lambda b: b["ymin"])
    col_boxes = sorted(
        (d["box"] for d in results if d["label"] == "table column"),
        key=lambda b: b["xmin"])

    cell_boxes: list[list[tuple[float, float, float, float]]] = [
        [(col["xmin"], row["ymin"], col["xmax"], row["ymax"]) for col in col_boxes]
        for row in row_boxes
    ]
    n_cols = len(col_boxes)
    n_data_rows = max(len(cell_boxes) - 1, 0)
    return TableGrid(
        header_row=[""] * n_cols,
        rows=[[CellResult("", 0.0) for _ in range(n_cols)] for _ in range(n_data_rows)],
        cell_boxes=cell_boxes,
        source_image=crop,
    )


def ocr_cells(grid: "TableGrid", *, handwritten: bool = False) -> "TableGrid":
    """Crop + TrOCR each detected cell, filling in header_row and rows."""
    import torch

    if not grid.cell_boxes or grid.source_image is None:
        return grid

    processor, model = _get_trocr(handwritten)

    def _ocr_one(cell_image) -> tuple[str, float]:
        pixel_values = processor(images=cell_image, return_tensors="pt").pixel_values
        with torch.no_grad():
            generated = model.generate(
                pixel_values, output_scores=True,
                return_dict_in_generate=True, max_new_tokens=32)
        text = processor.batch_decode(
            generated.sequences, skip_special_tokens=True)[0].strip()
        if not generated.scores:
            return text, 0.0
        scores = torch.stack(generated.scores, dim=1).softmax(-1)
        token_ids = generated.sequences[:, 1:1 + scores.shape[1]]
        token_probs = scores.gather(-1, token_ids.unsqueeze(-1)).squeeze(-1)
        confidence = float(token_probs.mean()) if token_probs.numel() else 0.0
        return text, confidence

    header_boxes = grid.cell_boxes[0] if grid.cell_boxes else []
    grid.header_row = [_ocr_one(grid.source_image.crop(box))[0] for box in header_boxes]

    new_rows = []
    for row_boxes in grid.cell_boxes[1:]:
        row_cells = []
        for box in row_boxes:
            text, confidence = _ocr_one(grid.source_image.crop(box))
            row_cells.append(CellResult(text=text, confidence=confidence))
        new_rows.append(row_cells)
    grid.rows = new_rows
    return grid


def draft_lithology(scan_path: Path, *, handwritten: bool = False) -> "DraftResult":
    """Full pipeline: rasterize -> detect -> recognize -> OCR -> map -> rows + QA."""
    qa = QACollector()
    qa.add(SEV_INFO, "draft_lithology_from_scan",
           "DRAFT output: OCR/table-structure extraction, human review "
           "required before running validate-boring-logs.")

    pages = rasterize_pdf(Path(scan_path))
    rows: list[LithologyInterval] = []
    found_table = False

    for page_index, image in enumerate(pages):
        for region in extract_table_regions(image):
            found_table = True
            grid = recognize_structure(image, region)
            grid = ocr_cells(grid, handwritten=handwritten)
            column_map = map_columns(grid.header_row)
            field_to_index = {field_name: index
                               for index, field_name in column_map.items()}
            for row_number, row_cells in enumerate(grid.rows, start=1):
                interval = _row_to_lithology_interval(
                    row_cells, field_to_index, qa, page_index + 1, row_number)
                if interval is not None:
                    rows.append(interval)

    if not found_table:
        qa.add(SEV_ERROR, "no_table_detected",
               "no lithology table detected; nothing drafted")

    return DraftResult(rows=rows, qa=qa)
```

- [ ] **Step 5: Run tests to verify pass/skip**

Run: `python -m pytest tests/envmon/test_draft_lithology_from_scan.py -v`
Expected: the 11 tests from Tasks 1–3 still PASS; the two new tests SKIPPED
(missing `fitz`/`torch`/`transformers` in this environment) rather than ERROR.
If `pymupdf` happens to be installed, `test_rasterize_pdf_returns_one_image_per_page`
should PASS.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/envmon/draft_lithology_from_scan.py pyproject.toml tests/envmon/test_draft_lithology_from_scan.py
git commit -m "feat(envmon): add Table-Transformer + TrOCR pipeline for draft_lithology_from_scan"
```

---

### Task 5: CLI command

**Files:**
- Modify: `autogis/adapters/cli.py`
- Test: `tests/envmon/test_cli_draft_lithology_from_scan.py`

**Interfaces:**
- Consumes: `draft_lithology`, `write_draft_csv` from
  `autogis.core.envmon.draft_lithology_from_scan` (Tasks 3–4); `qa_report_options`,
  `_render_qa` already defined in `cli.py`.
- Produces: the `autogis envmon draft-lithology-from-scan` command and a private
  `_require_ocr_extra() -> None` guard (importable for test monkeypatching).

- [ ] **Step 1: Write the failing tests**

Create `tests/envmon/test_cli_draft_lithology_from_scan.py`:

```python
"""CLI wiring tests for draft-lithology-from-scan — no real OCR models are
invoked; draft_lithology()/write_draft_csv() are monkeypatched so these tests
run with zero OCR dependencies installed."""
from click.testing import CliRunner

from autogis.adapters.cli import autogis
from autogis.core.common.qa import QACollector, SEV_INFO
from autogis.core.common.schema.boring import LithologyInterval
from autogis.core.envmon.draft_lithology_from_scan import DraftResult


def test_draft_lithology_from_scan_without_ocr_extra_is_clean_error(tmp_path):
    scan = tmp_path / "log.pdf"
    scan.write_bytes(b"%PDF-1.4 fake")
    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "draft-lithology-from-scan", str(scan),
        "--out-dir", str(tmp_path / "out"),
    ])
    assert result.exit_code != 0
    assert "pip install autogis[ocr]" in result.output


def test_draft_lithology_from_scan_writes_csv_and_renders_qa(tmp_path, monkeypatch):
    scan = tmp_path / "log.pdf"
    scan.write_bytes(b"%PDF-1.4 fake")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        "autogis.adapters.cli._require_ocr_extra", lambda: None)

    def fake_draft_lithology(scan_path, *, handwritten=False):
        qa = QACollector()
        qa.add(SEV_INFO, "draft_lithology_from_scan", "DRAFT output.")
        rows = [LithologyInterval(boring_id="MW-1", top_depth=0.0,
                                   bottom_depth=2.0, uscs="ML",
                                   description="Sandy silt")]
        return DraftResult(rows=rows, qa=qa)

    monkeypatch.setattr(
        "autogis.core.envmon.draft_lithology_from_scan.draft_lithology",
        fake_draft_lithology)

    runner = CliRunner()
    result = runner.invoke(autogis, [
        "envmon", "draft-lithology-from-scan", str(scan),
        "--out-dir", str(out_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "DRAFT" in result.output
    assert (out_dir / "lithology.csv").exists()
    content = (out_dir / "lithology.csv").read_text(encoding="utf-8")
    assert "MW-1" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/envmon/test_cli_draft_lithology_from_scan.py -v`
Expected: FAIL — `Error: No such command 'draft-lithology-from-scan'.`

- [ ] **Step 3: Add the CLI command**

In `autogis/adapters/cli.py`, after the `import_boring_logs_cmd` function (ends
at line 2806, immediately before `@envmon.command("survey-to-well-elevation")`),
insert:

```python
def _require_ocr_extra() -> None:
    """Surface the missing `ocr` extra as a clean click error, not a
    mid-pipeline traceback. Checked via find_spec (no heavy import) so this
    guard doesn't itself require torch/transformers to be importable."""
    import importlib.util
    missing = [mod for mod in ("torch", "transformers", "PIL", "fitz")
               if importlib.util.find_spec(mod) is None]
    if missing:
        raise click.ClickException(
            f"Missing OCR dependencies: {', '.join(missing)}. "
            f"Install with: pip install autogis[ocr]")


@envmon.command("draft-lithology-from-scan")
@click.argument("scan_path", metavar="SCAN_PATH",
                type=click.Path(exists=True, dir_okay=False))
@click.option("--out-dir", "out_dir", required=True, type=click.Path(file_okay=False),
              help="Directory to write the draft lithology.csv into.")
@click.option("--handwritten", is_flag=True, default=False,
              help="Use the handwritten TrOCR model instead of the printed one.")
@qa_report_options
def draft_lithology_from_scan_cmd(scan_path, out_dir, handwritten, report, fail_on):
    """DRAFT: OCR a scanned/PDF boring log into a draft lithology.csv (headless).

    DRAFT TOOL: no real scanned sample has validated this pipeline. Output is
    an unreviewed draft, never authoritative — review every row against the
    original scan, then run 'autogis envmon validate-boring-logs OUT_DIR'
    before anything downstream uses it. Requires the ocr extra
    (pip install autogis[ocr]).
    """
    _require_ocr_extra()
    from autogis.core.envmon.draft_lithology_from_scan import (
        draft_lithology, write_draft_csv)
    result = draft_lithology(Path(scan_path), handwritten=handwritten)
    out_path = write_draft_csv(result.rows, Path(out_dir) / "lithology.csv")
    click.echo(f"DRAFT: wrote {out_path} ({len(result.rows)} row(s)). "
               f"Review against the scan before running validate-boring-logs.")
    _render_qa(result.qa, report, fail_on)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/envmon/test_cli_draft_lithology_from_scan.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: all tests pass (aside from the environment-appropriate SKIPs already
noted in Task 4); no regressions in the rest of the suite.

- [ ] **Step 6: Commit**

```bash
git add autogis/adapters/cli.py tests/envmon/test_cli_draft_lithology_from_scan.py
git commit -m "feat(envmon): add draft-lithology-from-scan CLI command"
```

---

## Self-Review Notes

- **Spec coverage:** every Public API symbol in the spec (`TableRegion`, `TableGrid`,
  `CellResult`, `DraftResult`, `rasterize_pdf`, `extract_table_regions`,
  `recognize_structure`, `ocr_cells`, `HEADER_ALIASES`, `map_columns`,
  `draft_lithology`, `write_draft_csv`) is implemented across Tasks 1–4. The CLI
  command, its headless/no-`_guard()` requirement, the `ocr` extra, the DRAFT
  banner, and the confidence→severity table are covered in Tasks 4–5. The spec's
  explicit non-blocking gap (no real scanned fixture) is preserved as-is, not
  silently "resolved" by this plan.
- **Deviation from the spec's literal file list, called out explicitly:** CLI tests
  live in a separate `test_cli_draft_lithology_from_scan.py` rather than folded into
  `test_draft_lithology_from_scan.py`, matching this repo's existing
  `test_subsurface_profile.py` / `test_cli_subsurface_profile.py` split.
- **Implementation detail beyond the spec's literal dataclass fields:** `TableGrid`
  gained `cell_boxes`/`source_image` fields (both defaulted, so the documented
  `header_row`/`rows` two-argument contract is unchanged) to carry cell geometry
  from `recognize_structure` to `ocr_cells` — required plumbing the spec's API
  sketch didn't need to spell out.
- **Type consistency check:** `LithologyInterval` field names used in
  `_row_to_lithology_interval` (`boring_id`, `top_depth`, `bottom_depth`, `uscs`,
  `primary_material`, `color`, `moisture`, `description`) match
  `autogis/core/common/schema/boring.py` exactly. `HEADER_ALIASES` keys match the
  same field names used by `field_to_index` in `draft_lithology`. `write_draft_csv`
  output columns match what `parse_lithology_csv` reads, verified by the Task 3
  round-trip test.
