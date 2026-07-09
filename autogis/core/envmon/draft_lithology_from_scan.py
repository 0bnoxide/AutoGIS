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
