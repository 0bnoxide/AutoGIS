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
    "secondary_material": ["secondary material", "secondary soil type"],
}


def _normalize_header(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the "fuzzy" part of
    the header-alias match (real scans carry parens, extra spaces, etc.)."""
    cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
    return " ".join(cleaned.split())


def _alias_matches(alias_tokens: list[str], header_tokens: list[str]) -> bool:
    """True if *alias_tokens* appear as a contiguous run within *header_tokens*
    (whole-token match, so the alias "to" matches a "To" column but not
    "Total")."""
    n = len(alias_tokens)
    if not n:
        return False
    return any(header_tokens[i:i + n] == alias_tokens
               for i in range(len(header_tokens) - n + 1))


def map_columns(header_row: list[str]) -> dict[int, str]:
    """Fuzzy-match header cells to LithologyInterval field names.

    Matching is on whole normalized tokens (see _normalize_header), not raw
    substrings, so a short alias like "to" matches a column literally headed
    "To" but never bleeds into "Total". When several aliases match one column,
    the alias with the most tokens wins ("secondary material" beats the bare
    "material"), tie-broken by declaration order in HEADER_ALIASES. A column
    matching no alias is omitted (its data is preserved in the row but mapped
    to no LithologyInterval field).
    """
    mapped: dict[int, str] = {}
    for index, raw in enumerate(header_row):
        header_tokens = _normalize_header(raw).split()
        if not header_tokens:
            continue
        best_field: Optional[str] = None
        best_len = 0
        for field_name, aliases in HEADER_ALIASES.items():
            for alias in aliases:
                alias_tokens = alias.split()
                if _alias_matches(alias_tokens, header_tokens) and \
                        len(alias_tokens) > best_len:
                    best_field = field_name
                    best_len = len(alias_tokens)
        if best_field is not None:
            mapped[index] = best_field
    return mapped


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
