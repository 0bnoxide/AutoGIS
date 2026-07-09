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
